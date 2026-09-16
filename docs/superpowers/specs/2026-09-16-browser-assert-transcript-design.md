# v1.5.0 — browser_assert

**Date:** 2026-09-16
**Status:** Agreed — assert only
**Target version:** 1.5.0

## Ringkasan

Smoke test punya bukti lolos/gagal yang objektif. Snapshot tetap peta `@n`. Verdict dari `browser_assert`.

Tidak termasuk: auto-transcript JSONL, report dari transcript, `exit_code` CI, record-replay, scoped snapshot.

## Konteks (v1.4.3)

- Loop skill: `open → snapshot → act → snapshot lagi`. Agen yang memutuskan lolos.
- `browser_wait` menunggu load / visible / URL glob / `waitForFunction`. Timeout = `status:error`, bukan fail tes. Tidak ada text-contains, count, input_value, expected/actual.
- `browser_report` tetap wajib `results_json` (tidak diubah).
- Tool MCP di `mcp/server.py`; aksi batch di `_run_one`; script helper di `_script_rpc` + `mcp/script-host.mjs`.
- Tes: unittest tanpa Playwright. `SMOKE_VERSION = "1.4.3"`.

## Desain

### `browser_assert`

```
browser_assert(
    expect: str,            # text | url | visible | hidden | count | input_value
    text: str = "",         # text / url (substring); input_value (eksak)
    selector: str = "",     # CSS atau @n
    count: int = 0,         # expect=count, jumlah eksak
    timeout: int = 5000,    # ms, polling sampai kondisi terpenuhi
    negate: bool = False,
    session: str = "",
)
```

| expect        | True jika |
|---------------|-----------|
| `text`        | innerText berisi `text` (selector kosong → `body`) |
| `url`         | `page.url` mengandung `text` (substring, bukan glob `wait`) |
| `visible`     | locator visible. Detached / tidak terlihat = fail |
| `hidden`      | locator hidden **atau** detached (termasuk `@n` yang sudah hilang dari DOM) |
| `count`       | jumlah locator (tanpa mereduksi ke `.first`) == `count` |
| `input_value` | value == `text` (eksak). Selector kosong → `input, textarea, select` pertama |

Error tool (`status:error`), bukan verdict:

- tidak ada page (`_need_page`)
- `expect` tidak dikenal
- `selector` kosong untuk `visible` / `hidden` / `count`
- `text` kosong untuk `text` / `url`
- `@n` yang tidak pernah ada di snapshot (`Unknown ref`)

Verdict:

- kondisi terpenuhi → `status:ok`
- tidak terpenuhi / timeout → `status:assert_fail` (bukan `error`)
- wajib: `assert`, `expected`, `actual` ringkas; fail menambah `hint`

`negate=true` membalik keputusan dan polling menunggu kondisi terbalik (`expect=visible` + negate = menunggu tidak terlihat). `negate="false"` (string) harus False.

`input_value` boleh `text=""`. `count=0` valid.

Jangan pakai `_locator()` yang melempar `Expired ref` untuk hidden/visible — detached adalah verdict, kecuali ref tidak pernah di-snapshot.

### Integrasi

- `_run_one` aksi `assert`. Batch berhenti pada `error` **atau** `assert_fail`. Status batch = status langkah yang gagal (`assert_fail` tetap `assert_fail`).
- `script_rpc` + helper `assert({ expect, text, selector, count, timeout, negate })`. Gagal → `run_script` mengembalikan payload assert itu dan menghentikan snippet (jangan lanjut helper berikutnya).
- Tidak mengubah `browser_report`.

### Modul

- `mcp/tools/assertion.py` — validasi, deskripsi, verdict, `as_bool`, `batch_halt` (murni).
- `BrowserSession.assert_condition()` — DOM/polling, locator mentah untuk `count`, `_need_page`.

## Docs

- `SMOKE_VERSION` + `package.json` → `1.5.0`
- Skill: `open → snapshot → act → assert`. Snapshot = peta. Assert = verdict.
- README: dokumentasi tool. Report tetap `results_json`.
- CHANGELOG 1.5.0. Tidak menjanjikan transcript.

## Testing

- `tests/test_assertion.py`: shaping, negate, unknown expect, selector wajib, text wajib, `as_bool("false")`, `batch_halt`.
- `tests/test_sessions.py`: coerce RPC dict `assert`.
- `SMOKE_VERSION == "1.5.0"`.
- Tidak menambah dependency.
