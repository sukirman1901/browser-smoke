"""Named BrowserSession registry. Factory is injected to avoid importing Playwright in tests."""

from __future__ import annotations

from typing import Any, Callable


class SessionRegistry:
    def __init__(self, factory: Callable[..., Any]):
        self._factory = factory
        self._sessions: dict[str, Any] = {}
        self._current = "default"

    @property
    def current(self) -> str:
        return self._current

    def get(self, name: str = "", *, switch: bool = True):
        from tools.persist import safe_session_name

        key = safe_session_name(name or self._current)
        if name and switch:
            self._current = key
        if key not in self._sessions:
            self._sessions[key] = self._factory(name=key)
        return self._sessions[key]

    def use(self, name: str):
        return self.get(name)

    def drop(self, name: str) -> None:
        from tools.persist import safe_session_name

        key = safe_session_name(name)
        self._sessions.pop(key, None)
        if self._current == key:
            self._current = "default"

    def names(self) -> list[str]:
        return list(self._sessions.keys())
