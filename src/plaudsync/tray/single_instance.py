"""Tray single-instance file lock — ${state_root}/.plaudsync/tray.lock.

Druhá instance: lock fail → raise TrayInstanceLockHeld → caller (app.main_tray)
zaloguje warning + (volitelně) zobrazí toast + exit 0.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import portalocker


class TrayInstanceLockHeld(Exception):
    """Another tray process is currently holding the lock."""


class TrayInstanceLock:
    def __init__(self, state_root: Path) -> None:
        self._path = state_root / ".plaudsync" / "tray.lock"
        self._fh: Any = None

    def __enter__(self) -> "TrayInstanceLock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fh = portalocker.Lock(
                str(self._path),
                mode="a",
                flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
                timeout=0,
            )
            self._fh.acquire()
        except portalocker.LockException as e:
            raise TrayInstanceLockHeld(f"tray lock held: {self._path}") from e
        return self

    def __exit__(self, *exc: object) -> None:
        if self._fh is not None:
            try:
                self._fh.release()
            finally:
                self._fh = None
