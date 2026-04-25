"""VCR cassette tests for PlaudClient.download_audio."""
from __future__ import annotations

import pytest

from plaudsync.plaud_client import PlaudClient


@pytest.mark.vcr(cassette_library_dir="tests/cassettes/test_plaud_client_download")
def test_streamed_audio_yields_chunks() -> None:
    with PlaudClient("test-token") as client:
        chunks = list(client.download_audio("rec_abc"))
    body = b"".join(chunks)
    assert body == b"AAAABBBBCCCCDDDD<truncated_audio>"
    assert len(body) == 33


@pytest.mark.vcr(cassette_library_dir="tests/cassettes/test_plaud_client_download")
def test_download_returns_size() -> None:
    """download_audio yields chunks; caller verifies size against metadata."""
    with PlaudClient("test-token") as client:
        # Spec: download_audio is a streaming iterator; size verification
        # happens in sync.py based on RecordingMeta.file_size.
        chunks = list(client.download_audio("rec_xyz"))
    assert b"".join(chunks) == b"short"
