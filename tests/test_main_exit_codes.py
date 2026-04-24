"""Integration tests for __main__.main() exit-code contract."""
from __future__ import annotations

import pytest

from plaudsync import __main__ as entrypoint
from plaudsync.auth import PlaudTokenExpired
from plaudsync.plaud_client import PlaudClient


def test_main_exits_2_on_token_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAUD_API_TOKEN", "whatever")
    monkeypatch.setenv("SENTRY_DSN", "")  # disable Sentry for the test

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

    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()
    assert exc_info.value.code == 3
