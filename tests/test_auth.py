"""Unit tests for plaudsync.auth — token loading and exceptions."""
from __future__ import annotations

import pytest

from plaudsync.auth import PlaudTokenMissing, load_token
from plaudsync.observability import scrub_event


def test_load_token_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLAUD_API_TOKEN", raising=False)
    with pytest.raises(PlaudTokenMissing) as exc_info:
        load_token()
    assert "PLAUD_API_TOKEN" in str(exc_info.value)


def test_load_token_empty_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAUD_API_TOKEN", "   ")
    with pytest.raises(PlaudTokenMissing):
        load_token()


def test_load_token_success_returns_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAUD_API_TOKEN", "test-token-abc123")
    assert load_token() == "test-token-abc123"


def test_scrub_event_redacts_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAUD_API_TOKEN", "secret-xyz-12345")
    event = {
        "message": "request failed with Authorization: Bearer secret-xyz-12345",
        "extra": {"token_preview": "secret-xyz-12345-more"},
    }
    scrubbed = scrub_event(event, hint={})
    assert scrubbed is not None
    assert "secret-xyz-12345" not in scrubbed["message"]
    assert "Bearer [REDACTED]" in scrubbed["message"]
    assert "secret-xyz-12345" not in scrubbed["extra"]["token_preview"]
