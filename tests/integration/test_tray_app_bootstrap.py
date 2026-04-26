"""tray.app.main_tray — bootstrap proces (mock pystray.Icon.run aby netrhal headless CI)."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


def test_main_tray_returns_7_on_missing_state_root(monkeypatch):
    monkeypatch.delenv("PLAUDSYNC_STATE_ROOT", raising=False)
    from plaudsync.tray.app import main_tray
    assert main_tray() == 7


def test_main_tray_returns_0_on_clean_exit(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "unclassified_dir: " + str(tmp_path / "unclassified") + "\nprojects: {}\n",
        encoding="utf-8",
    )

    fake_icon = MagicMock()

    def fake_run():
        # Simulate user clicked Quit immediately
        return None
    fake_icon.run = fake_run

    with patch("plaudsync.tray.app._build_icon", return_value=fake_icon):
        from plaudsync.tray.app import main_tray
        assert main_tray() == 0


def test_main_tray_returns_0_on_second_instance(monkeypatch, tmp_path):
    """2x tray na stejnem state_root: 2. exitne 0 + log warning."""
    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "unclassified_dir: " + str(tmp_path / "unclassified") + "\nprojects: {}\n",
        encoding="utf-8",
    )

    from plaudsync.tray.single_instance import TrayInstanceLock

    with TrayInstanceLock(tmp_path):
        from plaudsync.tray.app import main_tray
        assert main_tray() == 0  # second instance
