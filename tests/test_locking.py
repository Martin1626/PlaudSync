"""Unit tests for src/plaudsync/locking.py."""
from __future__ import annotations

from pathlib import Path

import pytest

from plaudsync.locking import SyncLock, SyncLockHeld


def test_lock_acquire_and_release(tmp_path: Path) -> None:
    lock_path = tmp_path / "sync.lock"
    with SyncLock(lock_path):
        assert lock_path.exists()
    # After context, lock file may exist (portalocker keeps file) but lock released.
    # Re-acquire must succeed:
    with SyncLock(lock_path):
        pass


def test_second_acquire_raises_SyncLockHeld(tmp_path: Path) -> None:
    lock_path = tmp_path / "sync.lock"
    lock_a = SyncLock(lock_path)
    lock_a.__enter__()
    try:
        lock_b = SyncLock(lock_path)
        with pytest.raises(SyncLockHeld):
            lock_b.__enter__()
    finally:
        lock_a.__exit__(None, None, None)
