# Smoke

A Playwright browser your coding agent can drive: open a site, fill a form, scrape a page, or smoke-test a UI you just built.

MCP server id is **`smoke`**. In OpenCode the tools are `smoke_browser_open`, `smoke_browser_snapshot`, … Cursor and Claude Code call the same tools without the prefix (`browser_open`).

Results are compact JSON. Screenshots stay off unless you ask. The agent gets **its own living Chromium** (persist by default) — not the Chrome where you read Gmail. See [What this is not](#what-this-is-not).

Works with [OpenCode](https://opencode.ai), [Cursor](https://cursor.com), [Claude Code](https://docs.anthropic.com/en/docs/claude-code), and any MCP client.

Do not run `npx smoke` — that is a different npm package (a mock HTTP server). Install from this GitHub repo:

## Quick start

Need **Node.js 18+** and **Python 3.10+**. Chromium is installed by setup.

### 1. Install

```bash
npx github:sukirman1901/browser-smoke
```

Pick local or global, then which host (OpenCode, Cursor, Claude Code, or all). Setup copies the MCP server, creates a venv, and installs Playwright Chromium. The MCP key it writes is `smoke`.

Restart the host after install (quit/reopen OpenCode, Cursor, or Claude Code).

| Command | What it does |
|---------|----------------|
| `npx github:sukirman1901/browser-smoke` | Interactive |
| `npx github:sukirman1901/browser-smoke -- --local --all` | This project, all three hosts |
| `npx github:sukirman1901/browser-smoke -- --local --cursor` | Cursor only |
| `npx github:sukirman1901/browser-smoke -- --local --claude` | Claude Code only |
| `npx github:sukirman1901/browser-smoke -- --global --opencode` | OpenCode user config |
| `npx github:sukirman1901/browser-smoke -- --print` | Print the stdio MCP entry |

After a version upgrade, run the same command again so MCP files refresh, then restart the host.

### 2. First task

Paste this into the agent:

```
Use smoke: open https://example.com, take a snapshot, tell me the title and the first five links. Do not screenshot.
```

### 3. How the agent should drive it

Same loop for a daily task and a smoke test (OpenCode names):

1. `smoke_browser_open` the URL.
2. `smoke_browser_snapshot` — this is the selector map: `@1`, `@2`, `@3`.
3. Click or type those refs. After navigation, if a ref errors, or to verify a result: snapshot again.
4. Several steps: **one** `smoke_browser_script` (or one `smoke_browser_run`). Do not chain eight MCP execute calls.
5. Scrape with `smoke_browser_execute` returning a small JSON array — not `innerHTML`.
6. Screenshot only for a visual bug. Never `screenshot_base64`.

## Daily task (window stays up)

This is the default. `smoke_browser_open` starts or reconnects **one** Smoke Chromium. Do not pass `persist=true` (it is already on). Do not launch Chrome debug unless you mean `cdp=`.

```
smoke_browser_open url=https://example.com
smoke_browser_snapshot
smoke_browser_script js_code="await click('@1'); await type('@2', 'hi');"
```

Leave the window. Next chat, `smoke_browser_open` the next URL — same window, cookies kept. `smoke_browser_close` disconnects; it does **not** quit Chromium. Pass `shutdown=true` only when you want the window gone.

Named sessions (`session=work`) if two tasks must not share tabs. Then pass `session=` on **every** tool.

Helpers inside `smoke_browser_script`: `open`, `click`, `type`, `snapshot`, `wait`, `execute`, `press`, `hover`, `scroll`, `dialog`, `download`, `upload`, `select`, `switchTab`. `wait("load")` and `wait("#ready")` are fine.

## Smoke test (after you ship a feature)

Throwaway browser — **must** `persist=false` or you pollute the living profile.

```
smoke_browser_open url=http://localhost:5173 persist=false session=test
smoke_browser_snapshot
smoke_browser_run actions_json='[{"action":"type","selector":"@1","text":"test@test.com"},{"action":"click","selector":"@3"}]'
smoke_browser_console
smoke_browser_errors
smoke_browser_report results_json
smoke_browser_close shutdown=true session=test
```

The app must already be running. Failures should block. Debug with console, errors, then `smoke_browser_network_capture` `mode=get` (no headers). Screenshot last.

Visual regression (opt-in):

```
smoke_browser_screenshot_diff name=homepage
```

Writes a baseline/diff under `artifacts/`. No PNG in the tool result unless you ask.

## Scrape

```
smoke_browser_open url=https://example.com
smoke_browser_execute js_code="() => [...document.querySelectorAll('a')].slice(0,50).map(a => ({t:a.textContent.trim(), h:a.href}))"
```

`smoke_browser_close` is optional; it does not quit the living window.

## Keep a login (Playwright profile, not Chrome)

Default persist already keeps cookies in `.browser-smoke/profiles/<session>`. Log in once in that window.

Custom dir:

```
smoke_browser_open url=https://app.example.com user_data_dir=.browser-smoke/profile
```

Cookies live in that folder. Gmail already open in your Chrome will not appear here.

Need stock Chrome instead of bundled Chromium? `channel=chrome` (throwaway, not the living profile). `cdp=` attaches to a debug Chrome you launched.

## Attach to a debug Chrome (`cdp=`)

This drives a Chrome **you** started with remote debugging. It is not the window where you already have Gmail.

Chrome 136+ ignores `--remote-debugging-port` on the daily profile. Use a **separate** user-data-dir. Log in inside that window if you need cookies.

1. Quit daily Chrome if it is using the same binary and you hit a lock (optional on macOS if you only open the debug profile).
2. Start debug Chrome (macOS):

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.browser-smoke/chrome-attach" \
  --no-first-run --no-default-browser-check
```

3. In the agent:

```
smoke_browser_open url=https://example.com cdp=9222
smoke_browser_snapshot
smoke_browser_close
```

`cdp=` also accepts `http://127.0.0.1:9222` or a `ws://` DevTools URL. You do not need `persist=false`. `smoke_browser_close` disconnects; it does **not** quit that Chrome. Do not combine `cdp` with `channel`.

## Forms, files, dialogs, popups

Snapshot first, then:

```
smoke_browser_click selector=@4 dialog=accept
smoke_browser_click selector=@5 popup=true
smoke_browser_switch_tab index=0
smoke_browser_download url=https://images.unsplash.com/photo-xyz save_as=hero.jpg
smoke_browser_set_files selector=@7 paths=/abs/path/hero.jpg
smoke_browser_download selector=@8
```

Prefer `dialog=accept` on the click that opens the alert. Arm the next dialog only when the trigger is not a click.

## What this is not

| You might expect | What you actually get |
|------------------|------------------------|
| Agent uses the Chrome window you are looking at | Smoke's own living Chromium. `cdp=` attaches only to a debug Chrome you launched |
| Gmail / cookies from your daily Chrome | Empty unless the agent logs in inside Smoke (or debug Chrome with `cdp=`) |
| A second “testing” Chromium on every open | Only if the agent passes `persist=false`. Default open reuses one window |
| Window dies when the chat ends | Only if you `close` with `shutdown=true` |
| Task Spaces / take over from the agent | Named MCP sessions. You do not share tabs with the agent |
| Screenshot on every click | Path on disk only when `screenshot=true` |
| `npx smoke` | Different npm package. Install from the GitHub command above |

## Tools

OpenCode names below. Cursor / Claude Code: drop the `smoke_` prefix.

### See the page

| Tool | When to use |
|------|-------------|
| `smoke_browser_snapshot(scope?)` | Default. `@ref` list; same-origin iframes tagged `iframe` |
| `smoke_browser_execute(js_code)` | Scrape / inspect, return JSON |
| `smoke_browser_extract_dom()` | Buttons/inputs/links without `@refs`. Prefer snapshot |
| `smoke_browser_wait(state, selector?, url?, js?)` | Load, visible, URL glob, or `waitForFunction` |

### Move around

| Tool | When to use |
|------|-------------|
| `smoke_browser_open(url, persist?, session?, user_data_dir?, channel?, cdp?)` | Default = living Chromium. `persist=false` = test. `cdp=9222` = debug Chrome |
| `smoke_browser_session` | `current` / `use` / `list` / `close` named sessions |
| `smoke_browser_script(js_code)` | One round trip with loops |
| `smoke_browser_run(actions_json)` | JSON batch, no loops |
| `smoke_browser_open_tab` / `get_tabs` / `switch_tab` | Extra tabs |
| `smoke_browser_scroll` / `reload` / `hover` / `press` | Scroll (default down 200px), reload, menus, keys |
| `smoke_browser_close(shutdown?)` | Default leaves the living window. `shutdown=true` kills persist Chromium |

### Click, type, files

| Tool | When to use |
|------|-------------|
| `smoke_browser_click(selector, dialog?, popup?)` | CSS or `@1` |
| `smoke_browser_type` / `paste` / `drag` | Fill, contenteditable chunk, drag `@n` onto `@n` |
| `smoke_browser_type_guess` | Dummy email/password for a smoke test |
| `smoke_browser_select_option` | `<select>` by value, label, or index |
| `smoke_browser_set_files` / `download` | File input; save under `artifacts/downloads/` |
| `smoke_browser_handle_dialog` | Next JS dialog if the trigger is not a click |

### Evidence

| Tool | When to use |
|------|-------------|
| `smoke_browser_console` / `errors` | Capped logs |
| `smoke_browser_network_capture` / `block_resources` / `inject_script` | Capture, block, mock |
| `smoke_browser_screenshot` / `screenshot_diff` / `highlight` | Visual, on demand |
| `smoke_browser_get_cookies` / `set_cookie` / `clear_cookies` / `storage` | Cookies and storage |
| `smoke_browser_report` | Writes `artifacts/smoke-report.md` |
| `smoke_browser_offscreen` | Hidden page in the same context |

`screenshot=true` on click/type/open writes a file path. `screenshot_base64=true` is an escape hatch.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Chromium missing / launch error | Run the GitHub `npx` command again, or `.browser-smoke/.venv/bin/playwright install chromium` |
| Tools look stale, or every click returns a screenshot | Run setup again and restart the host |
| OpenCode shows `browser-smoke_browser_open` | Old MCP key. Setup writes id `smoke` |
| Two Chromium windows | Default open is persist. Do not also pass `persist=false` or `cdp=` unless you mean it |
| Smoke test reused login cookies | Pass `persist=false session=test` |
| CDP connect failed / Chrome 136+ | Daily Gmail Chrome cannot be attached. Launch debug Chrome with a non-default `--user-data-dir` and `cdp=9222` |
| `cdp` + `channel` errors | Use only one |
| Connection refused | The target app is not running |
| Python not found | Install Python 3.10+ |
| Two sessions keep hitting the same tab | Pass `session=` on every tool |
| `npx smoke` does the wrong thing | That package is not this project. Use `npx github:sukirman1901/browser-smoke` |

## Development

```bash
git clone https://github.com/sukirman1901/browser-smoke.git
cd browser-smoke
python3 -m unittest discover -s tests -v
npm link
```

After `npm link`, the CLI is `smoke` (alias `browser-smoke`).

Releases: [CHANGELOG.md](CHANGELOG.md). Latest is **v1.4.0**.

## License

MIT
