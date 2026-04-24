"""Shared pytest configuration.

- ``pytest-recording`` cassette scrubbing filters (auth headers, query params).
- VCR default cassette library dir at ``tests/cassettes``.
- Integration tests opt-in to the real network via ``@pytest.mark.vcr(...)``;
  everything else is blocked by ``addopts = --block-network`` in pyproject.toml.
"""
from __future__ import annotations

from typing import Any

import pytest


# ---------------------------------------------------------------------------
# pytest-recording configuration
# ---------------------------------------------------------------------------
# Docs: https://github.com/kiwicom/pytest-recording


@pytest.fixture(scope="session")
def vcr_config() -> dict[str, Any]:
    """Global VCR defaults. Override per-test via @pytest.mark.vcr(**overrides)."""
    return {
        "cassette_library_dir": "tests/cassettes",
        "record_mode": "none",  # default is replay; CLI --record-mode=new_episodes overrides
        "match_on": ("method", "scheme", "host", "path", "query"),
        "filter_headers": [
            ("authorization", "<redacted>"),
            ("x-api-key", "<redacted>"),
            ("x-auth-token", "<redacted>"),
            ("cookie", "<redacted>"),
            ("set-cookie", "<redacted>"),
            ("proxy-authorization", "<redacted>"),
        ],
        "filter_query_parameters": [
            ("access_token", "<redacted>"),
            ("token", "<redacted>"),
            ("api_key", "<redacted>"),
            ("client_secret", "<redacted>"),
        ],
        "filter_post_data_parameters": [
            ("client_secret", "<redacted>"),
            ("refresh_token", "<redacted>"),
            ("password", "<redacted>"),
        ],
        "before_record_response": _redact_response,
    }


def _redact_response(response: dict[str, Any]) -> dict[str, Any]:
    """Strip or truncate fields that commonly leak PII in API responses.

    This is a first pass. When `cassette-refresh` skill audits a cassette and
    finds unscrubbed names / emails / meeting titles, extend this function and
    re-record. Do not loosen it to hide a leak elsewhere.
    """
    headers = response.get("headers") or {}
    for name in ("Set-Cookie", "set-cookie", "Authorization", "authorization"):
        if name in headers:
            headers[name] = ["<redacted>"]
    # Body truncation / scrubbing happens per-endpoint as needed; keep a hook here.
    return response
