---
name: smoke
description: Use when controlling a browser from the agent — daily tasks (open a site, fill a form, scrape), smoke-test after feature work, upload/download/dialogs. Prefer compact tools; never request screenshots unless a visual bug needs evidence.
---

## Token rules (mandatory)

Do **not** return images unless the user asks for a visual check.

1. `browser_open` then **`browser_snapshot`** to see `@1`, `@2`, `@3`. That list is the selector map.
2. Click/type those `@n`. Do not invent CSS if a ref exists.
3. After navigation, a new page, `code=expired_ref`, or if you are unsure which control to use: **snapshot again**. That is verification.
4. Several steps → one `browser_script` (call `snapshot()` inside after nav) or one `browser_run`. Do not chain eight execute/DOM probes.
5. Never `screenshot_base64`. Screenshot only for a visual bug.
6. Scrape: `browser_execute` returning a **small JSON array**. No `innerHTML`. No DOM nodes.

Never skip snapshot when checking that a submit/publish/login worked. `open refs=true` is optional if you already need the map in the same call.

## One living browser (default)

`browser_open url=...` starts or reconnects **Google Chrome** at `~/.browser-smoke/chrome-attach` (port 9222). Same window next chat. Gmail in that profile is reused. Do **not** pass `persist=true` or `cdp=` for the normal path. The result includes `version` — if it disagrees with this skill, tell the user to re-run setup and restart the host.

```
browser_open url=...
browser_snapshot
browser_script js_code="await click('@1'); await type('@2', '...');"
```

`browser_close` leaves the window. `shutdown=true` only to quit.

This is not the user's daily Default Chrome. `persist=false` is Playwright Chromium (the testing window).

## Isolated smoke test

```
browser_open url=http://localhost:5173 persist=false session=test
browser_snapshot
browser_run actions_json=[{"action":"type","selector":"@1","text":"..."},{"action":"click","selector":"@2"}]
browser_console
browser_errors
browser_close shutdown=true session=test
```

Failures block. Debug with console, errors, then snapshot — not a screenshot. Do not `clear_cookies` on the living Chrome-attach profile.

## Scroll (two jobs)

Click/type/hover already scrolls **that** `@n` into view. Do not force-click.

- Control **missing from the snapshot** (below the fold): `browser_scroll` (default down 200px) or `scroll(800)` in a script, then **snapshot again**, then click. Viewport snapshot does not list off-screen controls.
- You already have `@n` (`scope=page`) and only need it on screen: `browser_scroll selector=@n`. Then snapshot if you will click something else nearby.
- `code=intercepted` means covered or still off-screen. Hover the menu host, snapshot, click a **fresh** `@n`. Do not retry the same click.

Menus / popovers: `hover` the host → snapshot → click the item.

`wait` timeout is **milliseconds** (`timeout=4000` is 4 seconds, never seconds).

## Other modes

Named sessions: `session=` on **every** tool. `channel=chrome` is throwaway stock Chrome. `cdp=9222` is debug Chrome the user launched.

## Tools

| Tool | Use |
|------|-----|
| `browser_open` | Living Google Chrome (`chrome-attach`). Then snapshot. `persist=false` = Playwright testing Chromium. Returns `version`. |
| `browser_snapshot` | **How you understand and verify the page.** `@n` for click/type. Default is the viewport. |
| `browser_script` | Default for 2+ steps. `snapshot()` / `click('@n')` / `type` / `wait` / `scroll` / `hover` / `execute` inside. |
| `browser_run` | JSON batch, no loops. |
| `browser_click` / `type` / `paste` / `drag` / `hover` / `press` | `@n` from the last snapshot. Click does not silent-force. |
| `browser_scroll` | Page delta, or `selector=@n` into view. Then snapshot. |
| `browser_select_option` / `browser_set_files` / `browser_download` | `download url=` fetches a file. `set_files` fills hidden file inputs. Type cannot fill `<select>`. |
| `browser_execute` | Tiny JSON only. Not a replacement for snapshot. |
| `browser_close` | Does not quit unless `shutdown=true`. |

## Files

```
browser_snapshot
browser_download url="https://example.com/a.jpg" save_as=hero.jpg
browser_set_files selector=@7 paths="/abs/path/hero.jpg"
```

`iframe "cross-origin"` = cannot click inside. Do not loop. Insert by URL/HTML once, or `set_files` on `file hidden`.

If type/paste fail on an editor: **one** `execute` to set the value, then snapshot to verify.

## Scrape

```
browser_open url="https://example.com"
browser_execute js_code="() => [...document.querySelectorAll('a')].slice(0,50).map(a => ({t:a.textContent.trim(), h:a.href}))"
```
