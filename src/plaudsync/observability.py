"""Sentry ``before_send`` callback that scrubs PII from events before they leave the host.

Rationale (průzkum kolo 4, DA bod #1): PlaudSync handles meeting recordings and
project-category labels. Default Sentry payloads include file paths, exception
messages, breadcrumbs, and request contexts — any of which may carry business
content. Kill criterion L-18 fires if unscrubbed data reaches Sentry UI.

Scrubbing strategy:
- Replace absolute filesystem paths (Windows + POSIX) with ``<path>``.
- Replace filenames with recognizable recording extensions (mp3/m4a/wav/flac) with ``<recording>``.
- Replace any ``category`` or ``project`` value in extra/contexts with ``<redacted-label>``.
- Leave exception types and stack frame structure intact so root-causing still works.

This is the first pass. If a post-deploy Sentry audit still finds leaks, tighten
the patterns here rather than loosening privacy config in ``__main__._configure_sentry``.
"""
from __future__ import annotations

import os
import re
from typing import Any

# Absolute path regex matches Windows (C:\\...) and POSIX (/...) paths that
# contain at least one separator after the root. Conservative by design: prefers
# over-scrubbing to under-scrubbing.
_WIN_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s\"'<>|*?]+")
_POSIX_PATH_RE = re.compile(r"(?:/[^\s/\"'<>|*?]+){2,}")

# Recording filenames are scrubbed wholesale (filename itself often carries
# project name or meeting title, per SPEC.md local layout).
_RECORDING_FILE_RE = re.compile(r"[\w\-. ]+\.(?:mp3|m4a|wav|flac|ogg|opus)", re.IGNORECASE)

# Keys whose values are known to contain business labels.
_REDACTED_KEYS = frozenset(
    {
        "category",
        "categories",
        "project",
        "project_name",
        "project_id",
        "meeting_title",
        "title",
        "recording_title",
        "transcript_excerpt",
        "participants",
        "attendees",
    }
)

# Scrubs inline label patterns inside free-text strings (exception messages,
# log lines). Matches `<key>=<value>` or `<key>: <value>` where <key> is one
# of the known label keys. Necessary because exception messages built with
# f-strings often inline business labels — see kill criterion L-18 partial
# leak observed 2026-04-24 (smoke test event PLAUDSYNC-1).
_INLINE_LABEL_RE = re.compile(
    r"\b(" + "|".join(sorted(_REDACTED_KEYS)) + r")(\s*[=:]\s*)([^\s,;)\"'\]]+)",
    re.IGNORECASE,
)

# Bearer-token pattern — redact anywhere it appears in strings (Authorization
# headers, log lines, exception messages). Added for the auth feature.
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE)


def _scrub_string(value: str) -> str:
    value = _WIN_PATH_RE.sub("<path>", value)
    value = _POSIX_PATH_RE.sub("<path>", value)
    value = _RECORDING_FILE_RE.sub("<recording>", value)
    value = _INLINE_LABEL_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}<redacted-label>", value
    )
    value = _BEARER_RE.sub("Bearer [REDACTED]", value)
    # Exact-value redaction — catches the token in URLs, query strings, log lines.
    plaud_token = os.getenv("PLAUD_API_TOKEN", "").strip()
    if plaud_token:
        value = value.replace(plaud_token, "[REDACTED]")
    return value


def _scrub_mapping(obj: dict[str, Any]) -> dict[str, Any]:
    scrubbed: dict[str, Any] = {}
    for key, value in obj.items():
        if key in _REDACTED_KEYS:
            scrubbed[key] = "<redacted-label>"
        else:
            scrubbed[key] = _scrub_value(value)
    return scrubbed


def _scrub_value(value: Any) -> Any:
    if isinstance(value, str):
        return _scrub_string(value)
    if isinstance(value, dict):
        return _scrub_mapping(value)
    if isinstance(value, list):
        return [_scrub_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_value(item) for item in value)
    return value


def scrub_event(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Sentry ``before_send`` hook. Returns scrubbed event or ``None`` to drop."""
    del hint  # not used; kept for Sentry API contract.
    return _scrub_mapping(event)
