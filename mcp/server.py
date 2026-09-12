"""
Browser Smoke Test MCP Server
FastMCP server for browser-based smoke testing via Playwright.
"""

import json
import os

from fastmcp import FastMCP

from tools.browser import get_session
from tools.dom_extractor import classify_inputs, guess_input_value
from tools.payload import clip_logs, compact_classified, compact_network, dumps
from tools.reporter import generate_report

mcp = FastMCP("browser-smoke")

REPORT_FILE = "artifacts/smoke-report.md"


@mcp.tool()
async def browser_open(
    url: str,
    headless: bool = False,
    screenshot: bool = False,
    screenshot_base64: bool = False,
    wait_until: str = "domcontentloaded",
    channel: str = "",
    user_data_dir: str = "",
) -> str:
    """Open a URL. user_data_dir enables a persistent Playwright profile (cookies survive close)."""
    session = await get_session()
    await session.ensure_started(
        headless=headless, channel=channel, user_data_dir=user_data_dir
    )
    result = await session.open(
        url,
        wait_until=wait_until,
        screenshot=screenshot,
        screenshot_base64=screenshot_base64,
    )
    return dumps(result)


@mcp.tool()
async def browser_snapshot(scope: str = "viewport") -> str:
    """Compact accessibility snapshot with @refs. Prefer this over extract_dom. Click/type with selector='@1'."""
    session = await get_session()
    return dumps(await session.snapshot(scope))


@mcp.tool()
async def browser_extract_dom() -> str:
    """Compact interactive elements (no bounding boxes). Prefer browser_snapshot when choosing targets."""
    session = await get_session()
    elements = await session.extract_dom()
    if isinstance(elements, dict) and elements.get("status") == "error":
        return dumps(elements)
    return dumps(compact_classified(classify_inputs(elements)))


@mcp.tool()
async def browser_click(
    selector: str,
    screenshot: bool = False,
    screenshot_base64: bool = False,
) -> str:
    """Click a CSS selector or snapshot ref like @1. No screenshot unless requested."""
    session = await get_session()
    result = await session.click(selector, screenshot=screenshot, screenshot_base64=screenshot_base64)
    return dumps(result)


@mcp.tool()
async def browser_type(
    selector: str,
    text: str,
    screenshot: bool = False,
    screenshot_base64: bool = False,
) -> str:
    """Type into a CSS selector or snapshot ref like @2."""
    session = await get_session()
    result = await session.type_text(
        selector, text, screenshot=screenshot, screenshot_base64=screenshot_base64
    )
    return dumps(result)


@mcp.tool()
async def browser_type_guess(
    selector: str,
    input_type: str = "text",
    screenshot: bool = False,
    screenshot_base64: bool = False,
) -> str:
    """Fill a guessed test value (email/password/text/...)."""
    session = await get_session()
    value = guess_input_value({"type": input_type})
    result = await session.type_text(
        selector, value, screenshot=screenshot, screenshot_base64=screenshot_base64
    )
    return dumps(result)


@mcp.tool()
async def browser_screenshot(screenshot_base64: bool = False) -> str:
    """Capture the viewport. Returns a file path by default, not inline PNG."""
    session = await get_session()
    return dumps(await session.screenshot(screenshot_base64=screenshot_base64))


@mcp.tool()
async def browser_screenshot_diff(
    name: str,
    threshold: float = 0.01,
    screenshot_base64: bool = False,
) -> str:
    """Diff against artifacts/baselines/<name>.png. Writes diff PNG to disk; no base64 unless requested."""
    session = await get_session()
    return dumps(
        await session.screenshot_diff(
            name, threshold, screenshot_base64=screenshot_base64
        )
    )


@mcp.tool()
async def browser_scroll(
    x: int = 0,
    y: int = 200,
    screenshot: bool = False,
    screenshot_base64: bool = False,
) -> str:
    """Scroll by delta pixels (scrollBy). Default is down 200px."""
    session = await get_session()
    return dumps(await session.scroll(x, y, screenshot=screenshot, screenshot_base64=screenshot_base64))


@mcp.tool()
async def browser_handle_dialog(action: str = "accept", prompt: str = "") -> str:
    """Set how the *next* JS dialog is handled (one-shot, then back to dismiss). Call before the click that opens it."""
    session = await get_session()
    return dumps(await session.handle_dialog(action, prompt))


@mcp.tool()
async def browser_set_files(selector: str, paths: str) -> str:
    """Set input[type=file]. paths is a comma-separated list of absolute file paths."""
    session = await get_session()
    return dumps(await session.set_files(selector, paths))


@mcp.tool()
async def browser_download(selector: str, save_as: str = "", timeout: int = 30000) -> str:
    """Click a download trigger and save the file under artifacts/downloads/."""
    session = await get_session()
    return dumps(await session.click_download(selector, save_as, timeout))


@mcp.tool()
async def browser_select_option(
    selector: str, value: str = "", label: str = "", index: int = -1
) -> str:
    """Choose a <select> option by value, visible label, or index."""
    session = await get_session()
    return dumps(await session.select_option(selector, value, label, index))


@mcp.tool()
async def browser_press(selector: str, key: str) -> str:
    """Press a key on an element (Enter, Tab, Control+s, ...)."""
    session = await get_session()
    return dumps(await session.press(selector, key))


@mcp.tool()
async def browser_hover(selector: str) -> str:
    """Hover an element (menus, tooltips)."""
    session = await get_session()
    return dumps(await session.hover(selector))


@mcp.tool()
async def browser_reload(wait_until: str = "domcontentloaded") -> str:
    """Reload the current page."""
    session = await get_session()
    return dumps(await session.reload(wait_until))


@mcp.tool()
async def browser_wait(
    state: str = "load",
    selector: str = "",
    url: str = "",
    timeout: int = 10000,
) -> str:
    """Wait for load/domcontentloaded/networkidle, a selector (visible/hidden), or a URL glob."""
    session = await get_session()
    return dumps(await session.wait(state=state, selector=selector, url=url, timeout=timeout))


@mcp.tool()
async def browser_run(actions_json: str, screenshot: bool = False) -> str:
    """Run many actions in one call. JSON array of {action, ...}. Stops on first error."""
    session = await get_session()
    actions = json.loads(actions_json) if isinstance(actions_json, str) else actions_json
    if not isinstance(actions, list):
        return dumps({"status": "error", "message": "actions_json must be a JSON array"})
    return dumps(await session.run_actions(actions, screenshot=screenshot))


@mcp.tool()
async def browser_highlight(
    selector: str,
    color: str = "red",
    duration: int = 2000,
    screenshot: bool = False,
    screenshot_base64: bool = False,
) -> str:
    """Outline an element. Screenshot only if requested."""
    session = await get_session()
    return dumps(
        await session.highlight(
            selector, color, duration, screenshot=screenshot, screenshot_base64=screenshot_base64
        )
    )


@mcp.tool()
async def browser_report(results_json: str, include_report: bool = False) -> str:
    """Write artifacts/smoke-report.md. Returns the path; set include_report=true to echo markdown."""
    results = json.loads(results_json) if isinstance(results_json, str) else results_json
    session = await get_session()
    url = session.page.url if session.page else "unknown"
    report = generate_report(url, results)
    os.makedirs(os.path.dirname(REPORT_FILE) or ".", exist_ok=True)
    with open(REPORT_FILE, "w") as f:
        f.write(report)
    out = {"status": "ok", "report_file": REPORT_FILE}
    if include_report:
        out["report"] = report
    return dumps(out)


@mcp.tool()
async def browser_execute(js_code: str) -> str:
    """Run JavaScript in the page and return a JSON result. Prefer this for scraping."""
    session = await get_session()
    if session.page is None:
        return dumps({"status": "error", "message": "No page open. Call browser_open first."})
    return dumps(await session.execute(js_code))


@mcp.tool()
async def browser_offscreen(action: str, url: str = "", js: str = "") -> str:
    """Hidden page for background work. action: open|exec|close."""
    session = await get_session()
    return dumps(await session.offscreen(action, url, js))


@mcp.tool()
async def browser_open_tab(url: str) -> str:
    """Open a new tab and focus it."""
    session = await get_session()
    if session.context is None:
        await session.start()
    return dumps(await session.open_tab(url))


@mcp.tool()
async def browser_get_tabs() -> str:
    """List open tabs (title, URL, active)."""
    session = await get_session()
    tabs = await session.get_tabs()
    return dumps({"tabs": tabs, "active_tab": next((t for t in tabs if t["active"]), None)})


@mcp.tool()
async def browser_console() -> str:
    """Recent console logs (capped, text truncated)."""
    session = await get_session()
    logs = clip_logs(session.get_console())
    return dumps({"entries": logs, "count": len(logs)})


@mcp.tool()
async def browser_errors() -> str:
    """Recent pageerror events (capped)."""
    session = await get_session()
    errors = clip_logs(
        [{"text": e.get("message", ""), "url": e.get("url", "")} for e in session.get_errors()]
    )
    return dumps({"entries": errors, "count": len(errors)})


@mcp.tool()
async def browser_network_capture(mode: str, patterns: str = "", headers: bool = False) -> str:
    """Capture requests. mode: start|stop|get. get omits headers unless headers=true."""
    session = await get_session()
    if mode == "start":
        pattern_list = [p.strip() for p in patterns.split(",") if p.strip()] if patterns else None
        return dumps(await session.start_network_capture(pattern_list))
    if mode == "stop":
        return dumps(await session.stop_network_capture())
    if mode == "get":
        entries = compact_network(session.get_network_logs(), headers=headers)
        return dumps({"entries": entries, "count": len(entries)})
    return dumps({"status": "error", "message": f"unknown mode: {mode}"})


@mcp.tool()
async def browser_block_resources(patterns: str) -> str:
    """Block resources by comma-separated globs. Empty string unblocks."""
    session = await get_session()
    pattern_list = [p.strip() for p in patterns.split(",") if p.strip()]
    return dumps(await session.block_resources(pattern_list))


@mcp.tool()
async def browser_inject_script(script: str, url_pattern: str = "*") -> str:
    """addInitScript before future navigations."""
    session = await get_session()
    return dumps(await session.inject_script(script, url_pattern))


@mcp.tool()
async def browser_get_cookies(include_values: bool = False) -> str:
    """Cookie names/domains only unless include_values=true."""
    session = await get_session()
    return dumps(await session.get_cookies(include_values=include_values))


@mcp.tool()
async def browser_set_cookie(name: str, value: str, domain: str = "", path: str = "/") -> str:
    """Set a cookie. Domain optional if a page is already open."""
    session = await get_session()
    return dumps(await session.set_cookie(name, value, domain, path))


@mcp.tool()
async def browser_clear_cookies() -> str:
    """Clear all cookies in the current context."""
    session = await get_session()
    return dumps(await session.clear_cookies())


@mcp.tool()
async def browser_storage(mode: str, storage: str = "local", key: str = "", value: str = "") -> str:
    """localStorage/sessionStorage. mode: all|get|set|clear. storage: local|session."""
    session = await get_session()
    return dumps(await session.storage(mode, storage, key, value))


@mcp.tool()
async def browser_close() -> str:
    """Close the browser session."""
    session = await get_session()
    await session.close()
    return dumps({"status": "ok"})


if __name__ == "__main__":
    mcp.run()
