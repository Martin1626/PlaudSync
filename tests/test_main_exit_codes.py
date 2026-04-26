"""Integration tests for __main__.main() exit-code contract."""
from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plaudsync import __main__ as entrypoint
from plaudsync.auth import PlaudTokenExpired
from plaudsync.config import Config
from plaudsync.plaud_client import PlaudClient


def _setup_sync_pipeline_mocks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Patch config loading, locking, and state so pipeline proceeds to token/client step."""
    unclassified = tmp_path / "U"
    unclassified.mkdir()
    valid_config = Config(unclassified_dir=unclassified, projects={})

    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr("plaudsync.config.load_config", lambda _root: valid_config)

    # Patch SyncLock to a no-op context manager so lock acquisition is skipped.
    @contextlib.contextmanager  # type: ignore[misc]
    def _noop_lock(_path: Path):  # type: ignore[no-untyped-def]
        yield

    monkeypatch.setattr("plaudsync.locking.SyncLock", _noop_lock)

    # Patch open_state to return a throwaway in-memory SQLite connection
    # WITH schema bootstrap so it mirrors production contract (real open_state
    # runs CREATE IF NOT EXISTS). Schedule gating peek queries sync_runs and
    # would raise OperationalError on a bare :memory: db.
    def _open_state_mock(_root: Path) -> sqlite3.Connection:
        from plaudsync.state import _SCHEMA  # noqa: PLC0415
        conn = sqlite3.connect(":memory:")
        conn.executescript(_SCHEMA)
        return conn

    monkeypatch.setattr("plaudsync.state.open_state", _open_state_mock)


def test_main_exits_2_on_token_expired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLAUD_API_TOKEN", "whatever")
    monkeypatch.setenv("SENTRY_DSN", "")  # disable Sentry for the test
    monkeypatch.setattr("sys.argv", ["plaudsync"])  # default sync invocation
    _setup_sync_pipeline_mocks(monkeypatch, tmp_path)

    def _raise_expired(self: PlaudClient) -> None:  # type: ignore[unused-argument]
        raise PlaudTokenExpired(
            "Plaud API rejected token - re-paste from browser localStorage.tokenstr"
        )

    # Patch _region_probe so __init__ raises before any network call.
    monkeypatch.setattr(PlaudClient, "_region_probe", _raise_expired)

    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()
    assert exc_info.value.code == 2


def test_main_exits_3_on_token_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PLAUD_API_TOKEN", raising=False)
    monkeypatch.setenv("SENTRY_DSN", "")
    monkeypatch.setattr("sys.argv", ["plaudsync"])
    # Prevent main() from re-populating PLAUD_API_TOKEN via .env during the test.
    monkeypatch.setattr("plaudsync.__main__.load_dotenv", lambda: None)
    _setup_sync_pipeline_mocks(monkeypatch, tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()
    assert exc_info.value.code == 3


def test_verify_subcommand_exits_0_on_valid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAUD_API_TOKEN", "whatever")
    monkeypatch.setenv("SENTRY_DSN", "")
    monkeypatch.setattr("sys.argv", ["plaudsync", "verify"])

    # Patch _region_probe (called by __init__ and verify) to be a no-op.
    monkeypatch.setattr(PlaudClient, "_region_probe", lambda self: None)
    monkeypatch.setattr(PlaudClient, "verify", lambda self: None)

    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()
    assert exc_info.value.code == 0


def test_verify_subcommand_exits_2_on_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAUD_API_TOKEN", "whatever")
    monkeypatch.setenv("SENTRY_DSN", "")
    monkeypatch.setattr("sys.argv", ["plaudsync", "verify"])

    def _raise_expired(self: PlaudClient) -> None:  # type: ignore[unused-argument]
        raise PlaudTokenExpired("Plaud API rejected token")

    # Patch _region_probe: __init__ calls it first; if it raises, construction
    # aborts and verify() is never reached. Either way exit code 2 is returned.
    monkeypatch.setattr(PlaudClient, "_region_probe", _raise_expired)

    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()
    assert exc_info.value.code == 2
