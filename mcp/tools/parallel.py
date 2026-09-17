"""Shape parallel tab jobs. Playwright gather stays on BrowserSession.run_parallel."""

from __future__ import annotations

import json
from typing import Any

MAX_PARALLEL_JOBS = 8


def _as_list(raw: str | list | None) -> Any:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    text = str(raw).strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        if "," in text and "://" in text:
            return [part.strip() for part in text.split(",") if part.strip()]
        return [text]
    return data


def _urls_from(raw: str | list | None) -> list[str] | dict:
    data = _as_list(raw)
    if isinstance(data, str):
        data = [data]
    if not isinstance(data, list):
        return {"status": "error", "message": "urls must be a JSON array of strings"}
    urls = [str(item).strip() for item in data if str(item).strip()]
    return urls


def _tabs_from(raw: str | list | None) -> list[int] | dict:
    data = _as_list(raw)
    if data == []:
        return []
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        data = [int(data)]
    if not isinstance(data, list):
        return {"status": "error", "message": "tabs must be a JSON array of indexes"}
    tabs: list[int] = []
    for item in data:
        try:
            tabs.append(int(item))
        except (TypeError, ValueError):
            return {"status": "error", "message": f"tab index is not a number: {item}"}
    return tabs


def _job_from_item(item: Any, default_js: str = "") -> dict | None:
    if isinstance(item, str):
        url = item.strip()
        if not url:
            return None
        job = {"url": url}
        if default_js:
            job["js"] = default_js
        return job
    if not isinstance(item, dict):
        return None
    url = str(item.get("url") or "").strip()
    js = str(item.get("js") or item.get("js_code") or default_js or "")
    tab = item.get("tab")
    if tab is None:
        tab = item.get("index")
    job: dict[str, Any] = {}
    if url:
        job["url"] = url
    elif tab is not None:
        try:
            job["tab"] = int(tab)
        except (TypeError, ValueError):
            return None
    else:
        return None
    if js:
        job["js"] = js
    return job


def _present(value: Any) -> bool:
    if value is None:
        return False
    if value == "" or value == [] or value == {}:
        return False
    return True


def _parse_jobs_payload(jobs_json: str | list | dict) -> list | dict:
    if isinstance(jobs_json, list):
        return jobs_json
    if isinstance(jobs_json, dict):
        return [jobs_json]
    try:
        data = json.loads(str(jobs_json))
    except json.JSONDecodeError as e:
        return {"status": "error", "message": f"jobs_json is not JSON: {e}"}
    if isinstance(data, dict):
        return [data]
    if not isinstance(data, list):
        return {"status": "error", "message": "jobs_json must be a JSON array"}
    return data


def parse_parallel_jobs(
    *,
    urls: str | list | None = "",
    js_code: str = "",
    jobs_json: str | list | dict = "",
    tabs: str | list | None = "",
    existing_tabs: list[int] | None = None,
) -> dict:
    """Return {jobs:[...]} or {status:error,...}. Max 8. Does not click — load and/or evaluate."""
    js = (js_code or "").strip()
    existing = list(existing_tabs or [])

    jobs: list[dict] = []
    if _present(jobs_json):
        data = _parse_jobs_payload(jobs_json)
        if isinstance(data, dict):
            return data
        for item in data:
            job = _job_from_item(item, js)
            if job is None:
                return {
                    "status": "error",
                    "message": "each job needs url or tab",
                    "hint": '[{"url":"https://a.com","js":"() => document.title"}]',
                }
            jobs.append(job)
    elif _present(urls):
        parsed = _urls_from(urls)
        if isinstance(parsed, dict):
            return parsed
        if not parsed:
            return {"status": "error", "message": "urls is empty"}
        for url in parsed:
            job = {"url": url}
            if js:
                job["js"] = js
            jobs.append(job)
    elif js:
        chosen = _tabs_from(tabs) if _present(tabs) else existing
        if isinstance(chosen, dict):
            return chosen
        if not chosen:
            return {
                "status": "error",
                "message": "No tabs to run on. Pass urls or open a page first.",
            }
        for index in chosen:
            jobs.append({"tab": index, "js": js})
    else:
        return {
            "status": "error",
            "message": "pass urls, jobs_json, or js_code",
            "hint": "browser_parallel urls='[\"https://a.com\",\"https://b.com\"]' js_code='() => document.title'",
        }

    if len(jobs) > MAX_PARALLEL_JOBS:
        return {
            "status": "error",
            "message": f"max {MAX_PARALLEL_JOBS} tabs at once (got {len(jobs)})",
        }
    if not jobs:
        return {"status": "error", "message": "no parallel jobs"}
    return {"jobs": jobs}


def settle_parallel(results: list[dict]) -> dict:
    ok = sum(1 for row in results if row.get("status") == "ok")
    failed = len(results) - ok
    status = "ok" if ok else "error"
    return {
        "status": status,
        "parallel": True,
        "ok": ok,
        "failed": failed,
        "results": results,
    }
