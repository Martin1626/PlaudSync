"""SQLite delta state for PlaudSync — recordings + sync_runs tables.

See docs/superpowers/specs/2026-04-25-sync-core-design.md Decision #4.
WAL mode for concurrent UI reader + sync writer.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


_SCHEMA = """
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

CREATE INDEX IF NOT EXISTS idx_recordings_downloaded_at ON recordings(downloaded_at DESC);
CREATE INDEX IF NOT EXISTS idx_sync_runs_started_at ON sync_runs(started_at DESC);
"""


def open_state(state_root: Path) -> sqlite3.Connection:
    db_dir = state_root / ".plaudsync"
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_dir / "state.db")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn
