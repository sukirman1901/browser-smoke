"""Coerce browser_script RPC params so string helpers do not crash Python."""

from __future__ import annotations

LOAD_STATES = {
    "load",
    "domcontentloaded",
    "networkidle",
    "commit",
    "visible",
    "hidden",
    "attached",
    "detached",
}


def _as_paths(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return ",".join(str(p) for p in value if str(p).strip())
    return str(value or "")


def coerce_rpc_params(method: str, params: object) -> dict:
    if params is None:
        return {}
    if isinstance(params, dict):
        out = dict(params)
        if method in ("set_files", "upload"):
            paths = out.get("paths", out.get("files", ""))
            if not isinstance(paths, str):
                out["paths"] = _as_paths(paths)
        return out
    if isinstance(params, str):
        if method == "wait":
            if params in LOAD_STATES:
                return {"state": params}
            if "://" in params or "*" in params:
                return {"url": params}
            return {"selector": params}
        if method == "open":
            return {"url": params}
        if method == "scroll":
            if params.startswith("@"):
                return {"selector": params}
            try:
                return {"y": int(params)}
            except ValueError:
                return {"selector": params}
        if method in (
            "click",
            "hover",
            "press",
            "type",
            "paste",
            "download",
            "set_files",
            "select",
        ):
            return {"selector": params}
        if method == "switch_tab":
            try:
                return {"index": int(params)}
            except ValueError:
                return {}
        if method == "dialog":
            return {"handle": params}
        return {}
    if isinstance(params, (int, float)):
        if method == "switch_tab":
            return {"index": int(params)}
        if method == "scroll":
            return {"y": int(params)}
        return {}
    return {}
