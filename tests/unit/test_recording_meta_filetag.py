"""Hotfix J (BL-X 2026-04-30) — RecordingMeta extracts folder ID from
``filetag_id_list`` (list shape Plaud actually uses) instead of the
non-existent singular ``filetag_id``.

Bug history: pre-Hotfix J, plaud_folder was always '_unknown' for every
recording because the wrong field was read. Folder-classifier path was
silently dead — folder badge never fired in production despite
classify_by_folder=True + correct folder mappings in config.
"""
from __future__ import annotations

from plaudsync.plaud_client import RecordingMeta


def _base_raw() -> dict:
    return {
        "id": "rec_001",
        "filename": "04-30 X: title",
        "start_time": 1745000000000,
        "duration_ms": 60000,
        "filesize": 12345,
    }


def test_extracts_folder_id_from_filetag_id_list() -> None:
    """Production case: Plaud /file/simple/web returns filetag_id_list as
    a list with one folder ID per recording."""
    raw = {**_base_raw(), "filetag_id_list": ["8ed7ab6e5a68f02e31f736a15a99024d"]}
    meta = RecordingMeta.from_raw(raw)
    assert meta.plaud_folder == "8ed7ab6e5a68f02e31f736a15a99024d"


def test_empty_filetag_id_list_falls_back_to_unknown() -> None:
    raw = {**_base_raw(), "filetag_id_list": []}
    meta = RecordingMeta.from_raw(raw)
    assert meta.plaud_folder == "_unknown"


def test_missing_filetag_id_list_falls_back_to_unknown() -> None:
    raw = {**_base_raw()}  # no filetag fields at all
    meta = RecordingMeta.from_raw(raw)
    assert meta.plaud_folder == "_unknown"


def test_multi_entry_list_uses_first() -> None:
    """If Plaud ever returns multiple folder IDs (one recording in 2 folders),
    we use the first. Today recordings are filed in at most one folder."""
    raw = {**_base_raw(), "filetag_id_list": ["aaa" + "0" * 29, "bbb" + "0" * 29]}
    meta = RecordingMeta.from_raw(raw)
    assert meta.plaud_folder == "aaa" + "0" * 29


def test_legacy_singular_filetag_id_still_works() -> None:
    """Defensive fallback for hypothetical alt API response shape."""
    raw = {**_base_raw(), "filetag_id": "legacy_singular_id_value_here_32"}
    meta = RecordingMeta.from_raw(raw)
    assert meta.plaud_folder == "legacy_singular_id_value_here_32"


def test_legacy_tag_ids_field_still_works() -> None:
    """Pre-Hotfix-J fallback was tag_ids list; keep it for back-compat."""
    raw = {**_base_raw(), "tag_ids": ["legacy_tag_value_32_chars_xxxxxx"]}
    meta = RecordingMeta.from_raw(raw)
    assert meta.plaud_folder == "legacy_tag_value_32_chars_xxxxxx"


def test_filetag_id_list_takes_precedence_over_legacy() -> None:
    """Real Plaud field wins over legacy fallbacks even when both present."""
    raw = {
        **_base_raw(),
        "filetag_id_list": ["real_value_32_chars_xxxxxxxxxxx"],
        "tag_ids": ["legacy_tag_value_32_chars_xxxxxx"],
        "filetag_id": "singular_legacy_value_32_chars_x",
    }
    meta = RecordingMeta.from_raw(raw)
    assert meta.plaud_folder == "real_value_32_chars_xxxxxxxxxxx"
