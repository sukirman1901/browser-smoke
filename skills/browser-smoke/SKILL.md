---
name: browser-smoke
description: Use when testing UI after feature development — before commit, before PR, or after code changes that affect the frontend
---

## Browser Smoke Test Methodology

### Setup

Sebelum mulai, pastikan test app jalan (e.g. `npm run dev`, `localhost:5173`).

Gunakan `todowrite` untuk track tiap skenario test.

### Core Loop

**Setiap failure = blocking. Jangan lanjut sebelum fix.**

1. **Buka URL** → `browser_open(url)`
2. **Ekstrak DOM** → `browser_extract_dom()` — lihat semua element interaktif + selector
3. **Test interaksi** — klik, type, scroll, inject script, capture network
4. **Verify hasil** — tiap step: pass atau fail? Catat hasilnya.
5. **Kalau fail** → analisa penyebab:
   - Debug: `browser_network_capture(mode="get")` — cek network request/response
   - Debug: `browser_console()` — cek console errors
   - Debug: `browser_errors()` — cek JS runtime errors
   - Debug: `browser_screenshot_diff(name)` — visual regression check
   - Debug: `browser_highlight(selector)` — highlight element
   - Cari fix di codebase → edit → retest step yang sama
6. **Retest** — ulangi step yang fail sampai pass
7. **Kalau semua pass** → lanjut ke skenario berikutnya
8. **Generate report** → `browser_report(results_json)`

### Tools (Playwright MCP)

| Tool | Fungsi |
|------|--------|
| `browser_open(url, headless)` | Buka halaman, balikin title + status code + screenshot |
| `browser_extract_dom()` | List element interaktif (button, input, link) + selector |
| `browser_click(selector)` | Klik element, balikin screenshot |
| `browser_type(selector, text)` | Ketik teks ke input |
| `browser_type_guess(selector, type)` | Auto-fill (email/password/text) |
| `browser_screenshot()` | Screenshot halaman |
| `browser_screenshot_diff(name, threshold)` | Screenshot + diff dengan baseline (visual regression) |
| `browser_scroll(x, y)` | Scroll halaman |
| `browser_highlight(selector, color)` | Highlight element dengan outline (visual debugging) |
| `browser_execute(js_code)` | Execute JavaScript, balikin result |
| `browser_inject_script(script, url_pattern)` | Inject JS sebelum page load (mock API, test helpers) |
| `browser_offscreen(action, url, js)` | Hidden page untuk background processing |
| `browser_open_tab(url)` | Buka tab baru, fokus ke tab baru |
| `browser_get_tabs()` | List semua tab + title + URL + active status |
| `browser_console()` | Ambil console log yang tertangkap |
| `browser_errors()` | Ambil JS runtime errors yang tertangkap |
| `browser_network_capture(mode, patterns)` | Capture network requests/responses (start/stop/get) |
| `browser_block_resources(patterns)` | Block resources (images, analytics, etc) via glob |
| `browser_get_cookies()` / `browser_set_cookie()` / `browser_clear_cookies()` | Cookie management |
| `browser_storage(mode, storage, key, value)` | localStorage/sessionStorage access (all/get/set/clear) |
| `browser_report(results_json)` | Generate report markdown ke `artifacts/smoke-report.md` |
| `browser_close()` | Tutup browser session |

### Advanced Workflows

#### Network Monitoring

Capture network activity selama test untuk debug request/response:

1. Start: `browser_network_capture(mode="start", patterns="*.api.*,*.json")`
2. Lakukan interaksi (click, type, submit)
3. Get hasil: `browser_network_capture(mode="get")` — lihat status code, headers, body size
4. Stop: `browser_network_capture(mode="stop")`
5. Correlation: cocokkan network error dengan console error untuk diagnosis cepat

#### Script Injection

Inject JavaScript sebelum halaman dimuat untuk mocking atau test helpers:

1. Inject: `browser_inject_script(script="window.__TEST__ = true;")`
2. Buka URL: `browser_open(url)` — script jalan sebelum page load
3. Verify: `browser_execute(js_code="window.__TEST__")`

Berguna untuk: mock API response, inject polyfill, set test flags, bypass gate.

#### State Management (Cookies + Storage)

Setup state sebelum test atau verify state setelah test:

1. Set cookie: `browser_set_cookie(name="session", value="token123", domain=".example.com")`
2. Set localStorage: `browser_storage(mode="set", storage="local", key="theme", value="dark")`
3. Buka URL: state sudah siap
4. Verify: `browser_get_cookies()` / `browser_storage(mode="all", storage="local")`

#### Visual Regression

Deteksi perubahan visual yang tidak diinginkan:

1. Baseline: `browser_screenshot_diff(name="homepage")` — creates baseline on first run
2. After code change: jalankan lagi → compare dengan baseline
3. Output: `diff_pixels` count + `diff_screenshot` (base64 image of highlighted differences)
4. Threshold bisa diatur: `browser_screenshot_diff(name="homepage", threshold=0.05)`

#### Background Processing

Gunakan offscreen page untuk task paralel (network capture, API polling):

1. Open: `browser_offscreen(action="open", url="http://localhost:5173")`
2. Exec: `browser_offscreen(action="exec", js="fetch('/api/data').then(r=>r.json())")`
3. Close: `browser_offscreen(action="close")`

### Failure Analysis Loop

```
Step fail?
  → browser_network_capture(mode="get") untuk cek network error
  → browser_console() untuk cek console error
  → browser_errors() untuk cek runtime error
  → browser_screenshot_diff(name) untuk cek visual regression
  → browser_highlight(selector) untuk visual debugging
  → browser_execute() untuk inspect element state
  → Cari source code → edit → fix
  → Retest step yang sama
  → Kalau masih fail, repeat analisa
```

### Comprehensive Smoke Test (All Features)

Test scenario lengkap yang menggunakan semua capabilities baru:

```
1. browser_network_capture(mode="start")
2. browser_block_resources(patterns="*.jpg,*.png,analytics")
3. browser_inject_script(script="window.__TEST_MODE__=true")
4. browser_open(url="http://localhost:5173")
5. browser_screenshot_diff(name="initial-load")
6. browser_extract_dom()
7. browser_click(selector="button ...")
8. browser_console()
9. browser_errors()
10. browser_network_capture(mode="get")
11. browser_get_cookies()
12. browser_storage(mode="all", storage="local")
13. browser_report(results_json)
14. browser_close()
```

### Output

Laporan: `artifacts/smoke-report.md`
Format: tiap step + status ✅/❌ + screenshot + summary pass/fail.
