"""Cassette test for PlaudClient.fetch_detail() — BL-4 content_list shape.

The test calls list_recordings first to obtain a recording ID, then
fetch_detail for that recording. Both requests live in the same cassette.

To re-record:
    VCR_RECORD_MODE=once pytest tests/integration/test_fetch_detail.py

Auto-scrubbed (conftest.py): Authorization, aiContentHeader keys, embeddings,
data_link, data_content, Set-Cookie.

Manual scrub pass:
- Replace recording IDs in URL path (`/file/detail/<32-hex>`) and body with
  placeholder `<REC_ID_N>` (must match across request URL + response body)
- Replace any remaining titles / serial_numbers / file_md5 if surfaced
"""
from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from plaudsync.auth import load_token
from plaudsync.plaud_client import ContentItem, DetailMeta, PlaudClient


def _token() -> str:
    load_dotenv()
    if os.getenv("VCR_RECORD_MODE"):
        return load_token()
    return "test-token"


@pytest.mark.vcr(cassette_library_dir="tests/cassettes/test_fetch_detail")
def test_fetch_detail_typed_projection() -> None:
    with PlaudClient(_token()) as client:
        # Take the first recording from the listing to drive fetch_detail.
        meta = next(iter(client.list_recordings(since=None)))
        detail = client.fetch_detail(meta.plaud_id)

    assert isinstance(detail, DetailMeta)
    assert detail.plaud_id == meta.plaud_id
    # language is 2-char ISO code on full Plaud accounts; tolerate empty for
    # very short recordings that bypass transcription.
    assert isinstance(detail.language, str)
    assert detail.speakers_count >= 0
    assert isinstance(detail.task_ids, dict)
    assert isinstance(detail.content_list, list)
    if detail.content_list:
        item = detail.content_list[0]
        assert isinstance(item, ContentItem)
        assert item.data_type
        assert isinstance(item.task_status, int)


@pytest.mark.vcr(cassette_library_dir="tests/cassettes/test_fetch_detail")
def test_fetch_detail_excludes_business_strings() -> None:
    """DetailMeta projection must not carry headline / recommend_questions /
    category / industry_category — even after scrubbing, the dataclass shape
    forbids these by construction."""
    with PlaudClient(_token()) as client:
        meta = next(iter(client.list_recordings(since=None)))
        detail = client.fetch_detail(meta.plaud_id)

    blob = repr(detail)
    for forbidden in ("headline", "recommend_questions", "industry_category",
                       "original_category", "aiContentHeader"):
        assert forbidden not in blob, f"DetailMeta unexpectedly carries {forbidden!r}"
