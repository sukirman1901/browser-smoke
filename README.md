# Browser Smoke

MCP Playwright browser for agents: daily tasks (open, click, fill, scrape) and smoke tests. Compact JSON, screenshots off by default.

Works with [OpenCode](https://opencode.ai), Cursor, Claude Code, and any MCP client.

See [CHANGELOG.md](CHANGELOG.md) for v1.2.3 (`smoke_browser_open` in OpenCode), v1.2.2 popup/drag/paste, and earlier token defaults.

## Prerequisites

| Requirement | Version |
|-------------|---------|
| Node.js | >= 18 |
| Python | >= 3.10 |
| Playwright Chromium | installed by `init` |

## Token defaults (v1.2)

Tool results are compact JSON. Clicks, types, and `open` **do not** attach PNG. Screenshot files go to `artifacts/shots/` only when you ask.

| Do | Don't |
|----|--------|
| `browser_snapshot` then click `@1` | `extract_dom` + screenshot on every click |
| `browser_run` for a flow | 8 separate MCP calls |
| `browser_execute` returning JSON | dump `innerHTML` or base64 images |

`npx browser-smoke init` always refreshes the MCP server files so this upgrade lands. OpenCode tool names are `smoke_browser_open` (MCP id `smoke` + tool `browser_open`).

## Quick install

```bash
npx browser-smoke init
```

Interactive: local/global, then OpenCode / Cursor / Claude Code / all.

| Command | Description |
|---------|-------------|
| `npx browser-smoke init` | Interactive |
| `npx browser-smoke init --local --all` | Project OpenCode + Cursor + Claude |
| `npx browser-smoke init --local --cursor` | Cursor `.cursor/mcp.json` only |
| `npx browser-smoke init --local --claude` | Claude Code `.mcp.json` only |
| `npx browser-smoke init --global --opencode` | OpenCode user config |
| `npx browser-smoke init --print` | Preview stdio MCP entry |

`init` always refreshes MCP server files. Restart the host after install.

## Tools

### Cheap observation

| Tool | Description |
|------|-------------|
| `browser_snapshot(scope?)` | Accessibility-ish `@ref` list. Prefer this. |
| `browser_extract_dom()` | Compact buttons/inputs/links (no bounding boxes) |
| `browser_execute(js_code)` | Page JS → JSON (scrape) |
| `browser_wait(state, selector?, url?, js?)` | load / visible / URL / `waitForFunction` |

### Navigation & batch

| Tool | Description |
|------|-------------|
| `browser_open(url, headless?, wait_until?, channel?, user_data_dir?)` | Bundled Chromium. Persistent profile via `user_data_dir` |
| `browser_run(actions_json)` | Many actions, one call |
| `browser_open_tab` / `browser_get_tabs` / `browser_switch_tab` / `browser_close` | Tabs |
| `browser_scroll(x?, y?)` | `scrollBy` (default down 200px) |
| `browser_reload` / `browser_hover` / `browser_press` | Reload, menus, keys |

### Interaction

| Tool | Description |
|------|-------------|
| `browser_click(selector, dialog?, popup?)` | CSS or `@1`. `dialog=accept` for alert/confirm. `popup=true` for `window.open` |
| `browser_type(selector, text)` | Fill (replaces value) |
| `browser_paste(selector, text)` | Insert as one chunk (contenteditable) |
| `browser_drag(source, target)` | Drag `@n` onto `@n` |
| `browser_type_guess(selector, input_type?)` | Dummy email/password/… |
| `browser_select_option(selector, value?, label?, index?)` | `<select>` |
| `browser_set_files(selector, paths)` | File input, comma-separated abs paths |
| `browser_download(selector, save_as?)` | Click + save to `artifacts/downloads/` |
| `browser_handle_dialog(action, prompt?)` | Arm the *next* dialog if the trigger is not a click |

Pass `screenshot=true` on these only when you need a file path. `screenshot_base64=true` is an escape hatch.

### Visual (on demand)

| Tool | Description |
|------|-------------|
| `browser_screenshot()` | Writes `artifacts/shots/NNNN.png`, returns path |
| `browser_screenshot_diff(name, threshold?)` | Baseline/diff on disk |
| `browser_highlight(selector)` | Outline for debugging |

### Network, console, state

| Tool | Description |
|------|-------------|
| `browser_console` / `browser_errors` | Capped, truncated |
| `browser_network_capture(mode, patterns?, headers?)` | start/stop/get |
| `browser_block_resources` / `browser_inject_script` | Block / mock |
| `browser_get_cookies(include_values?)` / `set` / `clear` | Cookies |
| `browser_storage(...)` | local/session storage |
| `browser_report(results_json)` | Writes markdown; does not echo it |
| `browser_offscreen(action, url?, js?)` | Hidden page |

## Usage

Smoke flow:

```
browser_open(url="http://localhost:5173")
browser_snapshot()
browser_run(actions_json='[{"action":"type","selector":"@1","text":"test@test.com"},{"action":"click","selector":"@3"}]')
browser_console()
browser_errors()
browser_report(results_json)
browser_close()
```

Scrape:

```
browser_open(url="https://example.com")
browser_execute(js_code="() => [...document.querySelectorAll('h1,h2,a')].slice(0,40).map(el => ({t:el.tagName, x:el.textContent.trim(), h:el.href||null}))")
browser_close()
```

Visual regression:

```
browser_screenshot_diff(name="homepage")
```

Persistent login (Playwright profile, not your daily Chrome):

```
browser_open(url="https://app.example.com", user_data_dir=".browser-smoke/profile")
```

Upload / download / dialog / popup:

```
browser_click(selector="@4", dialog="accept")
browser_click(selector="@5", popup=true)
browser_switch_tab(index=0)
browser_set_files(selector="@7", paths="/abs/path/cv.pdf")
browser_download(selector="@8")
```

## Troubleshooting

| Masalah | Solusi |
|---------|--------|
| Chromium error | `npx browser-smoke init` lagi, atau `.browser-smoke/.venv/bin/playwright install chromium` |
| Need real Chrome | `browser_open(..., channel="chrome")` |
| Connection refused | Target app harus jalan |
| Python not found | Python 3.10+ |
| Old tools / screenshots on every click | `init` ulang — sync MCP files |

## Development

```bash
git clone https://github.com/sukirman1901/browser-smoke.git
cd browser-smoke
python3 -m unittest discover -s tests -v
npm link
```

## License

MIT
