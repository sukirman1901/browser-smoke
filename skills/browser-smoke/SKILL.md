---
name: browser-smoke
description: Use when controlling a browser from the agent — daily tasks (open a site, fill a form, scrape), smoke-test after feature work, upload/download/dialogs. Prefer compact tools; never request screenshots unless a visual bug needs evidence.
---

## Token rules (mandatory)

Do **not** return images unless the user asks for a visual check.

1. `browser_open` then `browser_snapshot` (or `browser_execute` for scrape).
2. Click/type with `@n` from the last snapshot. After navigation, snapshot again — stale `@n` errors.
3. Multi-step: one `browser_run`, not a chain of MCP tools.
4. Screenshot only for visual bugs. Never `screenshot_base64`.
5. Scrape: `browser_execute` returning a small JSON array. No `innerHTML`.

## Core loop

Daily task or smoke — same tools:

```
browser_open url=...
browser_snapshot
browser_run actions_json=[{"action":"type","selector":"@1","text":"..."},{"action":"click","selector":"@2"}]
```

Smoke extras (optional): `browser_console`, `browser_errors`, `browser_report`, then `browser_close`.

Failures block. Debug with console, errors, network_capture `mode=get` (no headers), then `browser_execute`. Screenshot last.

Logged-in session (Playwright profile, not Chrome's daily profile):

`browser_open url=... user_data_dir=".browser-smoke/profile"`

## Tools

| Tool | Use |
|------|-----|
| `browser_open(url, headless?, user_data_dir?, channel?)` | Navigate. Persistent profile optional. |
| `browser_snapshot(scope?)` | `@ref` list, same-origin iframes tagged `iframe`. |
| `browser_run(actions_json)` | Batch including click+dialog/popup, drag, paste, wait js, switch_tab. |
| `browser_click` / `type` / `paste` / `drag` / `hover` / `press` | Selector or `@n`. `click` accepts `dialog` and `popup`. |
| `browser_select_option` / `browser_set_files` / `browser_download` | Forms and files. |
| `browser_handle_dialog(action, prompt?)` | Only if the trigger is not a click. Prefer `click(..., dialog=accept)`. |
| `browser_wait` / `browser_reload` / `browser_scroll` | URL, selector, load, or `js` waitForFunction. |
| `browser_execute` | Scrape / inspect JSON. |
| `browser_screenshot` / `screenshot_diff` / `highlight` | Visual, on demand. |
| `browser_console` / `errors` / `network_capture` / cookies / storage | Evidence. |
| `browser_report` / `close` / tabs / offscreen | Wrap-up. |

## Files, dialogs, popups

```
browser_click selector=@4 dialog=accept
browser_click selector=@5 popup=true
browser_switch_tab index=0
browser_set_files selector=@7 paths="/abs/path/cv.pdf"
browser_download selector=@8
```

## Scrape

```
browser_open url="https://example.com"
browser_execute js_code="() => [...document.querySelectorAll('a')].slice(0,50).map(a => ({t:a.textContent.trim(), h:a.href}))"
browser_close
```
