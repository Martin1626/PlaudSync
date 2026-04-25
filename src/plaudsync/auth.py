"""Plaud API authentication — token loading and exception taxonomy.

Usage:
    from plaudsync.auth import load_token, PlaudTokenMissing, PlaudTokenExpired
    token = load_token()                   # raises PlaudTokenMissing if unset/empty

See docs/superpowers/specs/2026-04-24-plaud-auth-design.md for rationale.
"""
from __future__ import annotations

import os


class PlaudTokenMissing(Exception):
    """PLAUD_API_TOKEN env var is unset, empty, or whitespace-only."""


class PlaudTokenExpired(Exception):
    """Plaud API rejected the current token (HTTP 401)."""


def load_token() -> str:
    """Read PLAUD_API_TOKEN from env; strip whitespace; raise if missing/empty.

    Call ``dotenv.load_dotenv()`` before this (done in __main__.main()).
    """
    raw = os.getenv("PLAUD_API_TOKEN", "")
    token = raw.strip()
    if not token:
        raise PlaudTokenMissing(
            "PLAUD_API_TOKEN not set in .env — see README setup section"
        )
    return token


def mask_token(token: str) -> str:
    """Render a UI-safe mask of a Plaud API token.

    Format: first 8 chars + 15 bullets + last 4 chars (27 visible chars).
    Tokens shorter than 12 chars (cannot guarantee no overlap) get a flat
    20-bullet placeholder.

    JWT header bytes (eyJhbGci...) are public boilerplate, so leaking the
    first 8 chars + last 4 chars is acceptable per Settings spec Gap 2
    (Option A) threat model.
    """
    if len(token) < 12:
        return "•" * 20
    return token[:8] + "•" * 15 + token[-4:]
