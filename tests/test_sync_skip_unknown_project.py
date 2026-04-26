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


class _ClientNoListing:
    """Returns no new recordings on listing, but supports download_audio
    when retry pass calls it for previously-skipped rows."""

    def __init__(self, audio_bytes: dict[str, bytes]) -> None:
        self._audio = audio_bytes
        self.download_calls: list[str] = []

    def list_recordings(self, since=None):
        return iter([])

    def download_audio(self, plaud_id: str):
        self.download_calls.append(plaud_id)
        yield self._audio[plaud_id]


def test_skipped_recording_retried_after_config_update(tmp_path: Path) -> None:
    """After sync 1 skips UNKNOWN, user adds UNKNOWN to config; sync 2 must
    download and classify the previously-skipped recording."""
    alza_dir = tmp_path / "ALZA"
    alza_dir.mkdir()
    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir()

    config_v1 = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": alza_dir},
    )
    conn = open_state(tmp_path)

    meta = _MetaStub(
        plaud_id="rec-retry-1",
        title="04-26 UNKNOWN: bar",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    client_v1 = _ClientWithOneUnknownProject(meta)

    exit_v1 = run_sync(client_v1, CategorizationClassifier(), conn, config_v1, "manual")
    assert exit_v1 == 0
    assert client_v1.download_calls == []

    row_v1 = conn.execute(
        "SELECT status FROM recordings WHERE plaud_id = 'rec-retry-1'"
    ).fetchone()
    assert row_v1[0] == "skipped_unknown_project"

    unknown_dir = tmp_path / "UNKNOWN"
    unknown_dir.mkdir()
    config_v2 = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": alza_dir, "UNKNOWN": unknown_dir},
    )
    client_v2 = _ClientNoListing({"rec-retry-1": b"the-audio-bytes"})

    exit_v2 = run_sync(client_v2, CategorizationClassifier(), conn, config_v2, "manual")
    assert exit_v2 == 0
    assert client_v2.download_calls == ["rec-retry-1"]

    mp3s = list(unknown_dir.glob("*.mp3"))
    assert len(mp3s) == 1, f"expected 1 mp3 in UNKNOWN/, found: {mp3s}"
    assert mp3s[0].read_bytes() == b"the-audio-bytes"

    row_v2 = conn.execute(
        "SELECT status, local_path, classifier_label "
        "FROM recordings WHERE plaud_id = 'rec-retry-1'"
    ).fetchone()
    assert row_v2[0] == "downloaded"
    assert Path(row_v2[1]) == mp3s[0]
    assert row_v2[2] == "UNKNOWN"

    conn.close()


def _seed_skipped_row(
    conn: sqlite3.Connection,
    *,
    plaud_id: str,
    title: str,
    created_at: str,
    classifier_label: str,
) -> None:
    from plaudsync.state import start_sync_run
    run_id = start_sync_run(conn, "manual")
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, "
        "downloaded_at, local_path, classifier_label, status, sync_run_id) "
        "VALUES (?, ?, ?, ?, '', ?, 'skipped_unknown_project', ?)",
        (plaud_id, title, created_at, created_at, classifier_label, run_id),
    )
    conn.commit()


def test_skipped_recording_outside_14d_window_not_retried(tmp_path: Path) -> None:
    """Row with created_at_plaud older than 14d must NOT be retried even
    when config now has the project."""
    unknown_dir = tmp_path / "UNKNOWN"
    unknown_dir.mkdir()
    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir()

    config = Config(
        unclassified_dir=unclassified,
        projects={"UNKNOWN": unknown_dir},
    )
    conn = open_state(tmp_path)

    old_ts = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
    _seed_skipped_row(
        conn,
        plaud_id="rec-old-1",
        title="04-09 UNKNOWN: ancient",
        created_at=old_ts,
        classifier_label="UNKNOWN",
    )

    client = _ClientNoListing({"rec-old-1": b"should-never-be-fetched"})
    exit_code = run_sync(client, CategorizationClassifier(), conn, config, "manual")

    assert exit_code == 0
    assert client.download_calls == [], "must NOT call download for >14d row"

    mp3s = list(unknown_dir.glob("*.mp3"))
    assert mp3s == [], "no file must be written for old row"

    row = conn.execute(
        "SELECT status, local_path FROM recordings WHERE plaud_id = 'rec-old-1'"
    ).fetchone()
    assert row[0] == "skipped_unknown_project"
    assert row[1] == ""

    conn.close()
