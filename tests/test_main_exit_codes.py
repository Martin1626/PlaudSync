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

    monkeypatch.setattr(PlaudClient, "verify", _raise_expired)

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

    def _ok(self: PlaudClient) -> None:  # type: ignore[unused-argument]
        return None

    monkeypatch.setattr(PlaudClient, "verify", _ok)

    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()
    assert exc_info.value.code == 0


def test_verify_subcommand_exits_2_on_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAUD_API_TOKEN", "whatever")
    monkeypatch.setenv("SENTRY_DSN", "")
    monkeypatch.setattr("sys.argv", ["plaudsync", "verify"])

    def _raise_expired(self: PlaudClient) -> None:  # type: ignore[unused-argument]
        raise PlaudTokenExpired("Plaud API rejected token")

    monkeypatch.setattr(PlaudClient, "verify", _raise_expired)

    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()
    assert exc_info.value.code == 2
