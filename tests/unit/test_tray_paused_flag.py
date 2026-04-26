"""paused_flag — file-based pause toggle pro tray scheduler."""
from __future__ import annotations

from pathlib import Path

from plaudsync.tray.paused_flag import is_paused, set_paused, clear_paused, toggle_paused


def test_is_paused_false_when_no_file(tmp_path):
    assert is_paused(tmp_path) is False


def test_set_paused_creates_flag_file(tmp_path):
    set_paused(tmp_path)
    assert is_paused(tmp_path) is True
    assert (tmp_path / ".plaudsync" / "paused.flag").exists()


def test_clear_paused_removes_flag(tmp_path):
    set_paused(tmp_path)
    clear_paused(tmp_path)
    assert is_paused(tmp_path) is False


def test_clear_paused_idempotent_when_no_flag(tmp_path):
    clear_paused(tmp_path)  # no-op, no error
    assert is_paused(tmp_path) is False


def test_toggle_paused_returns_new_state(tmp_path):
    assert toggle_paused(tmp_path) is True   # was unpaused → now paused
    assert toggle_paused(tmp_path) is False  # was paused → now unpaused


def test_set_paused_idempotent(tmp_path):
    set_paused(tmp_path)
    set_paused(tmp_path)  # 2× call, no error
    assert is_paused(tmp_path) is True
