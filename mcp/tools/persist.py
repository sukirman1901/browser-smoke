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
    sock.settimeout(0.2)
    try:
        sock.connect(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        sock.close()


def spawn_chromium(executable: str, port: int, user_data_dir: str, *, headless: bool) -> int:
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
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        if cdp_alive(port):
            return proc.pid
        if proc.poll() is not None:
            raise RuntimeError(f"Chromium exited before CDP was ready (code {proc.returncode})")
        time.sleep(0.15)
    raise RuntimeError(f"CDP did not start on port {port}")


def kill_pid(pid: int) -> None:
    if pid <= 0:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
