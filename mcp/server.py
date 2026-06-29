"""
Browser Smoke Test MCP Server
FastMCP server for browser-based smoke testing via Playwright.
"""

import json
from fastmcp import FastMCP

from tools.browser import get_session
from tools.dom_extractor import classify_inputs, guess_input_value
from tools.reporter import generate_report, make_result

mcp = FastMCP("browser-smoke")

REPORT_FILE = "artifacts/smoke-report.md"


@mcp.tool()
async def browser_open(url: str, headless: bool = False) -> str:
    """Open URL in browser. Returns status, page title, and screenshot."""
    session = await get_session()
    if session.page is None:
        await session.start(headless=headless)
    result = await session.open(url)
    return json.dumps(result, indent=2)


@mcp.tool()
async def browser_extract_dom() -> str:
    """Extract interactive DOM elements (buttons, inputs, links). Returns categorized list."""
    session = await get_session()
    elements = await session.extract_dom()
    classified = classify_inputs(elements)
    return json.dumps(classified, indent=2)


@mcp.tool()
async def browser_click(selector: str) -> str:
    """Click an element by CSS selector. Returns screenshot + status."""
    session = await get_session()
    result = await session.click(selector)
    return json.dumps(result, indent=2)


@mcp.tool()
async def browser_type(selector: str, text: str) -> str:
    """Type text into an input field by CSS selector."""
    session = await get_session()
    result = await session.type_text(selector, text)
    return json.dumps(result, indent=2)


@mcp.tool()
async def browser_type_guess(selector: str, input_type: str = "text") -> str:
    """Type a guessed test value into an input based on its type (text/email/password/etc)."""
    session = await get_session()
    value = guess_input_value({"type": input_type})
    result = await session.type_text(selector, value)
    return json.dumps(result, indent=2)


@mcp.tool()
async def browser_screenshot() -> str:
    """Take a screenshot of current page."""
    session = await get_session()
    result = await session.screenshot()
    return json.dumps(result, indent=2)


@mcp.tool()
async def browser_screenshot_diff(name: str, threshold: float = 0.01) -> str:
    """Take screenshot and diff against baseline. Creates baseline on first run. Returns diff pixel count."""
    session = await get_session()
    result = await session.screenshot_diff(name, threshold)
    return json.dumps(result, indent=2)


@mcp.tool()
async def browser_scroll(x: int = 0, y: int = 200) -> str:
    """Scroll page by x, y pixels. Default scroll down 200px."""
    session = await get_session()
    result = await session.scroll(x, y)
    return json.dumps(result, indent=2)


@mcp.tool()
async def browser_highlight(selector: str, color: str = "red", duration: int = 2000) -> str:
    """Highlight an element with a colored outline for visual debugging."""
    session = await get_session()
    result = await session.highlight(selector, color, duration)
    return json.dumps(result, indent=2)


@mcp.tool()
async def browser_report(results_json: str) -> str:
    """Generate smoke test report from results JSON array. Returns markdown."""
    results = json.loads(results_json) if isinstance(results_json, str) else results_json
    session = await get_session()
    url = session.page.url if session.page else "unknown"
    report = generate_report(url, results)
    import os
    os.makedirs(os.path.dirname(REPORT_FILE) or ".", exist_ok=True)
    with open(REPORT_FILE, "w") as f:
        f.write(report)
    return json.dumps({"status": "ok", "report_file": REPORT_FILE, "report": report}, indent=2)


@mcp.tool()
async def browser_execute(js_code: str) -> str:
    """Execute JavaScript in the current page context. Returns result as string."""
    session = await get_session()
    if session.page is None:
        return json.dumps({"status": "error", "message": "No page open. Call browser_open first."})
    result = await session.execute(js_code)
    return json.dumps(result, indent=2)


@mcp.tool()
async def browser_offscreen(action: str, url: str = "", js: str = "") -> str:
    """Manage offscreen/hidden page for background processing. action: open|exec|close."""
    session = await get_session()
    result = await session.offscreen(action, url, js)
    return json.dumps(result, indent=2)


@mcp.tool()
async def browser_open_tab(url: str) -> str:
    """Open a new tab with the given URL. Switches focus to the new tab."""
    session = await get_session()
    if session.context is None:
        await session.start()
    result = await session.open_tab(url)
    return json.dumps(result, indent=2)


@mcp.tool()
async def browser_get_tabs() -> str:
    """List all open tabs with title, URL, and active status."""
    session = await get_session()
    tabs = await session.get_tabs()
    return json.dumps({"tabs": tabs, "active_tab": next((t for t in tabs if t["active"]), None)}, indent=2)


@mcp.tool()
async def browser_console() -> str:
    """Get captured console log entries from the current session."""
    session = await get_session()
    logs = session.get_console()
    return json.dumps({"entries": logs, "count": len(logs)}, indent=2)


@mcp.tool()
async def browser_errors() -> str:
    """Get captured page JS errors from the current session."""
    session = await get_session()
    errors = session.get_errors()
    return json.dumps({"entries": errors, "count": len(errors)}, indent=2)


@mcp.tool()
async def browser_network_capture(mode: str, patterns: str = "") -> str:
    """Capture network requests/responses. mode: start|stop|get. patterns: optional comma-separated URL patterns."""
    session = await get_session()
    if mode == "start":
        pattern_list = [p.strip() for p in patterns.split(",") if p.strip()] if patterns else None
        result = await session.start_network_capture(pattern_list)
    elif mode == "stop":
        result = await session.stop_network_capture()
    elif mode == "get":
        return json.dumps({"entries": session.get_network_logs(), "count": len(session.get_network_logs())}, indent=2)
    else:
        return json.dumps({"status": "error", "message": f"unknown mode: {mode}"})
    return json.dumps(result, indent=2)


@mcp.tool()
async def browser_block_resources(patterns: str) -> str:
    """Block resources matching comma-separated glob patterns. Empty string to unblock all."""
    session = await get_session()
    pattern_list = [p.strip() for p in patterns.split(",") if p.strip()]
    result = await session.block_resources(pattern_list)
    return json.dumps(result, indent=2)


@mcp.tool()
async def browser_inject_script(script: str, url_pattern: str = "*") -> str:
    """Inject JavaScript to run before page load (addInitScript). Useful for mocking APIs, injecting test helpers."""
    session = await get_session()
    result = await session.inject_script(script, url_pattern)
    return json.dumps(result, indent=2)


@mcp.tool()
async def browser_get_cookies() -> str:
    """Get all cookies for the current browser context."""
    session = await get_session()
    result = await session.get_cookies()
    return json.dumps(result, indent=2)


@mcp.tool()
async def browser_set_cookie(name: str, value: str, domain: str = "", path: str = "/") -> str:
    """Set a cookie in the current browser context."""
    session = await get_session()
    result = await session.set_cookie(name, value, domain, path)
    return json.dumps(result, indent=2)


@mcp.tool()
async def browser_clear_cookies() -> str:
    """Clear all cookies."""
    session = await get_session()
    result = await session.clear_cookies()
    return json.dumps(result, indent=2)


@mcp.tool()
async def browser_storage(mode: str, storage: str = "local", key: str = "", value: str = "") -> str:
    """Access localStorage/sessionStorage. mode: all|get|set|clear. storage: local|session."""
    session = await get_session()
    result = await session.storage(mode, storage, key, value)
    return json.dumps(result, indent=2)


@mcp.tool()
async def browser_close() -> str:
    """Close the browser session."""
    session = await get_session()
    await session.close()
    return json.dumps({"status": "ok"})


if __name__ == "__main__":
    mcp.run()
