"""Compact MCP payloads so tool results stay small in the agent context."""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import urlparse

SMOKE_VERSION = "1.6.0"

# Snapshot interactive set. Keep this in sync with SNAPSHOT_JS in browser.py.
SNAPSHOT_SELECTOR = (
    "a, button, input, select, textarea, "
    '[contenteditable]:not([contenteditable="false"]), '
    '[role="button"], [role="link"], [role="textbox"], [role="checkbox"], '
    '[role="menuitem"], [role="option"], [role="tab"], [role="dialog"], '
    '[role="combobox"], [role="listbox"], [role="switch"], [role="treeitem"], '
    '[role="slider"], [tabindex]:not([tabindex="-1"])'
)

# ~6k tokens of JSON; larger results must be narrowed by the caller.
MAX_RESULT_CHARS = 24_000
LOG_CAP = 40
LOG_TEXT_CHARS = 240
LOG_MEM_CAP = 200
MAX_SNAPSHOT_ITEMS = 80
HREF_CHARS = 40

# Roles the agent can click/type. Landmarks and static text stay out to keep tokens down.
INTERACTIVE_ARIA_ROLES = frozenset(
    {
        "button",
        "link",
        "textbox",
        "searchbox",
        "combobox",
        "listbox",
        "option",
        "checkbox",
        "radio",
        "switch",
        "slider",
        "spinbutton",
        "tab",
        "menuitem",
        "menuitemcheckbox",
        "menuitemradio",
        "treeitem",
        "dialog",
        "alertdialog",
    }
)

_ARIA_LINE = re.compile(
    r'^\s*-\s+([A-Za-z0-9_-]+)(?:\s+"((?:\\.|[^"\\])*)")?'
)
_ARIA_REF = re.compile(r"\[ref=(e\d+)\]")
_ARIA_BOX = re.compile(
    r"\[box=([-+]?\d+(?:\.\d+)?),([-+]?\d+(?:\.\d+)?),([-+]?\d+(?:\.\d+)?),([-+]?\d+(?:\.\d+)?)\]"
)


def tool_error(message: str, *, code: str = "", hint: str = "") -> dict:
    out = {"status": "error", "message": str(message)}
    if code:
        out["code"] = code
    if hint:
        out["hint"] = hint
    return out


def classify_target_error(message: str) -> dict:
    """Map Playwright/locator failures so the agent can snapshot instead of force-clicking."""
    msg = str(message)
    low = msg.lower()
    if "unknown ref" in low or "expired ref" in low:
        return tool_error(
            msg,
            code="expired_ref",
            hint="Call browser_snapshot again.",
        )
    if any(
        s in low
        for s in (
            "intercepts pointer",
            "outside of the viewport",
            "not visible",
            "not receive pointer",
            "element is not stable",
        )
    ):
        return tool_error(
            msg,
            code="intercepted",
            hint="Covered or off-screen. Hover the menu host, or browser_scroll then snapshot, then click a fresh @n. Do not retry the same click.",
        )
    return tool_error(msg)


def classify_type_error(message: str) -> dict:
    msg = str(message)
    low = msg.lower()
    if "select" in low or "combobox" in low:
        return tool_error(msg, hint="Use browser_select_option for <select>, not type.")
    if "readonly" in low or "disabled" in low:
        return tool_error(msg, hint="Target is not editable. Snapshot again.")
    return classify_target_error(msg)


def _box_in_viewport(box: tuple[float, float, float, float], viewport: dict) -> bool:
    x, y, w, h = box
    if w <= 0 or h <= 0:
        return False
    vw = float(viewport.get("width") or 0)
    vh = float(viewport.get("height") or 0)
    if vw <= 0 or vh <= 0:
        return True
    return y < vh and (y + h) > 0 and x < vw and (x + w) > 0


def parse_aria_snapshot(
    yaml_text: str,
    *,
    start: int = 1,
    viewport: dict | None = None,
) -> list[dict]:
    """Turn Playwright aria_snapshot(mode='ai') YAML into Smoke @n items."""
    items: list[dict] = []
    n = start
    for line in (yaml_text or "").splitlines():
        ref_m = _ARIA_REF.search(line)
        if not ref_m:
            continue
        role_m = _ARIA_LINE.match(line)
        if not role_m:
            continue
        role = role_m.group(1).lower()
        if role not in INTERACTIVE_ARIA_ROLES:
            continue
        if viewport:
            box_m = _ARIA_BOX.search(line)
            if box_m:
                box = tuple(float(v) for v in box_m.groups())
                if not _box_in_viewport(box, viewport):
                    continue
        name = (role_m.group(2) or "").replace('\\"', '"')
        items.append(
            {
                "ref": n,
                "role": role,
                "name": name[:60],
                "aria_ref": ref_m.group(1),
                "sel": f"aria-ref={ref_m.group(1)}",
            }
        )
        n += 1
    return items


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
