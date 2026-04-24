"""Plaud API authentication — token loading and exception taxonomy.

Usage:
    from plaudsync.auth import load_token, PlaudTokenMissing, PlaudTokenExpired
    token = load_token()                   # raises PlaudTokenMissing if unset/empty

See docs/superpowers/specs/2026-04-24-plaud-auth-design.md for rationale.
"""
from __future__ import annotations


class PlaudTokenMissing(Exception):
    """PLAUD_API_TOKEN env var is unset, empty, or whitespace-only."""


class PlaudTokenExpired(Exception):
    """Plaud API rejected the current token (HTTP 401)."""
