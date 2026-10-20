"""RecordingMeta.edit_marker — listing key `version_ms` (Ruling 8).

Plaud bumps version_ms on every edit (incl. speaker renames), so the speaker
pass re-checks a recording when the marker changes.
"""
from __future__ import annotations

from plaudsync.plaud_client import RecordingMeta


def _base_raw() -> dict:
    return {
        "id": "rec_001",
        "filename": "t",
        "start_time": 1745000000000,
        "duration_ms": 60000,
        "filesize": 12345,
    }


def test_edit_marker_from_version_ms() -> None:
    meta = RecordingMeta.from_raw({**_base_raw(), "version_ms": 1777468355443})
    assert meta.edit_marker == "1777468355443"


def test_edit_marker_none_when_missing() -> None:
    assert RecordingMeta.from_raw(_base_raw()).edit_marker is None


def test_positional_constructor_without_marker_still_works() -> None:
    meta = RecordingMeta("id", "t", "2026-01-01T00:00:00+00:00", 0, 0, 0, "_unknown")
    assert meta.edit_marker is None
