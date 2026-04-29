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


_BL4_BUSINESS_KEYS = (
    "headline",
    "category",
    "original_category",
    "industry_category",
    "recommend_questions",
    "data_content",
    "data_link",
)
_BL4_BUSINESS_RE = re.compile(
    r'"(?P<key>' + "|".join(_BL4_BUSINESS_KEYS) + r')"\s*:\s*'
    r'(?P<val>"[^"\\]*(?:\\.[^"\\]*)*"|\[[^\]]*\])'
)


def _scrub_bl4_business_fields(body_str: str | bytes) -> str | bytes:
    """Replace BL-4 business content + signed URL values with placeholders.

    Targets fields documented in
    docs/superpowers/specs/2026-04-29-bl4-bl-x-content-classifier-design.md §7
    as 'NEVER expose'. Cassettes for BL-4/BL-X integration tests rely on this
    being run automatically during record (via before_record_response).
    """
    was_bytes = isinstance(body_str, bytes)
    text = body_str.decode("utf-8", errors="replace") if was_bytes else body_str

    def _replace(match: re.Match[str]) -> str:
        key = match.group("key")
        val = match.group("val")
        if val.startswith("["):
            return f'"{key}": []'
        return f'"{key}": "<redacted-bl4>"'

    text = _BL4_BUSINESS_RE.sub(_replace, text)
    return text.encode("utf-8") if was_bytes else text


def _scrub_embeddings(body_str: str | bytes) -> str | bytes:
    """Replace voice embedding float arrays with empty list (voice biometric PII).

    Plaud /file/detail/{id} returns embeddings: {Speaker N: [256 floats]}.
    Preserve the dict structure (keys matter for speakers_count) but null
    the float vectors.
    """
    was_bytes = isinstance(body_str, bytes)
    text = body_str.decode("utf-8", errors="replace") if was_bytes else body_str
    # Greedy match for "Speaker N": [...] arrays inside embeddings
    text = re.sub(
        r'("Speaker [^"]+"\s*:\s*)\[[^\]]*\]',
        r'\1[]',
        text,
    )
    return text.encode("utf-8") if was_bytes else text


def _redact_response(response: dict[str, Any]) -> dict[str, Any]:
    """Strip or truncate fields that commonly leak PII in API responses.

    Layered scrubbing (apply order matters):
    1. Auth/cookie headers → <redacted>
    2. JSON: title-ish keys → <redacted-title>
    3. JSON: BL-4 business keys (headline, category, recommend_questions,
       data_content, data_link) → <redacted-bl4>
    4. JSON: embeddings Speaker N float vectors → []
    5. Audio bodies > 1024 bytes → truncated

    When `cassette-refresh` skill audits a cassette and finds unscrubbed
    novel keys, extend this function and re-record. Do not loosen elsewhere.
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
            body["string"] = _scrub_bl4_business_fields(body["string"])
            body["string"] = _scrub_embeddings(body["string"])
        elif "audio" in ct.lower() and len(body["string"]) > 1024:
            raw = body["string"]
            if isinstance(raw, bytes):
                body["string"] = raw[:1024] + b"<truncated>"
            else:
                body["string"] = raw[:1024] + "<truncated>"
        else:
            # Plaud content_list signed S3 URLs return text/plain (transcript,
            # outline, summary). Truncate aggressively + placeholder marker.
            raw = body["string"]
            if isinstance(raw, bytes):
                if len(raw) > 64:
                    body["string"] = b"<redacted-content>"
            else:
                if len(raw) > 64:
                    body["string"] = "<redacted-content>"
    return response
