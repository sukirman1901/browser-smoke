---
name: smoke
description: Use when controlling a browser from the agent — daily tasks (open a site, fill a form, scrape), smoke-test after feature work, upload/download/dialogs. Prefer compact tools; never request screenshots unless a visual bug needs evidence.
---

## Token rules (mandatory)

Do **not** return images unless the user asks for a visual check.

1. `browser_open` then `browser_snapshot` (or `browser_execute` for scrape).
2. Click/type with `@n` from the last snapshot. After navigation, snapshot again — stale `@n` errors.
3. Multi-step: `browser_script` (loops) or one `browser_run`, not a chain of MCP tools.
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

Daily task (window stays up):

```
browser_open url=... persist=true session=work
browser_script js_code="await snapshot(); await click('@1'); log(await execute('() => document.title'))"
```

`browser_close shutdown=false` leaves Chromium running. Next chat: `browser_open persist=true session=work` reconnects.

Two named sessions: pass `session=` on **every** tool (`snapshot`, `click`, `script`, `close`), not only `open`. `persist=true` cannot be combined with `channel` or `cdp`.

Logged-in Playwright profile (not Chrome's daily profile):

`browser_open url=... user_data_dir=".browser-smoke/profile"`

Attach to a debug Chrome (not daily Gmail; Chrome 136+ ignores remote debugging on the default profile):

Launch Chrome with `--remote-debugging-port=9222` and `--user-data-dir=$HOME/.browser-smoke/chrome-attach`, then `browser_open url=... cdp=9222`. Close disconnects; it does not quit that Chrome.

## Tools

| Tool | Use |
|------|-----|
| `browser_open(url, persist?, session?, user_data_dir?, cdp?)` | `persist=true` keeps our Chromium. `cdp=9222` attaches to debug Chrome. |
| `browser_session` | `use` / `list` / `close` named sessions. |
| `browser_script(js_code)` | JS snippet with open/click/type/snapshot/wait/execute. Prefer for loops. |
| `browser_run(actions_json)` | JSON batch when you do not need loops. |
| `browser_snapshot(scope?)` | `@ref` list, same-origin iframes tagged `iframe`. |
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
