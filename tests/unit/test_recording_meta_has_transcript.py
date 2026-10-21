"""RecordingMeta.has_transcript — listing key `is_trans`.

The speaker pass learns only recordings Plaud has transcribed, so a recording
without a transcript costs no Plaud call.
"""
from __future__ import annotations

import pytest

from plaudsync.plaud_client import RecordingMeta


def _base_raw() -> dict:
    return {
        "id": "rec_001",
        "filename": "t",
        "start_time": 1745000000000,
        "duration_ms": 60000,
        "filesize": 12345,
    }


@pytest.mark.parametrize("is_trans", [True, False])
def test_has_transcript_from_is_trans(is_trans: bool) -> None:
    assert RecordingMeta.from_raw({**_base_raw(), "is_trans": is_trans}).has_transcript is is_trans


def test_has_transcript_assumed_when_listing_omits_it() -> None:
    # Unknown = try: the transcript fetch itself tells whether one exists.
    assert RecordingMeta.from_raw(_base_raw()).has_transcript is True
