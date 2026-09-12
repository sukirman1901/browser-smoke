from __future__ import annotations

import hashlib
import io

from PIL import Image
from pixelmatch.contrib.PIL import pixelmatch


def compare_png(
    baseline_png: bytes,
    current_png: bytes,
    *,
    threshold: float = 0.01,
) -> dict:
    baseline_img = Image.open(io.BytesIO(baseline_png)).convert("RGBA")
    current_img = Image.open(io.BytesIO(current_png)).convert("RGBA")
    if baseline_img.size != current_img.size:
        return {
            "status": "error",
            "message": "screenshot size differs from baseline; not compared",
            "baseline_size": list(baseline_img.size),
            "current_size": list(current_img.size),
        }

    diff_img = Image.new("RGBA", baseline_img.size)
    diff_pixels = pixelmatch(
        baseline_img,
        current_img,
        diff_img,
        threshold=threshold,
        includeAA=True,
    )
    diff_buf = io.BytesIO()
    diff_img.save(diff_buf, format="PNG")
    return {
        "status": "ok" if diff_pixels == 0 else "diff",
        "diff_pixels": diff_pixels,
        "total_pixels": baseline_img.width * baseline_img.height,
        "threshold": threshold,
        "baseline_hash": hashlib.md5(baseline_png).hexdigest()[:12],
        "current_hash": hashlib.md5(current_png).hexdigest()[:12],
        "diff_png": diff_buf.getvalue() if diff_pixels > 0 else b"",
    }
