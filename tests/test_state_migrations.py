"""Tests for state.py schema migrations + record_recording UPSERT extensions."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from plaudsync.state import open_state, record_recording, start_sync_run


_OLD_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_runs (
    run_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at           TEXT NOT NULL,
    finished_at          TEXT,
    exit_code            INTEGER,
    recordings_new       INTEGER NOT NULL DEFAULT 0,
    recordings_skipped   INTEGER NOT NULL DEFAULT 0,
    recordings_failed    INTEGER NOT NULL DEFAULT 0,
    trigger              TEXT NOT NULL CHECK (trigger IN ('task_scheduler','ui_sync_now','manual'))
);

CREATE TABLE IF NOT EXISTS recordings (
    plaud_id          TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    created_at_plaud  TEXT NOT NULL,
    downloaded_at     TEXT NOT NULL,
    local_path        TEXT NOT NULL,
    classifier_label  TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('downloaded','failed','skipped')),
    sync_run_id       INTEGER REFERENCES sync_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_recordings_downloaded_at ON recordings(downloaded_at DESC);
CREATE INDEX IF NOT EXISTS idx_sync_runs_started_at ON sync_runs(started_at DESC);
"""


@dataclass
class _MetaStub:
    plaud_id: str
    title: str
    created_at: str
    file_size: int = 0


def _seed_old_db(state_root: Path) -> Path:
    """Create a DB with the pre-BL-3 schema (no skipped_unknown_project, no
    file_size column) and one legacy row."""
    db_dir = state_root / ".plaudsync"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "state.db"
    raw = sqlite3.connect(db_path)
    raw.executescript(_OLD_SCHEMA)
    raw.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        ("2026-04-25T00:00:00+00:00", "manual"),
    )
    raw.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, "
        "downloaded_at, local_path, classifier_label, status, sync_run_id) "
        "VALUES (?, ?, ?, ?, ?, ?, 'downloaded', 1)",
        ("legacy-1", "old recording", "2026-04-25T00:00:00+00:00",
         "2026-04-25T00:01:00+00:00", "/legacy/path.mp3", "_unclassified"),
    )
    raw.commit()
    raw.close()
    return db_path


def test_open_state_migrates_old_check_constraint(tmp_path: Path) -> None:
    """open_state on a DB with pre-BL-3 CHECK constraint must rebuild the
    table, preserve existing rows, and accept skipped_unknown_project."""
    _seed_old_db(tmp_path)

    conn = open_state(tmp_path)

    legacy = conn.execute(
        "SELECT plaud_id, title, classifier_label, status FROM recordings "
        "WHERE plaud_id = 'legacy-1'"
    ).fetchone()
    assert legacy == ("legacy-1", "old recording", "_unclassified", "downloaded")

    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='recordings'"
    ).fetchone()[0]
    assert "skipped_unknown_project" in sql

    run_id = start_sync_run(conn, "manual")
    record_recording(
        conn,
        _MetaStub(plaud_id="new-1", title="04-26 X: y",
                  created_at="2026-04-26T00:00:00+00:00", file_size=4096),
        status="skipped_unknown_project",
        local_path="",
        run_id=run_id,
        classifier_label="X",
    )

    row = conn.execute(
        "SELECT status, file_size FROM recordings WHERE plaud_id = 'new-1'"
    ).fetchone()
    assert row[0] == "skipped_unknown_project"
    assert row[1] == 4096

    conn.close()


def test_open_state_adds_file_size_column_idempotent(tmp_path: Path) -> None:
    """Running open_state twice must not error (ADD COLUMN is idempotent)."""
    _seed_old_db(tmp_path)

    conn1 = open_state(tmp_path)
    conn1.close()

    conn2 = open_state(tmp_path)
    cols = [
        row[1]
        for row in conn2.execute("PRAGMA table_info(recordings)").fetchall()
    ]
    assert "file_size" in cols
    conn2.close()


def test_record_recording_upgrades_skipped_to_downloaded(tmp_path: Path) -> None:
    """UPSERT path: existing skipped_unknown_project row + incoming 'downloaded'
    must update status, local_path, classifier_label, and file_size."""
    conn = open_state(tmp_path)
    run_id = start_sync_run(conn, "manual")

    skip_meta = _MetaStub(
        plaud_id="rec-1",
        title="04-26 X: y",
        created_at="2026-04-26T00:00:00+00:00",
        file_size=2048,
    )
    record_recording(conn, skip_meta, status="skipped_unknown_project",
                     local_path="", run_id=run_id, classifier_label="X")

    download_meta = _MetaStub(
        plaud_id="rec-1",
        title="04-26 X: y",
        created_at="2026-04-26T00:00:00+00:00",
        file_size=2048,
    )
    record_recording(conn, download_meta, status="downloaded",
                     local_path="/data/X/file.mp3", run_id=run_id,
                     classifier_label="X")

    row = conn.execute(
        "SELECT status, local_path, classifier_label, file_size "
        "FROM recordings WHERE plaud_id = 'rec-1'"
    ).fetchone()
    assert row[0] == "downloaded"
    assert row[1] == "/data/X/file.mp3"
    assert row[2] == "X"
    assert row[3] == 2048

    conn.close()


def test_record_recording_does_not_overwrite_downloaded(tmp_path: Path) -> None:
    """Immutability: a 'downloaded' row must not be downgraded to skipped."""
    conn = open_state(tmp_path)
    run_id = start_sync_run(conn, "manual")

    meta = _MetaStub(
        plaud_id="rec-immutable",
        title="04-26 Y: z",
        created_at="2026-04-26T00:00:00+00:00",
        file_size=1024,
    )
    record_recording(conn, meta, status="downloaded",
                     local_path="/data/Y/z.mp3", run_id=run_id,
                     classifier_label="Y")

    record_recording(conn, meta, status="skipped_unknown_project",
                     local_path="", run_id=run_id, classifier_label="Y")

    row = conn.execute(
        "SELECT status, local_path FROM recordings WHERE plaud_id = 'rec-immutable'"
    ).fetchone()
    assert row[0] == "downloaded"
    assert row[1] == "/data/Y/z.mp3"

    conn.close()
