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
