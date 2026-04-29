"""PlaudClient default headers — required by /filetag/ + future endpoints.

Spike (scripts/spike_bl_x_folders.py) confirmed Plaud rejects /filetag/ when
app-platform: web header is missing. Inject these as session defaults so
all endpoints get them.
"""
from __future__ import annotations

from unittest.mock import patch

from plaudsync.plaud_client import PlaudClient


def _no_probe(self) -> None:
    """Skip _region_probe network call for this unit test."""
    return None


def test_plaud_client_sets_app_platform_and_edit_from_headers() -> None:
    with patch.object(PlaudClient, "_region_probe", _no_probe):
        client = PlaudClient("fake-token")
    assert client._session.headers.get("app-platform") == "web"
    assert client._session.headers.get("edit-from") == "web"


def test_plaud_client_preserves_authorization_header() -> None:
    with patch.object(PlaudClient, "_region_probe", _no_probe):
        client = PlaudClient("fake-token")
    assert client._session.headers.get("Authorization") == "Bearer fake-token"
