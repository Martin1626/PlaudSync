"""VCR cassette tests for PlaudClient.list_recordings."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from plaudsync.plaud_client import PlaudClient


@pytest.mark.vcr(cassette_library_dir="tests/cassettes/test_plaud_client_listing")
def test_paginate_two_pages() -> None:
    with PlaudClient("test-token") as client:
        ids = [m.plaud_id for m in client.list_recordings(since=None)]
    assert ids == ["a", "b", "c"]


@pytest.mark.vcr(cassette_library_dir="tests/cassettes/test_plaud_client_listing")
def test_since_filter_stops_early() -> None:
    # since timestamp = 1700000007 seconds → 1700000007000 ms
    since = datetime.fromtimestamp(1700000007, tz=timezone.utc).isoformat()
    with PlaudClient("test-token") as client:
        ids = [m.plaud_id for m in client.list_recordings(since=since)]
    assert ids == ["new1", "new2"]   # 'old1' is older than `since` → iterator stops
