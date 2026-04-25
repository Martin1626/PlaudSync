"""Concurrent sync file lock — fail-fast, exit code 5.

See docs/superpowers/specs/2026-04-25-sync-core-design.md Decision #6.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import portalocker


class SyncLockHeld(Exception):
    """Another sync process is currently holding the lock."""


class SyncLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._fh: Any = None

    def __enter__(self) -> "SyncLock":
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
            raise SyncLockHeld(f"sync lock held: {self._path}") from e
        return self

    def __exit__(self, *exc: object) -> None:
        if self._fh is not None:
            try:
                self._fh.release()
            finally:
                self._fh = None
