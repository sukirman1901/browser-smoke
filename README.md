# Browser Smoke

A Playwright browser your coding agent can drive: open a site, fill a form, scrape a page, or smoke-test a UI you just built.

It is an [MCP](https://modelcontextprotocol.io) server. You install it once; the agent calls tools. Results are compact JSON. Screenshots stay off unless you ask.

Works with [OpenCode](https://opencode.ai), [Cursor](https://cursor.com), [Claude Code](https://docs.anthropic.com/en/docs/claude-code), and any MCP client.

This is **not** your daily Chrome. The agent gets its own Chromium. Logins you already have in Chrome do not carry over. See [What this is not](#what-this-is-not).

## Quick start

Need **Node.js 18+** and **Python 3.10+**. Chromium is installed by `init`.

### 1. Install

```bash
npx browser-smoke init
```

Pick local or global, then which host (OpenCode, Cursor, Claude Code, or all). `init` copies the MCP server, creates a venv, and installs Playwright Chromium.

Restart the host after install (quit/reopen OpenCode, Cursor, or Claude Code).

| Command | What it does |
|---------|----------------|
| `npx browser-smoke init` | Interactive |
| `npx browser-smoke init --local --all` | This project, all three hosts |
| `npx browser-smoke init --local --cursor` | Cursor only |
| `npx browser-smoke init --local --claude` | Claude Code only |
| `npx browser-smoke init --global --opencode` | OpenCode user config |
| `npx browser-smoke init --print` | Print the stdio MCP entry |

After a version upgrade, run `init` again so MCP files refresh, then restart the host.

### 2. First task

Paste this into the agent:

```
Use browser-smoke: open https://example.com, take a snapshot, tell me the title and the first five links. Do not screenshot.
```

On OpenCode the tools show as `smoke_browser_open`, `smoke_browser_snapshot`, … (MCP server id `smoke` + tool name). The package is still `browser-smoke`.

### 3. How the agent should drive it

Same loop for a daily task and a smoke test:

1. `browser_open` the URL.
2. `browser_snapshot` — you get `@1`, `@2`, `@3` for buttons, inputs, links.
3. Click or type those refs (`@1`). After navigation, snapshot again. Old refs error on purpose.
4. For several steps, prefer **one** `browser_script` (loops allowed) or one `browser_run`. Do not chain eight MCP calls.
5. Scrape with `browser_execute` returning a small JSON array — not `innerHTML`.
6. Screenshot only for a visual bug. Never `screenshot_base64`.

## Daily task (window stays up)

Use this when the agent should browse the way you would: open a site, click around, leave the window open for the next chat.

```
browser_open(url="https://example.com", persist=true, session="work")
browser_script(
  js_code="const s = await snapshot(); log(s.snapshot); await click('@1');",
  session="work",
)
browser_close(shutdown=false, session="work")
```

- `persist=true` starts a detached Chromium (CDP). It survives MCP restart.
- `browser_close(shutdown=false)` disconnects without killing the window.
- Next chat: `browser_open(..., persist=true, session="work")` reconnects.

If two named sessions are open, pass `session=` on **every** tool (`snapshot`, `click`, `script`, `close`), not only `open`.

Helpers inside `browser_script`: `open`, `click`, `type`, `snapshot`, `wait`, `execute`, `press`, `hover`, `scroll`, `dialog`, `download`, `upload`, `select`, `switchTab`. `wait("load")` and `wait("#ready")` are fine.

## Smoke test (after you ship a feature)

Use this when a local app should still load, submit a form, and stay quiet in the console.

```
browser_open(url="http://localhost:5173")
browser_snapshot()
browser_run(actions_json='[{"action":"type","selector":"@1","text":"test@test.com"},{"action":"click","selector":"@3"}]')
browser_console()
browser_errors()
browser_report(results_json)
browser_close()
```

The app must already be running. Failures should block. Debug with console, errors, then `network_capture(mode="get")` (no headers). Screenshot last.

Visual regression (opt-in):

```
browser_screenshot_diff(name="homepage")
```

Writes a baseline/diff under `artifacts/`. No PNG in the tool result unless you ask.

## Scrape

```
browser_open(url="https://example.com")
browser_execute(js_code="() => [...document.querySelectorAll('a')].slice(0,50).map(a => ({t:a.textContent.trim(), h:a.href}))")
browser_close()
```

## Keep a login (Playwright profile, not Chrome)

The agent can log in once and reuse that session next time — in **its** Chromium, not the Chrome you use every day.

```
browser_open(url="https://app.example.com", user_data_dir=".browser-smoke/profile")
```

Cookies live in that folder. Gmail already open in your Chrome will not appear here.

Need stock Chrome instead of bundled Chromium? `browser_open(..., channel="chrome")`. Do not combine `channel` with `persist=true`.

## Forms, files, dialogs, popups

Snapshot first, then:

```
browser_click(selector="@4", dialog="accept")
browser_click(selector="@5", popup=true)
browser_switch_tab(index=0)
browser_set_files(selector="@7", paths="/abs/path/cv.pdf")
browser_download(selector="@8")
```

Prefer `click(..., dialog="accept")` over a separate `browser_handle_dialog`. Arm the next dialog only when the trigger is not a click.

## What this is not

| You might expect | What you actually get |
|------------------|------------------------|
| Agent uses the Chrome window you are looking at | Separate Playwright Chromium |
| Gmail / cookies from your daily Chrome | Empty profile, unless the agent logs in (or you set `user_data_dir`) |
| Window dies when the chat ends | Only if you `close(shutdown=true)`. `persist=true` + `shutdown=false` keeps it |
| Task Spaces / take over from the agent | Named MCP sessions. You do not share tabs with the agent |
| Screenshot on every click | Path on disk only when `screenshot=true` |

## Tools

Names below are the MCP tools. OpenCode prefixes them with `smoke_`.

### See the page

| Tool | When to use |
|------|-------------|
| `browser_snapshot(scope?)` | Default. `@ref` list; same-origin iframes tagged `iframe` |
| `browser_execute(js_code)` | Scrape / inspect, return JSON |
| `browser_extract_dom()` | Buttons/inputs/links without `@refs`. Prefer snapshot |
| `browser_wait(state, selector?, url?, js?)` | Load, visible, URL glob, or `waitForFunction` |

### Move around

| Tool | When to use |
|------|-------------|
| `browser_open(url, persist?, session?, user_data_dir?, channel?)` | Start or reconnect. Pass `session=` on later tools too |
| `browser_session` | `current` / `use` / `list` / `close` named sessions |
| `browser_script(js_code)` | One round trip with loops |
| `browser_run(actions_json)` | JSON batch, no loops |
| `browser_open_tab` / `browser_get_tabs` / `browser_switch_tab` | Extra tabs |
| `browser_scroll` / `browser_reload` / `browser_hover` / `browser_press` | Scroll (default down 200px), reload, menus, keys |
| `browser_close(shutdown?)` | `shutdown=false` leaves a persist window |

### Click, type, files

| Tool | When to use |
|------|-------------|
| `browser_click(selector, dialog?, popup?)` | CSS or `@1` |
| `browser_type` / `browser_paste` / `browser_drag` | Fill, contenteditable chunk, drag `@n` onto `@n` |
| `browser_type_guess` | Dummy email/password for smoke |
| `browser_select_option` | `<select>` by value, label, or index |
| `browser_set_files` / `browser_download` | File input; save under `artifacts/downloads/` |
| `browser_handle_dialog` | Next JS dialog if the trigger is not a click |

### Evidence (smoke)

| Tool | When to use |
|------|-------------|
| `browser_console` / `browser_errors` | Capped logs |
| `browser_network_capture` / `browser_block_resources` / `browser_inject_script` | Capture, block, mock |
| `browser_screenshot` / `browser_screenshot_diff` / `browser_highlight` | Visual, on demand |
| `browser_get_cookies` / `browser_set_cookie` / `browser_clear_cookies` / `browser_storage` | Cookies and storage |
| `browser_report` | Writes `artifacts/smoke-report.md` |
| `browser_offscreen` | Hidden page in the same context |

`screenshot=true` on click/type/open writes a file path. `screenshot_base64=true` is an escape hatch.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Chromium missing / launch error | `npx browser-smoke init` again, or `.browser-smoke/.venv/bin/playwright install chromium` |
| Tools look stale, or every click returns a screenshot | `init` again and restart the host — MCP files were not synced |
| OpenCode shows `browser-smoke_browser_open` | Old server id. `init` writes MCP id `smoke` |
| `persist=true` + `channel=chrome` errors | Omit `channel`. Persist is bundled Chromium only |
| Connection refused | The target app is not running |
| Python not found | Install Python 3.10+ |
| Two sessions keep hitting the same tab | Pass `session=` on every tool |
| `wait("load")` inside `browser_script` crashed | Upgrade to v1.3.1+ and `init` |

## Development

```bash
git clone https://github.com/sukirman1901/browser-smoke.git
cd browser-smoke
python3 -m unittest discover -s tests -v
npm link
```

Releases: [CHANGELOG.md](CHANGELOG.md). Latest is **v1.3.2**.

## License

MIT
