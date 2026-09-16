# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.5.1] - 2026-09-16

Assert polling honors the timeout you passed.

### Fixed

- `browser_assert` no longer waits a full 1s on `inner_text` / `input_value` when `timeout` is shorter

## [1.5.0] - 2026-09-16

Smoke tests get a real pass/fail. Snapshot stays the `@n` map.

### Added

- `browser_assert` (`expect=text|url|visible|hidden|count|input_value`) returns `ok` or `assert_fail`, with `expected` / `actual`
- Matching `assert` action in `browser_run` and `assert({...})` in `browser_script`
- `browser_run` / `browser_script` stop on `assert_fail` (same as the first error)

### Notes

- `wait` is still “block until ready”. `assert` is the verdict.
- Hidden (or a gone `@n`) is a pass for `expect=hidden`, not an expired-ref error. Unknown `@n` (never snapshotted) is still an error.
- `browser_report` still requires `results_json`. No transcript file.

## [1.4.3] - 2026-09-12

Snapshot is the accessibility tree (Playwright `aria_snapshot` AI mode), not a CSS tag list. `@n` is unchanged.

### Changed

- `browser_snapshot` uses semantic roles and names from the a11y tree; clicks resolve `aria-ref`
- Viewport snapshots drop off-screen controls via snapshot boxes
- Hidden file inputs and cross-origin iframes are still appended
- Falls back to the previous DOM selector snapshot if the a11y tree has no refs (old Playwright)

### Notes

This is not natural-language `act()`. The agent still picks `@n`. Canvas, OS pickers, and cross-origin iframes remain out of reach.

## [1.4.2] - 2026-09-12

Agent clicks and `@refs` are honest. Scroll has two jobs: the target, or the page.

### Changed

- Click/type/hover scroll the target into view, then act. No silent `force` retry when Playwright says intercepted or off-screen
- Those failures return `code=intercepted` or `code=expired_ref` with a snapshot hint
- Snapshot includes `contenteditable` and roles `dialog`, `combobox`, `listbox`, `switch`, `treeitem`, `slider`
- `browser_open` returns `version`
- `wait` timeout is documented as milliseconds

### Added

- `browser_scroll selector=@n` brings a known ref into view without clicking
- Script `scroll(800)` is down 800px; `scroll('@3')` is into-view
- After a page scroll, the result tells the agent to snapshot again

### Notes

Viewport snapshot still does not list below-the-fold controls. Scroll the page, snapshot, then click.

## [1.4.1] - 2026-09-12

Daily persist is Google Chrome at `~/.browser-smoke/chrome-attach` (port 9222), auto-started. Playwright Chromium is `persist=false` only.

### Changed

- Default `browser_open` launches or reconnects real Chrome (not Chrome for Testing)
- Default profile is `$HOME/.browser-smoke/chrome-attach` so an existing Gmail login there is reused
- If port 9222 already has CDP, attach — no second window
- Fallback to bundled Chromium only when Google Chrome is not installed

## [1.4.0] - 2026-09-12

Living Chromium is the default. Isolated test Chromium is opt-in.

### Changed

- `browser_open` defaults to `persist=true` (one window that survives MCP restart)
- `browser_close` with no `shutdown` leaves that window up; `shutdown=true` kills it
- `cdp=` and `channel=` still work without passing `persist=false` (attach/channel win)
- Smoke tests must pass `persist=false` or they reuse the living profile
- `browser_snapshot` is how the agent reads and verifies `@n`. Open does not include a snapshot unless `refs=true`
- Snapshot is capped at 80 lines; huge pages set `truncated`

### Added

- Snapshot includes `[role=menuitem]` and hidden `input[type=file]` (tagged `hidden`)
- Cross-origin iframes (Google picker) show as `@n iframe "cross-origin"` instead of going missing
- Click prefers the visible match; retries `force` once if Playwright says not visible / intercepted
- `browser_set_files` fills hidden file inputs and searches same-origin frames
- `browser_download url=...` fetches a file (browser cookies) to `artifacts/downloads/`

### Notes

This is not your daily Chrome and not Chrome debug. It is Smoke's own Chromium under `.browser-smoke/profiles/<session>`.

## [1.3.4] - 2026-09-12

Attach to a Chrome you launched with remote debugging.

### Added

- `browser_open(..., cdp=9222)` (or `http://127.0.0.1:9222` / `ws://…`) connects over CDP
- `browser_close` on an attached session disconnects Playwright only — it never quits that Chrome
- `cdp` cannot be combined with `persist` or `channel`

### Notes

- Chrome 136+ ignores `--remote-debugging-port` on the daily/default profile. Launch a **separate** Chrome with a non-default `--user-data-dir`. Log in there. That is not Gmail already open in your normal Chrome.

## [1.3.3] - 2026-09-12

Docs and CLI match the MCP id `smoke`. Install from GitHub (`npx github:sukirman1901/browser-smoke`); do not use `npx smoke` (different npm package). Bin alias `smoke`. OpenCode examples use `smoke_browser_*`.

## [1.3.2] - 2026-09-12

Rewrite README as a usage guide: quick start, first task, daily/smoke/scrape recipes, and an honest “what this is not” table. No runtime changes.

## [1.3.1] - 2026-09-12

Session isolation, persist CDP, and `browser_script` reliability.

### Fixed

- Every mutating/read tool accepts `session=` and takes that session's lock (not only open/run/script/close)
- `browser_script` `wait("load")` no longer crashes Python (string RPC params are coerced)
- Persist writes CDP state only after connect; spawn stderr goes to a log; shutdown kills the process group
- `persist=true` + `channel=chrome` returns an error instead of silently ignoring channel
- Persist reconnect sets viewport 1280×720; a new CDP context enables downloads
- `init` always refreshes pip + Chromium; Windows uses `Scripts/python.exe`
- Script host helpers: dialog, download, upload, select, switchTab; Node is not killed after a successful `done`

### Changed

- Pass `session=` on every tool when more than one named session is in use

## [1.3.0] - 2026-09-12

Named sessions, persistent Chromium, and a JS snippet runner. Not Chrome profile migration or Task Spaces.

### Added

- `browser_session` (`current` / `use` / `list` / `close`) — named sessions so two tasks do not share one tab
- `browser_open(..., persist=true, session=work)` — detached Chromium on CDP; survives MCP restart
- `browser_close(shutdown=false)` — disconnect without killing a persisted window
- `browser_script(js_code)` — one round trip with `open` / `click` / `type` / `snapshot` / `wait` / `execute` and real JS loops

### Notes

- Persist uses bundled Chromium + `.browser-smoke/profiles/<session>`, not your daily Chrome profile
- Re-run `npx browser-smoke init` so `script-host.mjs` is copied

## [1.2.3] - 2026-09-12

MCP server id is `smoke` so OpenCode tools show as `smoke_browser_open`, not `browser-smoke_browser_open`. Package/repo stay `browser-smoke`. `init` removes the old `browser-smoke` MCP key.

## [1.2.2] - 2026-09-12

Dialog/popup waitForEvent, plus drag, paste, and waitForFunction.

### Added

- `browser_click(..., dialog=accept|dismiss, popup=true)` — JS dialog and `window.open` in the same click
- `browser_switch_tab(index)` after a popup
- `browser_drag(source, target)` and `browser_paste(selector, text)` (`insertText`, good for contenteditable)
- `browser_wait(js=...)` — Playwright `waitForFunction`
- Matching `browser_run` actions: `click` with `dialog`/`popup`, `drag`, `paste`, `wait` with `js`, `switch_tab`

### Changed

- Prefer `browser_click(dialog="accept")` over a separate `browser_handle_dialog` call. The old two-step still works.

## [1.2.1] - 2026-09-12

P0 reliability: capture/block no longer fight each other; refs, dialogs, and empty sessions fail as JSON.

### Fixed

- Network capture uses response events instead of `route()`, so it no longer uninstalls `block_resources`
- `inject_script` honors `url_pattern` (glob against href/host)
- Dialog accept/dismiss is one-shot; stale dialog is not replayed on the next click
- `@n` that no longer exists returns `Expired ref` instead of clicking the wrong node
- Tools return JSON when no page is open instead of crashing
- `screenshot_diff` / download names cannot escape `artifacts/`
- `browser_report` no longer KeyErrors when `step` is missing
- Page console/dialog listeners are not registered twice; in-memory logs are capped

## [1.2.0] - 2026-09-12

Remaining P1 host install + P2 smoke-test gaps. Still not a daily agent browser.

### Added

- `init --cursor`, `--claude`, `--opencode`, `--all` (and an interactive host prompt)
- Same-origin iframe coverage in `browser_snapshot`; refs tagged `iframe` still click via `@n`
- Persistent Playwright profile via `browser_open(..., user_data_dir=...)`
- `browser_handle_dialog` (call before the click that opens alert/confirm/prompt)
- `browser_set_files` for `input[type=file]`
- `browser_download` (click + save under `artifacts/downloads/`)
- `browser_select_option`, `browser_press`, `browser_hover`, `browser_reload`
- Matching `browser_run` actions: `press`, `hover`, `select`, `upload`/`set_files`, `download`, `dialog`, `reload`

### Changed

- Dialogs default to dismiss so the session does not hang on `alert()`
- Browser context accepts downloads
- Skill and README cover Cursor/Claude install, persistent profile, files, and dialogs

## [1.1.0] - 2026-09-12

Token-first MCP results and P0 correctness. **Breaking** for agents that expected a PNG on every click.

### Added

- `browser_snapshot` with compact `@ref` lines; click/type accept `@1`
- `browser_run` to batch many actions in one MCP call
- `browser_wait` for load state, selector visibility, or URL
- Screenshots write to `artifacts/shots/` and return a path; `screenshot_base64` is opt-in
- Payload cap (~24k chars) with a truncated preview instead of blowing the context window
- Compact JSON (`separators`), capped console/network logs, cookie values omitted unless `include_values`
- `browser_report` returns the file path; markdown echoed only if `include_report=true`
- MIT `LICENSE`
- Unit tests and GitHub Actions CI
- `init` always syncs MCP server files so upgrades actually land

### Changed

- `open` / `click` / `type` / `scroll` / `highlight` no longer attach screenshots by default
- Launch bundled Playwright Chromium (optional `channel="chrome"`)
- `browser_scroll` uses `window.scrollBy` (delta), not `scrollTo`
- Default navigation wait is `domcontentloaded`
- Python requirement documented as 3.10+ (matches the installer)
- Skill rewritten around the cheap loop: snapshot → run → console/errors

### Fixed

- Visual diff no longer crashes when screenshot size differs from the baseline
- Empty cookie `domain` falls back to the current page URL

## [1.0.4] - 2026-06-29

Initial public release: 24 Playwright MCP tools, OpenCode installer, smoke-test skill.
