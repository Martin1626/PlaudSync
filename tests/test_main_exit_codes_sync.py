"""Integration tests for __main__ exit codes 4/5/6/7."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def _run_main(env: dict, args: list[str] | None = None) -> int:
    args = args or []
    proc = subprocess.run(
        [sys.executable, "-m", "plaudsync", *args],
        env={**env},
        capture_output=True,
        text=True,
    )
    return proc.returncode


def test_main_exit_7_on_missing_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No config.yaml in STATE_ROOT → ConfigValidationError → exit 7."""
    env = {
        "PLAUDSYNC_STATE_ROOT": str(tmp_path),
        "PLAUD_API_TOKEN": "test-token",
        "PLAUDSYNC_TRIGGER": "manual",
        "PATH": __import__("os").environ.get("PATH", ""),
        "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
    }
    code = _run_main(env)
    assert code == 7


def test_main_exit_5_when_lock_held(tmp_path: Path) -> None:
    """Holding the sync.lock externally → second run exits 5."""
    from plaudsync.locking import SyncLock

    # Setup minimal config
    unclassified = tmp_path / "U"
    unclassified.mkdir()
    (tmp_path / "config.yaml").write_text(
        f"unclassified_dir: {unclassified}\nprojects: {{}}\n", encoding="utf-8"
    )

    lock_path = tmp_path / ".plaudsync" / "sync.lock"
    with SyncLock(lock_path):
        env = {
            "PLAUDSYNC_STATE_ROOT": str(tmp_path),
            "PLAUD_API_TOKEN": "test-token",
            "PLAUDSYNC_TRIGGER": "manual",
            "PATH": __import__("os").environ.get("PATH", ""),
            "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
        }
        code = _run_main(env)
    assert code == 5
