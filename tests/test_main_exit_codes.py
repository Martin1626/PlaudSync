"""Integration tests for __main__.main() exit-code contract."""
from __future__ import annotations

import pytest

from plaudsync import __main__ as entrypoint
from plaudsync.auth import PlaudTokenExpired
from plaudsync.plaud_client import PlaudClient


def test_main_exits_2_on_token_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAUD_API_TOKEN", "whatever")
    monkeypatch.setenv("SENTRY_DSN", "")  # disable Sentry for the test
    monkeypatch.setattr("sys.argv", ["plaudsync"])  # default sync invocation

    def _raise_expired(self: PlaudClient) -> None:  # type: ignore[unused-argument]
        raise PlaudTokenExpired(
            "Plaud API rejected token - re-paste from browser localStorage.tokenstr"
        )

    # Patch _region_probe so __init__ raises before verify() is called.
    monkeypatch.setattr(PlaudClient, "_region_probe", _raise_expired)

    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()
    assert exc_info.value.code == 2


def test_main_exits_3_on_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLAUD_API_TOKEN", raising=False)
    monkeypatch.setenv("SENTRY_DSN", "")
    monkeypatch.setattr("sys.argv", ["plaudsync"])
    # Prevent main() from re-populating PLAUD_API_TOKEN via .env during the test.
    monkeypatch.setattr("plaudsync.__main__.load_dotenv", lambda: None)

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
