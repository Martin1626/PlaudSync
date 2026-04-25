"""Unit tests for plaudsync.ui.sync_starter — mocks subprocess.Popen."""
from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

from plaudsync.state import _SCHEMA  # type: ignore[attr-defined]
from plaudsync.ui import sync_starter


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.executescript(_SCHEMA)
    c.commit()
    return c


class _FakePopen:
    """Mock subprocess.Popen with controllable wait()."""

    def __init__(self, returncode_or_timeout, captured_env: dict | None = None):
        self._control = returncode_or_timeout
        self.returncode = returncode_or_timeout if isinstance(returncode_or_timeout, int) else None
        self.captured_env = captured_env

    def wait(self, timeout: float | None = None) -> int:
        if self._control is subprocess.TimeoutExpired:
            raise subprocess.TimeoutExpired(cmd="x", timeout=timeout or 0)
        return self._control  # type: ignore[return-value]


def test_spawn_sets_trigger_env_var(tmp_path: Path, conn: sqlite3.Connection,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_popen(*args, **kwargs):
        captured["env"] = kwargs.get("env")
        return _FakePopen(subprocess.TimeoutExpired)

    monkeypatch.setattr(sync_starter.subprocess, "Popen", fake_popen)

    sync_starter.start_sync_subprocess(tmp_path, conn)

    assert captured["env"]["PLAUDSYNC_TRIGGER"] == "ui_sync_now"
    assert captured["env"]["PLAUDSYNC_STATE_ROOT"] == str(tmp_path)


def test_returns_202_when_subprocess_running_after_500ms(
    tmp_path: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync_starter.subprocess, "Popen",
                        lambda *a, **k: _FakePopen(subprocess.TimeoutExpired))

    result = sync_starter.start_sync_subprocess(tmp_path, conn)

    assert result["kind"] == "started"
    assert "sync_id" in result
    assert "started_at" in result


def test_returns_409_when_subprocess_exits_5(
    tmp_path: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Seed an unfinished sync_runs row so the 409 detail can read started_at + trigger
    conn.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        ("2026-04-25T13:00:00+00:00", "task_scheduler"),
    )
    conn.commit()

    monkeypatch.setattr(sync_starter.subprocess, "Popen",
                        lambda *a, **k: _FakePopen(5))

    result = sync_starter.start_sync_subprocess(tmp_path, conn)

    assert result["kind"] == "conflict"
    assert result["reason"] == "already_running"
    assert result["started_at"] == "2026-04-25T13:00:00+00:00"
    assert result["by"] == "task_scheduler"


def test_returns_spawn_failed_for_other_exit_codes(
    tmp_path: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync_starter.subprocess, "Popen",
                        lambda *a, **k: _FakePopen(7))

    result = sync_starter.start_sync_subprocess(tmp_path, conn)

    assert result["kind"] == "spawn_failed"
    assert result["exit_code"] == 7
