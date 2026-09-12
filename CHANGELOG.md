# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
