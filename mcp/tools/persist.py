"""Detached Chromium + CDP helpers. No Playwright import (unit-testable)."""

from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
import zlib
from typing import Any


def safe_session_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", (name or "").strip()).strip("._")
    return (cleaned[:40] or "default")


def session_cdp_port(name: str) -> int:
    return 9333 + (zlib.crc32(safe_session_name(name).encode()) % 467)


def state_dir() -> str:
    path = os.path.join(os.getcwd(), ".browser-smoke", "sessions")
    os.makedirs(path, exist_ok=True)
    return path


def state_path(name: str) -> str:
    return os.path.join(state_dir(), f"{safe_session_name(name)}.json")


def read_state(name: str) -> dict[str, Any]:
    path = state_path(name)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_state(name: str, data: dict[str, Any]) -> None:
    with open(state_path(name), "w", encoding="utf-8") as f:
        json.dump(data, f)


def clear_state(name: str) -> None:
    path = state_path(name)
    if os.path.exists(path):
        os.remove(path)


def cdp_alive(port: int) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1)
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def port_free(port: int) -> bool:
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def pid_on_port(port: int) -> int:
    try:
        out = subprocess.check_output(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        for line in out.split():
            if line.isdigit():
                return int(line)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    return 0


def _usable_cdp_port(port: int) -> bool:
    # Bind-check first. Connecting for cdp_alive on a non-HTTP listener can
    # fill the accept backlog and make a follow-up probe look "free".
    return port_free(port) or cdp_alive(port)


def allocate_port(name: str, preferred: int = 0) -> int:
    if preferred > 0 and _usable_cdp_port(preferred):
        return preferred
    base = session_cdp_port(name)
    for offset in range(16):
        port = base + offset
        if port > 65535:
            break
        if _usable_cdp_port(port):
            return port
    raise RuntimeError("no free CDP port in range")


def spawn_chromium(
    executable: str,
    port: int,
    user_data_dir: str,
    *,
    headless: bool,
    log_path: str = "",
) -> int:
    os.makedirs(user_data_dir, exist_ok=True)
    cmd = [
        executable,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
    ]
    if headless:
        cmd.append("--headless=new")
    cmd.append("about:blank")
    logf = open(log_path, "ab") if log_path else subprocess.DEVNULL
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=logf,
            start_new_session=True,
        )
    finally:
        if log_path and hasattr(logf, "close"):
            logf.close()
    deadline = time.time() + 20
    while time.time() < deadline:
        if cdp_alive(port):
            return proc.pid
        if proc.poll() is not None:
            hint = ""
            if log_path and os.path.exists(log_path):
                try:
                    with open(log_path, "rb") as f:
                        hint = f.read()[-400:].decode("utf-8", "replace")
                except OSError:
                    pass
            raise RuntimeError(
                f"Chromium exited before CDP was ready (code {proc.returncode})"
                + (f": {hint.strip()}" if hint.strip() else "")
            )
        time.sleep(0.15)
    raise RuntimeError(f"CDP did not start on port {port}")


def kill_pid(pid: int) -> None:
    if pid <= 0:
        return

    def _alive() -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pid, sig)
        except (OSError, AttributeError):
            try:
                os.kill(pid, sig)
            except OSError:
                return
        deadline = time.time() + (2 if sig == signal.SIGTERM else 1)
        while time.time() < deadline:
            if not _alive():
                return
            time.sleep(0.1)
        if not _alive():
            return
