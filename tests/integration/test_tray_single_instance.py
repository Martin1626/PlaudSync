"""single_instance — tray.lock zajišťuje že běží max 1 tray proces na state_root."""
from __future__ import annotations

import pytest

from plaudsync.tray.single_instance import (
    TrayInstanceLock,
    TrayInstanceLockHeld,
)


def test_first_acquire_succeeds(tmp_path):
    with TrayInstanceLock(tmp_path):
        pass  # acquired + released


def test_second_acquire_raises_held(tmp_path):
    with TrayInstanceLock(tmp_path):
        with pytest.raises(TrayInstanceLockHeld):
            with TrayInstanceLock(tmp_path):
                pass


def test_release_allows_reacquire(tmp_path):
    with TrayInstanceLock(tmp_path):
        pass
    with TrayInstanceLock(tmp_path):
        pass  # second acquire after release works
