"""Integration tests for PlaudClient (auth-layer scope).

Uses VCR cassettes recorded against the real Plaud API. First run with
``VCR_RECORD_MODE=once`` to produce the cassette; subsequent runs replay
offline. Auth header is scrubbed before save (see tests/conftest.py).
"""
from __future__ import annotations

import os

import pytest

from plaudsync.auth import PlaudTokenExpired
from plaudsync.plaud_client import PlaudClient


@pytest.mark.vcr
def test_verify_expired_raises_PlaudTokenExpired() -> None:
    client = PlaudClient(token="test-token-invalid-abc123")
    try:
        with pytest.raises(PlaudTokenExpired) as exc_info:
            client.verify()
        assert "Plaud API rejected token" in str(exc_info.value)
    finally:
        client.close()


@pytest.mark.vcr
def test_verify_success() -> None:
    # Recording mode needs a real token from .env (run load_dotenv).
    # Replay mode ignores the token — cassette auth header is scrubbed.
    from dotenv import load_dotenv

    load_dotenv()
    token = os.environ.get("PLAUD_API_TOKEN") or "replay-only-fake-token"
    client = PlaudClient(token=token)
    try:
        result = client.verify()
        assert result is None
    finally:
        client.close()
