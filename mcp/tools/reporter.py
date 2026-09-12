import json
from datetime import datetime


def generate_report(url: str, results: list[dict]) -> str:
    lines = []
    lines.append(f"# Smoke Test Report — {url}")
    lines.append(f"**Date:** {datetime.now().isoformat()}")
    lines.append("")
    lines.append("| # | Step | Status | Screenshot |")
    lines.append("|---|------|--------|------------|")
    passed = 0
    failed = 0
    for i, r in enumerate(results, 1):
        status = "✅ Pass" if r.get("status") == "ok" else "❌ Fail"
        if r.get("status") == "ok":
            passed += 1
        else:
            failed += 1
        step = r.get("step") or r.get("action") or "step"
        detail = r.get("detail", r.get("selector", r.get("url", "")))
        ss = "📷" if r.get("screenshot") or r.get("screenshot_path") else ""
        lines.append(f"| {i} | {step}: {detail} | {status} | {ss} |")
    lines.append("")
    lines.append(f"**Summary:** {passed} passed, {failed} failed, {len(results)} total")
    lines.append("")
    if failed > 0:
        lines.append("### Failures")
        for r in results:
            if r.get("status") != "ok":
                step = r.get("step") or r.get("action") or "step"
                lines.append(f"- **{step}:** {r.get('message', 'Unknown error')}")
    return "\n".join(lines)


def make_result(step: str, status: str, **kwargs) -> dict:
    return {"step": step, "status": status, **kwargs}
