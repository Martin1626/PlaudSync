"""Integration tests for BL-3: skip recordings with unknown project codes."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plaudsync.classifier import CategorizationClassifier
from plaudsync.config import Config
from plaudsync.state import open_state
from plaudsync.sync import run_sync


@dataclass
class _MetaStub:
    plaud_id: str
    title: str
    created_at: str
    file_size: int = 0
    plaud_folder: str = ""


class _ClientWithOneUnknownProject:
    """Lists 1 recording whose title regex-matches an unknown project code."""

    def __init__(self, meta: _MetaStub) -> None:
        self._meta = meta
        self.download_calls: list[str] = []

    def list_recordings(self, since=None):
        yield self._meta

    def download_audio(self, plaud_id: str):
        self.download_calls.append(plaud_id)
        yield b"audio-bytes"


def test_unknown_project_is_skipped_not_downloaded(tmp_path: Path) -> None:
    """Title `MM-DD UNKNOWN: foo` with UNKNOWN absent from config →
    no download, DB row status='skipped_unknown_project', local_path=''.
    """
    alza_dir = tmp_path / "ALZA"
    alza_dir.mkdir()
    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir()

    config = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": alza_dir},
    )
    conn = open_state(tmp_path)

    meta = _MetaStub(
        plaud_id="rec-unknown-1",
        title="04-26 UNKNOWN: foo",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    client = _ClientWithOneUnknownProject(meta)

    exit_code = run_sync(client, CategorizationClassifier(), conn, config, "manual")

    assert exit_code == 0
    assert client.download_calls == [], "download_audio must NOT be called"

    mp3s = list(tmp_path.rglob("*.mp3"))
    assert mp3s == [], f"expected no MP3 files, found: {mp3s}"

    row = conn.execute(
        "SELECT status, local_path, classifier_label FROM recordings "
        "WHERE plaud_id = 'rec-unknown-1'"
    ).fetchone()
    assert row is not None, "DB row must be inserted for audit"
    assert row[0] == "skipped_unknown_project"
    assert row[1] == ""
    assert row[2] == "UNKNOWN"

    conn.close()
