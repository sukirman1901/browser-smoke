"""Compact MCP payloads so tool results stay small in the agent context."""

from __future__ import annotations

import json
from typing import Any

# ~6k tokens of JSON; larger results must be narrowed by the caller.
MAX_RESULT_CHARS = 24_000
LOG_CAP = 40
LOG_TEXT_CHARS = 240


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
        if item.get("type"):
            extra.append(item["type"])
        if item.get("href"):
            extra.append(item["href"])
        suffix = f" {' '.join(extra)}" if extra else ""
        quoted = f' "{name}"' if name else ""
        lines.append(f"@{ref} {role}{quoted}{suffix}")
    return "\n".join(lines)


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
