"""Shared pytest configuration.

- ``pytest-recording`` cassette scrubbing filters (auth headers, query params).
- VCR default cassette library dir at ``tests/cassettes``.
- Integration tests opt-in to the real network via ``@pytest.mark.vcr(...)``;
  everything else is blocked by ``addopts = --block-network`` in pyproject.toml.
- Record mode defaults to ``none`` (replay-only). To re-record cassettes set
  ``VCR_RECORD_MODE=once`` (or ``new_episodes``) in the env for one run.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Title / filename scrubber for cassette bodies
# ---------------------------------------------------------------------------

_TITLE_KEYS = ("file_name", "filename", "title", "recording_title")
_TITLE_RE = re.compile(
    r'"(?P<key>' + "|".join(_TITLE_KEYS) + r')"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"'
)


def _scrub_titles_in_body(body_str: str | bytes) -> str | bytes:
    """Replace title-ish JSON values with <redacted-title> sentinel.

    Cassette files commit-friendly: any real recording title from a
    re-record run gets normalized.  Handles both str and bytes bodies
    (VCR.py delivers bytes during replay from YAML cassettes).
    """
    was_bytes = isinstance(body_str, bytes)
    text = body_str.decode("utf-8", errors="replace") if was_bytes else body_str

    def _replace(match: re.Match[str]) -> str:
        return f'"{match.group("key")}": "<redacted-title>"'

    result = _TITLE_RE.sub(_replace, text)
    return result.encode("utf-8") if was_bytes else result


# ---------------------------------------------------------------------------
# pytest-recording configuration
# ---------------------------------------------------------------------------
# Docs: https://github.com/kiwicom/pytest-recording


@pytest.fixture(scope="session")
def vcr_config() -> dict[str, Any]:
    """Global VCR defaults. Override per-test via @pytest.mark.vcr(**overrides)."""
    return {
        "cassette_library_dir": "tests/cassettes",
        "record_mode": os.getenv("VCR_RECORD_MODE", "none"),  # replay-only by default
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
    body = response.get("body") or {}
    if "string" in body and "Content-Type" in (response.get("headers") or {}):
        ct = (response["headers"].get("Content-Type") or [""])[0]
        if "json" in ct.lower():
            body["string"] = _scrub_titles_in_body(body["string"])
        elif "audio" in ct.lower() and len(body["string"]) > 1024:
            raw = body["string"]
            if isinstance(raw, bytes):
                body["string"] = raw[:1024] + b"<truncated>"
            else:
                body["string"] = raw[:1024] + "<truncated>"
    return response
