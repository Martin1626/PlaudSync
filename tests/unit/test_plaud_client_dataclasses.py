"""Pure-data unit tests for FolderCatalogItem / ContentItem / DetailMeta.

Cassette tests for fetch_filetags / fetch_detail / download_content_text live
in tests/integration/ and require live API recording (BL-4/BL-X cassette
session — see cassette-refresh skill).
"""
from __future__ import annotations

import pytest

from plaudsync.plaud_client import (
    ContentItem,
    DetailMeta,
    FolderCatalogItem,
    PlaudDownloadCorrupted,
    PlaudClient,
)
from unittest.mock import patch


# ---------------------------------------------------------------------------
# FolderCatalogItem
# ---------------------------------------------------------------------------

def test_folder_catalog_item_from_raw_full() -> None:
    raw = {"id": "abc" * 10 + "ab", "name": "Alza", "icon": "📁", "color": "#FF0000"}
    item = FolderCatalogItem.from_raw(raw)
    assert item.id == raw["id"]
    assert item.name == "Alza"
    assert item.icon == "📁"
    assert item.color == "#FF0000"


def test_folder_catalog_item_from_raw_missing_keys_defaults_empty() -> None:
    item = FolderCatalogItem.from_raw({})
    assert item.id == ""
    assert item.name == ""
    assert item.icon == ""
    assert item.color == ""


# ---------------------------------------------------------------------------
# ContentItem
# ---------------------------------------------------------------------------

def test_content_item_from_raw_parses_task_status_int() -> None:
    raw = {
        "data_id": "auto_sum:abc:def",
        "data_type": "auto_sum_note",
        "task_status": 1,
        "data_link": "https://s3.example/x?signature=y",
        "err_code": "",
        "err_msg": "",
    }
    item = ContentItem.from_raw(raw)
    assert item.data_type == "auto_sum_note"
    assert item.task_status == 1
    assert item.data_link.startswith("https://")


def test_content_item_task_status_coerces_string_to_int() -> None:
    item = ContentItem.from_raw({"task_status": "2"})
    assert item.task_status == 2


def test_content_item_missing_task_status_defaults_zero() -> None:
    item = ContentItem.from_raw({})
    assert item.task_status == 0


# ---------------------------------------------------------------------------
# DetailMeta
# ---------------------------------------------------------------------------

def _detail_raw(language: str = "cs", speakers: int = 3) -> dict:
    return {
        "extra_data": {
            "tranConfig": {"language": language, "diarization": 1},
            "task_id_info": {
                "trans_task_id": "t1",
                "outline_task_id": "o1",
                "summary_id": "s1",
            },
            # AI/business fields included in raw — must NOT leak into DetailMeta
            "aiContentHeader": {
                "headline": "Confidential discussion about acquisition",
                "category": "M&A",
                "recommend_questions": [{"q": "secret"}],
            },
        },
        "embeddings": {f"Speaker {i}": [0.1] * 256 for i in range(1, speakers + 1)},
        "content_list": [
            {"data_id": "d1", "data_type": "transaction", "task_status": 1,
             "data_link": "https://s3/x", "err_code": "", "err_msg": ""},
            {"data_id": "d2", "data_type": "outline", "task_status": 1,
             "data_link": "https://s3/y", "err_code": "", "err_msg": ""},
            {"data_id": "d3", "data_type": "auto_sum_note", "task_status": 0,
             "data_link": "https://s3/z", "err_code": "", "err_msg": ""},
        ],
    }


def test_detail_meta_from_raw_extracts_language_and_speaker_count() -> None:
    detail = DetailMeta.from_raw("rec1", _detail_raw(language="en", speakers=5))
    assert detail.plaud_id == "rec1"
    assert detail.language == "en"
    assert detail.speakers_count == 5


def test_detail_meta_from_raw_extracts_task_ids() -> None:
    detail = DetailMeta.from_raw("rec1", _detail_raw())
    assert detail.task_ids == {"trans": "t1", "outline": "o1", "summary": "s1"}


def test_detail_meta_omits_business_fields() -> None:
    """Headline / recommend_questions / category MUST not be exposed."""
    detail = DetailMeta.from_raw("rec1", _detail_raw())
    # Use string repr scan as a defense-in-depth — none of the AI labels
    # should appear in any DetailMeta attribute.
    blob = repr(detail)
    assert "headline" not in blob.lower()
    assert "Confidential" not in blob
    assert "M&A" not in blob
    assert "secret" not in blob


def test_detail_meta_content_list_typed() -> None:
    detail = DetailMeta.from_raw("rec1", _detail_raw())
    assert all(isinstance(it, ContentItem) for it in detail.content_list)
    assert len(detail.content_list) == 3
    types = [it.data_type for it in detail.content_list]
    assert types == ["transaction", "outline", "auto_sum_note"]


def test_detail_meta_handles_missing_extra_data() -> None:
    detail = DetailMeta.from_raw("rec1", {"content_list": []})
    assert detail.language == ""
    assert detail.speakers_count == 0
    assert detail.task_ids == {}


def test_detail_meta_handles_partial_task_id_info() -> None:
    raw = {
        "extra_data": {
            "task_id_info": {"trans_task_id": "t1"},  # only trans
        },
        "content_list": [],
    }
    detail = DetailMeta.from_raw("rec1", raw)
    assert detail.task_ids == {"trans": "t1"}


# ---------------------------------------------------------------------------
# download_content_text — SSRF guard (no network)
# ---------------------------------------------------------------------------

def _no_probe(self) -> None:
    return None


def test_download_content_text_rejects_non_https() -> None:
    with patch.object(PlaudClient, "_region_probe", _no_probe):
        client = PlaudClient("fake-token")
    item = ContentItem(
        data_id="d1", data_type="transaction", task_status=1,
        data_link="http://evil.example/x", err_code="", err_msg="",
    )
    with pytest.raises(PlaudDownloadCorrupted, match="https"):
        client.download_content_text(item)


def test_download_content_text_rejects_non_url_scheme() -> None:
    with patch.object(PlaudClient, "_region_probe", _no_probe):
        client = PlaudClient("fake-token")
    item = ContentItem(
        data_id="d1", data_type="transaction", task_status=1,
        data_link="file:///etc/passwd", err_code="", err_msg="",
    )
    with pytest.raises(PlaudDownloadCorrupted, match="https"):
        client.download_content_text(item)
