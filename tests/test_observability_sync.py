"""Scrubber tests for sync-core inline labels."""
from __future__ import annotations

from plaudsync.observability import scrub_event


def test_scrubs_title_inline_in_message() -> None:
    event = {"exception": {"values": [{"value": "failed for title=Sprint planning"}]}}
    scrubbed = scrub_event(event, hint={})
    assert scrubbed is not None
    msg = scrubbed["exception"]["values"][0]["value"]
    assert "Sprint planning" not in msg
    assert "<redacted-label>" in msg


def test_scrubs_local_path_inline_in_message() -> None:
    event = {"exception": {"values": [{"value": "FS error local_path=C:/Recordings/file.mp3"}]}}
    scrubbed = scrub_event(event, hint={})
    assert scrubbed is not None
    msg = scrubbed["exception"]["values"][0]["value"]
    assert "local_path" in msg  # key preserved
    assert "<redacted-label>" in msg
    # The path itself was caught earlier by _WIN_PATH_RE → <path>; but the
    # label-pattern catches it too. Both are acceptable; assert no leak.
    assert "C:/Recordings/file.mp3" not in msg


def test_scrubs_plaud_folder_inline_in_message() -> None:
    event = {"exception": {"values": [{"value": "moved file plaud_folder=Klienti"}]}}
    scrubbed = scrub_event(event, hint={})
    assert scrubbed is not None
    msg = scrubbed["exception"]["values"][0]["value"]
    assert "Klienti" not in msg
