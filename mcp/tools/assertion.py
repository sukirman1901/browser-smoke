"""Pure assert shaping. DOM polling stays on BrowserSession.assert_condition."""

from __future__ import annotations

from typing import Any

EXPECTS = frozenset({"text", "url", "visible", "hidden", "count", "input_value"})
NEEDS_SELECTOR = frozenset({"visible", "hidden", "count"})
NEEDS_TEXT = frozenset({"text", "url"})
FAIL_HINT = "Snapshot or screenshot to debug."
BATCH_HALT = frozenset({"error", "assert_fail"})


def normalize_expect(expect: str) -> str:
    return (expect or "").strip().lower()


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def batch_halt(status: str) -> bool:
    return status in BATCH_HALT


def validate_assert(*, expect: str, selector: str, text: str) -> dict | None:
    kind = normalize_expect(expect)
    if kind not in EXPECTS:
        return {
            "status": "error",
            "message": f"unknown expect: {expect}",
            "hint": "use text|url|visible|hidden|count|input_value",
        }
    if kind in NEEDS_SELECTOR and not (selector or "").strip():
        return {
            "status": "error",
            "message": f"selector is required for expect={kind}",
            "hint": "pass CSS or a snapshot @n",
        }
    if kind in NEEDS_TEXT and not (text or "").strip():
        return {
            "status": "error",
            "message": f"text is required for expect={kind}",
            "hint": "pass the substring to find",
        }
    return None


def describe(
    *,
    expect: str,
    selector: str = "",
    text: str = "",
    count: int = 0,
    negate: bool = False,
) -> tuple[str, str]:
    kind = normalize_expect(expect)
    sel = (selector or "").strip()
    where = f" {sel}" if sel else ""
    if kind == "text":
        line = f"text{where} contains {text!r}"
        expected = f"text contains {text!r}"
        if negate:
            return "not " + line, f"text does not contain {text!r}"
        return line, expected
    if kind == "url":
        line = f"url contains {text}"
        if negate:
            return "not " + line, f"url does not contain {text}"
        return line, line
    if kind in ("visible", "hidden"):
        line = f"{kind}{where}".strip()
        if negate:
            return "not " + line, f"not {kind}"
        return line, kind
    if kind == "count":
        line = f"count{where} == {count}"
        expected = f"count == {count}"
        if negate:
            return "not " + line, f"count != {count}"
        return line, expected
    if kind == "input_value":
        line = f"input_value{where} == {text!r}"
        expected = f"input_value == {text!r}"
        if negate:
            return "not " + line, f"input_value != {text!r}"
        return line, expected
    line = kind or "assert"
    return (f"not {line}" if negate else line), line


def evaluate(
    expect: str,
    *,
    observed: Any,
    expected_text: str = "",
    expected_count: int = 0,
    negate: bool = False,
) -> bool:
    kind = normalize_expect(expect)
    if kind in ("text", "url"):
        matched = expected_text in (observed or "")
    elif kind in ("visible", "hidden"):
        matched = bool(observed)
    elif kind == "count":
        try:
            matched = int(observed) == int(expected_count)
        except (TypeError, ValueError):
            matched = False
    elif kind == "input_value":
        matched = ("" if observed is None else str(observed)) == expected_text
    else:
        matched = False
    return (not matched) if negate else matched


def verdict(
    *,
    assert_line: str,
    expected: str,
    actual: str,
    passed: bool,
) -> dict:
    out = {
        "status": "ok" if passed else "assert_fail",
        "assert": assert_line,
        "expected": expected,
        "actual": actual,
    }
    if not passed:
        out["hint"] = FAIL_HINT
    return out


def clip_actual(value: str, n: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"
