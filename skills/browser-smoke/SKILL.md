---
name: browser-smoke
description: Use when testing UI after feature work, before commit/PR, scraping a page, or filling a form that needs upload/download/dialogs. Prefer compact tools; never request screenshots unless a visual bug needs evidence.
---

## Token rules (mandatory)

Do **not** return images unless the user asks for a visual check.

1. `browser_open` then `browser_snapshot` (or `browser_execute` for scrape).
2. Click/type with `@n` from the last snapshot. After navigation, snapshot again — stale `@n` errors.
3. Multi-step: one `browser_run`, not a chain of MCP tools.
4. Screenshot only for visual bugs. Never `screenshot_base64`.
5. Scrape: `browser_execute` returning a small JSON array. No `innerHTML`.

## Core loop

```
browser_open url=...
browser_snapshot
browser_run actions_json=[{"action":"type","selector":"@1","text":"..."},{"action":"click","selector":"@2"}]
browser_console
browser_errors
browser_report results_json=...
browser_close
```

Failures block. Debug with console, errors, network_capture `mode=get` (no headers), then `browser_execute`. Screenshot last.

Logged-in smoke (Playwright profile, not Chrome's daily profile):

`browser_open url=... user_data_dir=".browser-smoke/profile"`

## Tools

| Tool | Use |
|------|-----|
| `browser_open(url, headless?, user_data_dir?, channel?)` | Navigate. Persistent profile optional. |
| `browser_snapshot(scope?)` | `@ref` list, same-origin iframes tagged `iframe`. |
| `browser_run(actions_json)` | Batch including press, select, upload, download, dialog, reload. |
| `browser_click` / `type` / `type_guess` / `hover` / `press` | Selector or `@n`. |
| `browser_select_option` / `browser_set_files` / `browser_download` | Forms and files. |
| `browser_handle_dialog(action, prompt?)` | Call **before** the click that opens alert/confirm/prompt. |
| `browser_wait` / `browser_reload` / `browser_scroll` | Timing and motion. |
| `browser_execute` | Scrape / inspect JSON. |
| `browser_screenshot` / `screenshot_diff` / `highlight` | Visual, on demand. |
| `browser_console` / `errors` / `network_capture` / cookies / storage | Evidence. |
| `browser_report` / `close` / tabs / offscreen | Wrap-up. |

## Files and dialogs

```
browser_handle_dialog action=accept
browser_click selector=@4
browser_set_files selector=@7 paths="/abs/path/cv.pdf"
browser_download selector=@8
```

## Scrape

```
browser_open url="https://example.com"
browser_execute js_code="() => [...document.querySelectorAll('a')].slice(0,50).map(a => ({t:a.textContent.trim(), h:a.href}))"
browser_close
```
