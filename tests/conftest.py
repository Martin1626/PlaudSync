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
        "before_record_request": _redact_request,
        "before_record_response": _redact_response,
    }


# ---------------------------------------------------------------------------
# Request scrubbing
# ---------------------------------------------------------------------------

_MAX_REQUEST_BODY = 200
# Signed content URLs (S3 presigned / CloudFront) carry credentials in the
# query. Request and data_link share this placeholder so replay still matches.
CONTENT_URL_PLACEHOLDER = "https://plaud-content.invalid/redacted"
_SIGNED_QUERY_RE = re.compile(r"(?i)[?&](x-amz-[a-z-]+|signature|key-pair-id|expires)=")


def _is_plaud_host(host: str) -> bool:
    return host == "plaud.ai" or host.endswith(".plaud.ai")


def _redact_request(request: Any) -> Any:
    """Write payloads carry full transcripts / summaries — never record them.

    VCR deep-copies the request before this runs, so the live request is not
    affected. Also applied to incoming requests during replay (matching).
    """
    body = request.body
    if body is not None and len(body) > _MAX_REQUEST_BODY:
        request.body = b"<redacted-request-body>"
        # VCR re-runs the filter chain on already-filtered requests while
        # matching; filter_post_data_parameters would json.loads the
        # placeholder of a JSON POST and crash before the request is sent.
        request.headers["Content-Type"] = "application/octet-stream"
    if not _is_plaud_host(request.host or "") and _SIGNED_QUERY_RE.search(request.uri):
        request.uri = CONTENT_URL_PLACEHOLDER
    return request


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
        if key == "data_link":
            # Empty link = not ready; keep. Otherwise a placeholder URL equal to
            # the redacted request URI, so replayed downloads still match.
            return f'"{key}": ""' if val == '""' else f'"{key}": "{CONTENT_URL_PLACEHOLDER}"'
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


_DEFAULT_SPEAKER_RE = re.compile(r"^Speaker \d+$|^PlaudSync Test")
_SPEAKER_KEYS = ("speaker", "original_speaker")
# Full summary / outline text on the /file/list row.
_TEXT_KEYS = ("ai_content", "overview")
_LIST_KEYS = ("outline_result",)


def _scrub_segment(seg: dict) -> None:
    if "content" in seg:
        seg["content"] = "<redacted>"
    for key in _SPEAKER_KEYS:
        value = seg.get(key)
        if isinstance(value, str) and not _DEFAULT_SPEAKER_RE.match(value):
            seg[key] = "<redacted-name>"


def _walk_segments(node: Any, in_trans_result: bool = False) -> int:
    """Scrub transcript segments anywhere in a JSON tree; return how many.

    A segment is any item of a ``trans_result`` list or any dict carrying a
    speaker key (S3 transcript sources are top-level segment lists).
    """
    found = 0
    if isinstance(node, list):
        for item in node:
            found += _walk_segments(item, in_trans_result)
    elif isinstance(node, dict):
        if in_trans_result or any(k in node for k in _SPEAKER_KEYS):
            _scrub_segment(node)
            found += 1
        for key, value in node.items():
            if key in _TEXT_KEYS and isinstance(value, str):
                node[key] = "<redacted>"
            elif key in _LIST_KEYS and isinstance(value, list):
                node[key] = []
            else:
                found += _walk_segments(value, key == "trans_result")
    return found


def _scrub_json_segments(body: str | bytes) -> tuple[str | bytes, int]:
    was_bytes = isinstance(body, bytes)
    try:
        data = json.loads(body)
    except ValueError:
        return body, 0
    before = json.dumps(data, ensure_ascii=False, sort_keys=True)
    found = _walk_segments(data)
    if json.dumps(data, ensure_ascii=False, sort_keys=True) == before:
        return body, found
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return (text.encode("utf-8") if was_bytes else text), found


def _scrub_trans_result(body: str | bytes) -> str | bytes:
    """Segment content -> <redacted>; non-default speaker names -> <redacted-name>.

    Also drops summary/outline text (ai_content, outline_result) that ride
    along on the /file/list row.
    """
    return _scrub_json_segments(body)[0]


def _header(headers: dict, name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return (value or [""])[0] if isinstance(value, list) else str(value)
    return ""


def _redact_response(response: dict[str, Any]) -> dict[str, Any]:
    """Strip or truncate fields that commonly leak PII in API responses.

    Layered scrubbing (apply order matters):
    1. Auth/cookie headers → <redacted>
    2. JSON: title-ish keys → <redacted-title>
    3. JSON: BL-4 business keys (headline, category, recommend_questions,
       data_content) → <redacted-bl4>; data_link → CONTENT_URL_PLACEHOLDER
    4. JSON: embeddings Speaker N float vectors → []
    5. JSON: transcript segments (content, real speaker names) + summary/outline
       text → placeholders (_scrub_trans_result)
    6. Audio bodies > 1024 bytes → truncated
    7. Other bodies: a JSON segment list (S3 transcript source, any
       content-type) is scrubbed but kept parseable; anything else > 64
       bytes → <redacted-content>

    When `cassette-refresh` skill audits a cassette and finds unscrubbed
    novel keys, extend this function and re-record. Do not loosen elsewhere.
    """
    headers = response.get("headers") or {}
    for name in ("Set-Cookie", "set-cookie", "Authorization", "authorization"):
        if name in headers:
            headers[name] = ["<redacted>"]
    body = response.get("body") or {}
    if "string" in body:
        ct = _header(headers, "Content-Type").lower()
        if "json" in ct:
            body["string"] = _scrub_titles_in_body(body["string"])
            body["string"] = _scrub_bl4_business_fields(body["string"])
            body["string"] = _scrub_embeddings(body["string"])
            body["string"] = _scrub_trans_result(body["string"])
        elif "audio" in ct and len(body["string"]) > 1024:
            raw = body["string"]
            if isinstance(raw, bytes):
                body["string"] = raw[:1024] + b"<truncated>"
            else:
                body["string"] = raw[:1024] + "<truncated>"
        else:
            # Plaud content_list signed S3 URLs return text/plain (transcript,
            # outline, summary). Transcript segment lists stay JSON (scrubbed)
            # so replay can parse them; everything else → placeholder.
            raw = body["string"]
            scrubbed, segments = _scrub_json_segments(raw)
            if segments:
                body["string"] = scrubbed
            elif isinstance(raw, bytes):
                if len(raw) > 64:
                    body["string"] = b"<redacted-content>"
            else:
                if len(raw) > 64:
                    body["string"] = "<redacted-content>"
    return response
