"""Cassette test for PlaudClient.fetch_filetags() — BL-X folder catalog.

To re-record:
    VCR_RECORD_MODE=once pytest tests/integration/test_fetch_filetags.py

Cassette is auto-scrubbed via tests/conftest.py for:
- Authorization header → <redacted>
- aiContentHeader business keys → <redacted-bl4>
- Voice embeddings → []
- Set-Cookie → <redacted>

Manual scrub pass after record (cassette-refresh skill):
- Replace `id: <real 32-hex>` with `id: <FOLDER_ID_N>` (consistent across file)
- Replace `name: <real folder name>` with `name: <NAME_N>`
"""
from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from plaudsync.auth import load_token
from plaudsync.plaud_client import FolderCatalogItem, PlaudClient


def _token() -> str:
    """Load token from .env when recording; cassette ignores Authorization
    on replay since match_on excludes headers."""
    load_dotenv()
    if os.getenv("VCR_RECORD_MODE"):
        return load_token()
    return "test-token"


@pytest.mark.vcr(cassette_library_dir="tests/cassettes/test_fetch_filetags")
def test_fetch_filetags_returns_catalog() -> None:
    with PlaudClient(_token()) as client:
        folders = client.fetch_filetags()

    assert len(folders) >= 1
    assert all(isinstance(f, FolderCatalogItem) for f in folders)
    first = folders[0]
    assert len(first.id) == 32
    assert isinstance(first.name, str) and first.name
