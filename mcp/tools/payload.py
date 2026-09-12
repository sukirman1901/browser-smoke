"""Compact MCP payloads so tool results stay small in the agent context."""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import urlparse

# ~6k tokens of JSON; larger results must be narrowed by the caller.
MAX_RESULT_CHARS = 24_000
LOG_CAP = 40
LOG_TEXT_CHARS = 240
LOG_MEM_CAP = 200
MAX_SNAPSHOT_ITEMS = 80
HREF_CHARS = 40


def dumps(obj: Any) -> str:
    text = json.dumps(obj, separators=(",", ":"), ensure_ascii=False, default=str)
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return json.dumps(
        {
            "status": "truncated",
            "chars": len(text),
            "hint": "Result too large. Use browser_execute with a narrower selector, browser_snapshot, or screenshot=false.",
            "preview": text[:4000],
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )


def compact_element(el: dict) -> dict:
    tag = el.get("tag", "")
    item = {
        "tag": tag,
        "sel": el.get("selector") or el.get("sel", ""),
        "text": (el.get("text") or "")[:60],
    }
    kind = el.get("type")
    if kind and kind != tag:
        item["type"] = kind
    return item


def compact_classified(classified: dict) -> dict:
    return {
        "buttons": [compact_element(e) for e in classified.get("buttons", [])],
        "inputs": [compact_element(e) for e in classified.get("inputs", [])],
        "links": [compact_element(e) for e in classified.get("links", [])],
        "others": [compact_element(e) for e in classified.get("others", [])],
        "total": classified.get("total", 0),
    }


def format_snapshot_lines(items: list[dict]) -> str:
    lines = []
    for item in items:
        ref = item.get("ref")
        role = item.get("role") or item.get("tag") or "generic"
        name = (item.get("name") or "").replace("\n", " ").strip()
        extra = []
        if item.get("iframe"):
            extra.append("iframe")
        if item.get("hidden"):
            extra.append("hidden")
        if item.get("type"):
            extra.append(item["type"])
        if item.get("href"):
            extra.append(item["href"][:HREF_CHARS])
        suffix = f" {' '.join(extra)}" if extra else ""
        quoted = f' "{name}"' if name else ""
        lines.append(f"@{ref} {role}{quoted}{suffix}")
    return "\n".join(lines)


def cap_snapshot_items(
    items: list[dict], limit: int = MAX_SNAPSHOT_ITEMS
) -> tuple[list[dict], int]:
    """Keep file/hidden and cross-origin markers; drop the rest of a huge page."""
    total = len(items)
    if total <= limit:
        return items, total
    pinned: list[dict] = []
    others: list[dict] = []
    for item in items:
        if item.get("hidden") or item.get("name") == "cross-origin":
            pinned.append(item)
        else:
            others.append(item)
    room = max(0, limit - len(pinned))
    return pinned + others[:room], total


def clip_logs(entries: list[dict], *, include_url: bool = False) -> list[dict]:
    clipped = []
    for entry in entries[-LOG_CAP:]:
        row = {
            "type": entry.get("type", "error"),
            "text": str(entry.get("text") or entry.get("message") or "")[:LOG_TEXT_CHARS],
        }
        if include_url and entry.get("url"):
            row["url"] = entry["url"]
        clipped.append(row)
    return clipped


def compact_network(entries: list[dict], *, headers: bool = False) -> list[dict]:
    out = []
    for entry in entries[-LOG_CAP:]:
        row = {
            "method": entry.get("method"),
            "url": entry.get("url"),
            "status": entry.get("status"),
            "type": entry.get("resource_type"),
        }
        if entry.get("error"):
            row["error"] = str(entry["error"])[:LOG_TEXT_CHARS]
        if headers:
            row["headers"] = entry.get("headers")
        out.append(row)
    return out


def cap_append(items: list, item: object, *, cap: int = LOG_MEM_CAP) -> None:
    items.append(item)
    extra = len(items) - cap
    if extra > 0:
        del items[:extra]


def url_glob_source(pattern: str) -> str:
    if pattern in ("*", "**/*", ""):
        return ".*"
    body = re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".")
    if "://" not in pattern and not pattern.startswith("*"):
        body = ".*" + body
    if "://" not in pattern and not pattern.endswith("*"):
        body = body + ".*"
    return body


def matches_url(url: str, patterns: list[str] | None) -> bool:
    if not patterns or any(p in ("*", "**/*", "") for p in patterns):
        return True
    host = urlparse(url).netloc
    for p in patterns:
        try:
            source = url_glob_source(p)
            if re.search(source, url) or (host and re.search(source, host)):
                return True
        except re.error:
            pass
        core = p.replace("*", "")
        if core and (core in url or core in host):
            return True
    return False


def wrap_init_script(script: str, url_pattern: str) -> str:
    if not url_pattern or url_pattern in ("*", "**/*"):
        return script
    source = json.dumps(url_glob_source(url_pattern))
    return (
        "(() => {\n"
        f"  const re = new RegExp({source});\n"
        "  if (!re.test(location.href) && !re.test(location.host)) return;\n"
        f"{script}\n"
        "})();"
    )


def safe_artifact_name(name: str, fallback: str = "shot") -> str:
    base = os.path.basename(name.replace("\\", "/"))
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._")
    return (cleaned[:80] or fallback)
