# v1.5.0 — browser_assert + Auto-Transcript + Report dari Transcript

**Date:** 2026-09-16
**Status:** Draft untuk review
**Target version:** 1.5.0

## Ringkasan

Menutup loop smoke test agar punya bukti lolos/gagal yang objektif, bukan interpretasi agen:

1. **`browser_assert`** — tool MCP baru untuk verifikasi terprogram (harapan yang diverifikasi pass/fail).
2. **Auto-transcript JSONL** — setiap aksi + hasil pada satu sesi direkam otomatis, tanpa perlu disalin manual.
3. **`browser_report`** — berubah: tanpa `results_json` ia membaca transcript run terakhir sesi dan menghasilkan laporan + exit-code/status verdict.

Semua tool/aplikasi yang ada tetap bekerja; ini menambah lapisan, tidak menulis ulang.

## Konteks Kode Saat Ini (groudning)

- Tool MCP di `mcp/server.py`: semua memakai pola `async with locked_session(session) as sess:` lalu `return dumps(result)`. `locked_session` dibuka di `tools/browser.py`, didecorate dari `tools/registry.py`.
- Snapshots memberi `@ref` (`@1`, `@2`, …) via `parse_aria_snapshot`; ref disimpan di `self._refs` peta `sel`+`frame`. Resolusi selector lewat `self._locator(selector)` (mendukung `@n` dan CSS, termasuk `aria-ref=...`).
- `click`/`type_text` menangkap error dan memetakan dengan `classify_target_error`/`classify_type_error` → `status:error` + `code` (`expired_ref`, `intercepted`) + hint.
- `run_actions` (`_run_one`) berhenti di error pertama; `browser_script` lewat `_script_rpc` + helper di `mcp/script-host.mjs`.
- `payload.py`: `dumps()` memampat JSON dan memotong >24k char; `SMOKE_VERSION = "1.4.3"`.
- `reporter.py`: `generate_report(url, results)` → tabel markdown + summary + daftar Failures. `browser_report(results_json)` saat ini **wajib** `results_json` (disalin agen).
- Tes: `tests/` unittest murni tanpa Playwright (registry factory di-inject). CI: `python -m unittest discover -s tests -v`.

## Pendekatan yang Dipilih

Alternatif yang dipertimbangkan:

- **A (dipilih):** Tool assert + transcript + report dari transcript. Verdict objektif, minimal surface, semua aksi lama tetap jalan. Report jadi dari data nyata, bukan salinan agen.
- **B:** Record → replay file `.smoke` deterministik. Lebih mencolok tapi effort jauh lebih besar (schema flow, rebase selector, langkah berulang) dan duplikatif dengan A.
- **C:** Hanya scoped snapshot + `data-smoke-pin`. Cepat tapi tidak memberi verdict.

A menutup gap utama (bukti lolos/gagal); B dan C masih bisa menjadi rilis terpisah berikutnya.

## Desain

### 1. `browser_assert` — tool verifikasi

Signature:

```
browser_assert(
    expect: str,            # text | url | visible | hidden | count | input_value
    text: str = "",         # untuk text/url/input_value
    selector: str = "",     # CSS atau @n; kosong = seluruh halaman (text) / input pertama (input_value)
    count: int = 0,         # untuk expect="count" (jumlah eksak locator)
    timeout: int = 5000,    # ms polling hingga kondisi terpenuhi
    negate: bool = False,   # membalik hasil (seperti expect().not)
    session: str = "",
)
```

Semantik per `expect`:

| expect       | True jika |
|--------------|-----------|
| `text`       | innerText elemen berisi `text` (selector kosong → body page) |
| `url`        | `page.url` mengandung `text` |
| `visible`    | lokator berstate visible (detach = fail) |
| `hidden`     | lokator hidden **atau** detached |
| `count`      | `locator.count()` == `count` (eksak) |
| `input_value`| value input di `selector` (atau input pertama) == `text` |

Perilaku:
- `selector` kosong untuk `text` → pakai `locator("body")`; untuk `input_value` → `locator("input, textarea, select").first`.
- Polling dengan batas `timeout`; `negate=True` membalik keputusan (mis. `expect="text" negate` = teks TIDAK boleh muncul).
- Error tool (bukan verdict) bila: tidak ada page (`_need_page`), `expect` tidak dikenal, `selector` kosong padahal wajib (`visible`/`hidden`/`count`).
- Hasil `status: "ok"` bila kondisi terpenuhi, `status: "assert_fail"` bila tidak — **bukan** `status:"error"`; ini verdict test. Wajib menyertakan `assert` (deskripsi), `expected`, `actual` ringkas.

Contoh hasil:

```json
{"status":"ok","assert":"text @3 contains 'Berhasil disimpan'","expected":"text contains 'Berhasil disimpan'","actual":"found in @3"}
{"status":"assert_fail","assert":"url contains /checkout","expected":"url contains /checkout","actual":"https://a.com/cart","hint":"Snapshot or screenshot to debug."}
```

Modul: logika hasil dibangun di `mcp/tools/assertion.py` (murni, tanpa Playwright) agar diuji unit; bagian DOM/Polling di `BrowserSession.assert_condition()` di `mcp/tools/browser.py` memakai `_locator`, `_need_page`, dan `page.wait_for_function`/`locator.wait_for`.

### 2. Auto-transcript JSONL

- File: `artifacts/transcripts/<safe_session>.jsonl` (satu baris JSON per aksi), rotasi ke `.1`, `.2`, … bila > 2000 baris.
- Direkam **setiap pemanggilan tool MCP** (termasuk `browser_script`, `browser_run`) oleh decorator `_trace(action)` di `server.py` (di bawah `@mcp.tool()` sehingga tiap call masuk track).
- Bidang per baris: `seq`, `ts` (ISO), `run_id`, `session`, `action` (nama tool), `params` (ringkas), `status` (diekskstrak dari JSON hasil), `elapsed_ms`, `screenshot_path` bila ada, `results` (daftar ringkas hasil bersarang, dipotong).
- **Kebijakan redaksi:** nilai `screenshot_base64` dihapus; `js_code`/`actions_json` disimpan terpotong (400 char); text param dibatasi 120 char; isi body hasil tidak disimpan kecuali `status`/kunci ringkas.
- **Run boundary:** `run_id` baru dimulai pada `browser_open` (atau `ensure_started`) untuk sesi itu; `browser_report` membaca semua baris sesi tsb sejak run terakhir. Tanpa `open` sebelumnya (attach hanya) → run dimulai dari entri pertama.
- Sesi dengan nama (mis. `test`) → file sendiri; sesi `default` → `artifacts/transcripts/default.jsonl`.

### 3. `browser_report` — dari transcript

Perubahan signature: `results_json: str = ""` (opsional).

- Bila `results_json` diisi → perilaku lama (kompatibel ke belakang).
- Bila kosong → ambil transcript run terakhir sesi → peta tiap baris ke hasil `reporter.generate_report`:
  - `status ok` → pass; `assert_fail`/`error` → fail.
  - Kolom screenshot terisi bila baris punya `screenshot_path`.
- Output: menambah `verdict: "passed"|"failed"`, `passed`, `failed`, `total`, dan `exit_code` (0 bila semua pass, 1 bila ada fail) agar bisa dipakai CI.
- Tanpa baris transcript → `status:"error"` dengan hint "no recorded actions; run browser_open then actions, or pass results_json".

### 4. Integrasi `run_actions` + `browser_script`

- `_run_one` menerima aksi `assert` → `self.assert_condition(...)`; `assert_fail` dicatat sebagai fail (bukan henti error? → **henti**, konsisten dgn "stops on first error", tapi statusnya `assert_fail`).
- `script_rpc` + `coerce_rpc_params` + helper `script-host.mjs` menambah helper `assert(...)` dengan parameter yang sama.

### 5. Versi, skill, dokumentasi

- `SMOKE_VERSION` → `1.5.0` (`payload.py`) + `package.json` version.
- `skills/browser-smoke/SKILL.md`: tambah langkah assert pada loop smoke test dan seksi "Verification": `open → snapshot → act → assert → (report)`, catat bahwa verdict dari `browser_assert`, screenshot hanya bila diminta.
- `README.md`: dokumentasi `browser_assert` + report otomatis.
- `CHANGELOG.md`: entri 1.5.0.

## Tidak Termasuk (scope out)

- Record → replay `.smoke` (opsi B) — rilis terpisah.
- Scoped snapshot / `data-smoke-pin` (opsi C) — rilis terpisah.
- Visual pointer & pergerakan kursor native.
- Otomasi level OS.
- Perubahan pada mode session/Chrome lifecyle.

## Error Handling

- `expect` tidak dikenal → `{"status":"error","message":"unknown expect: X","hint":"use text|url|visible|hidden|count|input_value"}`.
- Tidak ada page → reuse `_need_page` (status error, hint open dulu).
- Timeout polling → `assert_fail` dengan `actual` = gambaran saat timeout (mis. "not visible after 5000ms").
- `assert` pada `run_actions`/`script` gagal → berhenti, status `assert_fail`, transcript mencatat fail.
- Transcript gagal tulis (disk penuh/permission) → jangan rusak tool: catat ke `stderr`, lanjutkan tool normal, tandai `"transcript":"error"` di output tool.

## Testing

- `tests/test_assertion.py` (murni): shaping hasil untuk tiap expect, `negate`, timeout, unknown-expect, status error.
- `tests/test_transcript.py`: append+rotasi, run boundary via open, redaksi (hapus base64; truncate params), mapping baris→results untuk report, verdict/exit_code.
- `tests/test_reporter.py` (jika belum): kompatibilitas `results_json` lama masih jalan.
- Tidak menambah dependency; tetap unittest + CI yang sama.

## Checklist Rilis

- [ ] `mcp/tools/assertion.py` (shaping murni) + unit test
- [ ] `BrowserSession.assert_condition` + `@mcp.tool browser_assert` + test manual via MCP
- [ ] `mcp/tools/transcript.py` (recorder + run boundary) + `_trace` di server.py + rotasi
- [ ] `browser_report` via transcript + verdict/exit_code + unit test
- [ ] `_run_one` aksi `assert` + `script_rpc` + `script-host.mjs` helper
- [ ] bump versi + skill + README + CHANGELOG
- [ ] `python -m unittest discover -s tests -v` hijau