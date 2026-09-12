"""
Browser Smoke Test MCP Server
FastMCP server for browser-based smoke testing via Playwright.
"""

import json
import os

from fastmcp import FastMCP

from tools.browser import get_session, locked_session, registry
from tools.dom_extractor import classify_inputs, guess_input_value
from tools.payload import clip_logs, compact_classified, compact_network, dumps
from tools.reporter import generate_report

mcp = FastMCP("smoke")

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
    persist: bool = True,
    cdp: str = "",
    refs: bool = False,
    session: str = "",
) -> str:
    """Open/reconnect the living Google Chrome (~/.browser-smoke/chrome-attach). Then browser_snapshot for @refs. persist=false is Playwright Chromium for tests. cdp=9222 attaches if you already launched debug Chrome. Returns version."""
    async with locked_session(session) as sess:
        try:
            await sess.ensure_started(
                headless=headless,
                channel=channel,
                user_data_dir=user_data_dir,
                persist=persist,
                cdp=cdp,
            )
        except Exception as e:
            return dumps({"status": "error", "message": str(e)})
        result = await sess.open(
            url,
            wait_until=wait_until,
            screenshot=screenshot,
            screenshot_base64=screenshot_base64,
            refs=refs,
        )
        return dumps(result)


@mcp.tool()
async def browser_snapshot(scope: str = "viewport", session: str = "") -> str:
    """Compact @refs for the current page. Call this to see what to click, and again to verify after navigation."""
    async with locked_session(session) as sess:
        return dumps(await sess.snapshot(scope))


@mcp.tool()
async def browser_extract_dom(session: str = "") -> str:
    """Compact interactive elements (no bounding boxes). Prefer browser_snapshot when choosing targets."""
    async with locked_session(session) as sess:
        elements = await sess.extract_dom()
        if isinstance(elements, dict) and elements.get("status") == "error":
            return dumps(elements)
        return dumps(compact_classified(classify_inputs(elements)))


@mcp.tool()
async def browser_click(
    selector: str,
    screenshot: bool = False,
    screenshot_base64: bool = False,
    dialog: str = "",
    prompt: str = "",
    popup: bool = False,
    session: str = "",
) -> str:
    """Click CSS or @1. Scrolls the target into view first. Intercepted/covered is an error — snapshot again, do not retry the same click. dialog=accept|dismiss on this click. popup=true waits for window.open."""
    async with locked_session(session) as sess:
        result = await sess.click(
            selector,
            screenshot=screenshot,
            screenshot_base64=screenshot_base64,
            dialog=dialog,
            prompt=prompt,
            popup=popup,
        )
        return dumps(result)


@mcp.tool()
async def browser_type(
    selector: str,
    text: str,
    screenshot: bool = False,
    screenshot_base64: bool = False,
    session: str = "",
) -> str:
    """Type into a CSS selector or snapshot ref like @2."""
    async with locked_session(session) as sess:
        result = await sess.type_text(
            selector, text, screenshot=screenshot, screenshot_base64=screenshot_base64
        )
        return dumps(result)


@mcp.tool()
async def browser_type_guess(
    selector: str,
    input_type: str = "text",
    screenshot: bool = False,
    screenshot_base64: bool = False,
    session: str = "",
) -> str:
    """Fill a guessed test value (email/password/text/...)."""
    async with locked_session(session) as sess:
        value = guess_input_value({"type": input_type})
        result = await sess.type_text(
            selector, value, screenshot=screenshot, screenshot_base64=screenshot_base64
        )
        return dumps(result)


@mcp.tool()
async def browser_screenshot(screenshot_base64: bool = False, session: str = "") -> str:
    """Capture the viewport. Returns a file path by default, not inline PNG."""
    async with locked_session(session) as sess:
        return dumps(await sess.screenshot(screenshot_base64=screenshot_base64))


@mcp.tool()
async def browser_screenshot_diff(
    name: str,
    threshold: float = 0.01,
    screenshot_base64: bool = False,
    session: str = "",
) -> str:
    """Diff against artifacts/baselines/<name>.png. Writes diff PNG to disk; no base64 unless requested."""
    async with locked_session(session) as sess:
        return dumps(
            await sess.screenshot_diff(
                name, threshold, screenshot_base64=screenshot_base64
            )
        )


@mcp.tool()
async def browser_scroll(
    x: int = 0,
    y: int = 200,
    selector: str = "",
    screenshot: bool = False,
    screenshot_base64: bool = False,
    session: str = "",
) -> str:
    """Scroll the page (default down 200px) or selector=@n into view. Then browser_snapshot — viewport @refs change. Click already scrolls its own target."""
    async with locked_session(session) as sess:
        return dumps(
            await sess.scroll(
                x, y, selector=selector, screenshot=screenshot, screenshot_base64=screenshot_base64
            )
        )


@mcp.tool()
async def browser_handle_dialog(action: str = "accept", prompt: str = "", session: str = "") -> str:
    """Set how the *next* JS dialog is handled (one-shot). Prefer browser_click(..., dialog='accept') when the click opens it."""
    async with locked_session(session) as sess:
        return dumps(await sess.handle_dialog(action, prompt))


@mcp.tool()
async def browser_set_files(selector: str = "", paths: str = "", session: str = "") -> str:
    """Set input[type=file], including hidden inputs. paths = comma-separated absolute paths. selector optional if one file input exists."""
    async with locked_session(session) as sess:
        return dumps(await sess.set_files(selector, paths))


@mcp.tool()
async def browser_download(
    selector: str = "",
    url: str = "",
    save_as: str = "",
    timeout: int = 30000,
    session: str = "",
) -> str:
    """Save a file. url= fetches (cookies included). selector= clicks a download link. Writes artifacts/downloads/."""
    async with locked_session(session) as sess:
        if url:
            return dumps(await sess.save_url(url, save_as))
        if not selector:
            return dumps({"status": "error", "message": "provide url= to fetch, or selector= to click a download"})
        return dumps(await sess.click_download(selector, save_as, timeout))


@mcp.tool()
async def browser_select_option(
    selector: str, value: str = "", label: str = "", index: int = -1, session: str = ""
) -> str:
    """Choose a <select> option by value, visible label, or index."""
    async with locked_session(session) as sess:
        return dumps(await sess.select_option(selector, value, label, index))


@mcp.tool()
async def browser_drag(source: str, target: str, session: str = "") -> str:
    """Drag source onto target. CSS or @n."""
    async with locked_session(session) as sess:
        return dumps(await sess.drag(source, target))


@mcp.tool()
async def browser_paste(selector: str, text: str, session: str = "") -> str:
    """Insert text in one chunk (contenteditable / paste-like). Use type to replace an input value."""
    async with locked_session(session) as sess:
        return dumps(await sess.paste(selector, text))


@mcp.tool()
async def browser_press(selector: str, key: str, session: str = "") -> str:
    """Press a key on an element (Enter, Tab, Control+s, ...)."""
    async with locked_session(session) as sess:
        return dumps(await sess.press(selector, key))


@mcp.tool()
async def browser_hover(selector: str, session: str = "") -> str:
    """Hover an element (menus, tooltips). Then snapshot before clicking the revealed item."""
    async with locked_session(session) as sess:
        return dumps(await sess.hover(selector))


@mcp.tool()
async def browser_reload(wait_until: str = "domcontentloaded", session: str = "") -> str:
    """Reload the current page."""
    async with locked_session(session) as sess:
        return dumps(await sess.reload(wait_until))


@mcp.tool()
async def browser_wait(
    state: str = "load",
    selector: str = "",
    url: str = "",
    js: str = "",
    timeout: int = 10000,
    session: str = "",
) -> str:
    """Wait for load/domcontentloaded/networkidle, a selector, a URL glob, or JS waitForFunction (js='() => ...'). timeout is milliseconds."""
    async with locked_session(session) as sess:
        return dumps(await sess.wait(state=state, selector=selector, url=url, js=js, timeout=timeout))


@mcp.tool()
async def browser_run(actions_json: str, screenshot: bool = False, session: str = "") -> str:
    """Run many actions in one call. JSON array of {action, ...}. Stops on first error."""
    async with locked_session(session) as sess:
        actions = json.loads(actions_json) if isinstance(actions_json, str) else actions_json
        if not isinstance(actions, list):
            return dumps({"status": "error", "message": "actions_json must be a JSON array"})
        return dumps(await sess.run_actions(actions, screenshot=screenshot))


@mcp.tool()
async def browser_script(js_code: str, timeout: int = 60000, session: str = "") -> str:
    """Run a JS snippet with open/click/type/snapshot/wait/execute (loops allowed). One MCP round."""
    async with locked_session(session) as sess:
        return dumps(await sess.run_script(js_code, timeout=timeout))


@mcp.tool()
async def browser_highlight(
    selector: str,
    color: str = "red",
    duration: int = 2000,
    screenshot: bool = False,
    screenshot_base64: bool = False,
    session: str = "",
) -> str:
    """Outline an element. Screenshot only if requested."""
    async with locked_session(session) as sess:
        return dumps(
            await sess.highlight(
                selector, color, duration, screenshot=screenshot, screenshot_base64=screenshot_base64
            )
        )


@mcp.tool()
async def browser_report(results_json: str, include_report: bool = False, session: str = "") -> str:
    """Write artifacts/smoke-report.md. Returns the path; set include_report=true to echo markdown."""
    results = json.loads(results_json) if isinstance(results_json, str) else results_json
    async with locked_session(session) as sess:
        url = sess.page.url if sess.page else "unknown"
    report = generate_report(url, results)
    os.makedirs(os.path.dirname(REPORT_FILE) or ".", exist_ok=True)
    with open(REPORT_FILE, "w") as f:
        f.write(report)
    out = {"status": "ok", "report_file": REPORT_FILE}
    if include_report:
        out["report"] = report
    return dumps(out)


@mcp.tool()
async def browser_execute(js_code: str, session: str = "") -> str:
    """Run JavaScript in the page and return JSON. Returned Promises are awaited. Prefer this for scraping."""
    async with locked_session(session) as sess:
        if sess.page is None:
            return dumps({"status": "error", "message": "No page open. Call browser_open first."})
        return dumps(await sess.execute(js_code))


@mcp.tool()
async def browser_offscreen(action: str, url: str = "", js: str = "", session: str = "") -> str:
    """Hidden page for background work. action: open|exec|close."""
    async with locked_session(session) as sess:
        return dumps(await sess.offscreen(action, url, js))


@mcp.tool()
async def browser_open_tab(url: str, session: str = "") -> str:
    """Open a new tab and focus it."""
    async with locked_session(session) as sess:
        if sess.context is None:
            try:
                await sess.ensure_started()
            except (ValueError, RuntimeError) as e:
                return dumps({"status": "error", "message": str(e)})
        return dumps(await sess.open_tab(url))


@mcp.tool()
async def browser_get_tabs(session: str = "") -> str:
    """List open tabs (title, URL, active)."""
    async with locked_session(session) as sess:
        tabs = await sess.get_tabs()
        return dumps({"tabs": tabs, "active_tab": next((t for t in tabs if t["active"]), None)})


@mcp.tool()
async def browser_switch_tab(index: int, session: str = "") -> str:
    """Focus an open tab by index from browser_get_tabs."""
    async with locked_session(session) as sess:
        return dumps(await sess.switch_tab(index))


@mcp.tool()
async def browser_console(session: str = "") -> str:
    """Recent console logs (capped, text truncated)."""
    async with locked_session(session) as sess:
        logs = clip_logs(sess.get_console())
        return dumps({"entries": logs, "count": len(logs)})


@mcp.tool()
async def browser_errors(session: str = "") -> str:
    """Recent pageerror events (capped)."""
    async with locked_session(session) as sess:
        errors = clip_logs(
            [{"text": e.get("message", ""), "url": e.get("url", "")} for e in sess.get_errors()]
        )
        return dumps({"entries": errors, "count": len(errors)})


@mcp.tool()
async def browser_network_capture(
    mode: str, patterns: str = "", headers: bool = False, session: str = ""
) -> str:
    """Capture requests. mode: start|stop|get. get omits headers unless headers=true."""
    async with locked_session(session) as sess:
        if mode == "start":
            pattern_list = [p.strip() for p in patterns.split(",") if p.strip()] if patterns else None
            return dumps(await sess.start_network_capture(pattern_list))
        if mode == "stop":
            return dumps(await sess.stop_network_capture())
        if mode == "get":
            entries = compact_network(sess.get_network_logs(), headers=headers)
            return dumps({"entries": entries, "count": len(entries)})
        return dumps({"status": "error", "message": f"unknown mode: {mode}"})


@mcp.tool()
async def browser_block_resources(patterns: str, session: str = "") -> str:
    """Block resources by comma-separated globs. Empty string unblocks."""
    async with locked_session(session) as sess:
        pattern_list = [p.strip() for p in patterns.split(",") if p.strip()]
        return dumps(await sess.block_resources(pattern_list))


@mcp.tool()
async def browser_inject_script(script: str, url_pattern: str = "*", session: str = "") -> str:
    """addInitScript before future navigations."""
    async with locked_session(session) as sess:
        return dumps(await sess.inject_script(script, url_pattern))


@mcp.tool()
async def browser_get_cookies(include_values: bool = False, session: str = "") -> str:
    """Cookie names/domains only unless include_values=true."""
    async with locked_session(session) as sess:
        return dumps(await sess.get_cookies(include_values=include_values))


@mcp.tool()
async def browser_set_cookie(
    name: str, value: str, domain: str = "", path: str = "/", session: str = ""
) -> str:
    """Set a cookie. Domain optional if a page is already open."""
    async with locked_session(session) as sess:
        return dumps(await sess.set_cookie(name, value, domain, path))


@mcp.tool()
async def browser_clear_cookies(session: str = "") -> str:
    """Clear all cookies in this session's context. Do not use on the living Chrome-attach profile — smoke tests should persist=false."""
    async with locked_session(session) as sess:
        return dumps(await sess.clear_cookies())


@mcp.tool()
async def browser_storage(
    mode: str, storage: str = "local", key: str = "", value: str = "", session: str = ""
) -> str:
    """localStorage/sessionStorage. mode: all|get|set|clear. storage: local|session."""
    async with locked_session(session) as sess:
        return dumps(await sess.storage(mode, storage, key, value))


@mcp.tool()
async def browser_session(action: str = "current", name: str = "", shutdown: bool = False) -> str:
    """Named sessions. action: current|use|list|close. close+shutdown=true kills persisted Chromium."""
    from tools.persist import cdp_alive, read_state, safe_session_name, state_dir

    if action == "use":
        sess = await get_session(name)
        return dumps({"status": "ok", "current": registry.current, "open": sess.page is not None})
    if action == "list":
        rows = []
        seen = set()
        for n in registry.names():
            seen.add(n)
            sess = registry.get(n, switch=False)
            state = read_state(n)
            port = int(state.get("port") or 0)
            rows.append({
                "name": n,
                "current": n == registry.current,
                "open": sess.page is not None,
                "persist": bool(sess.persist or port),
                "attached": sess.attached,
                "mode": sess.mode,
                "cdp": cdp_alive(port) if port else False,
            })
        if os.path.isdir(state_dir()):
            for fn in os.listdir(state_dir()):
                if not fn.endswith(".json"):
                    continue
                n = safe_session_name(fn[:-5])
                if n in seen:
                    continue
                state = read_state(n)
                port = int(state.get("port") or 0)
                rows.append({
                    "name": n,
                    "current": False,
                    "open": False,
                    "persist": True,
                    "attached": False,
                    "mode": "persist",
                    "cdp": cdp_alive(port) if port else False,
                })
        return dumps({"current": registry.current, "sessions": rows})
    if action == "close":
        async with locked_session(name or registry.current) as sess:
            key = sess.name
            await sess.close(shutdown=shutdown)
        if shutdown:
            registry.drop(key)
        return dumps({"status": "ok", "closed": key, "shutdown": shutdown})
    sess = await get_session()
    return dumps({
        "status": "ok",
        "current": registry.current,
        "open": sess.page is not None,
        "persist": sess.persist,
        "attached": sess.attached,
        "mode": sess.mode,
    })


@mcp.tool()
async def browser_close(shutdown: bool | None = None, session: str = "") -> str:
    """Leave the living window up by default. shutdown=true kills persist Chromium. Attached debug Chrome is never killed."""
    async with locked_session(session) as sess:
        key = sess.name
        if shutdown is None:
            shutdown = not (sess.persist or sess.attached)
        await sess.close(shutdown=shutdown)
    if shutdown:
        registry.drop(key)
    return dumps({"status": "ok", "shutdown": shutdown, "session": key})


if __name__ == "__main__":
    mcp.run()
