"""SQLite delta state for PlaudSync — recordings + sync_runs tables.

See docs/superpowers/specs/2026-04-25-sync-core-design.md Decision #4.
WAL mode for concurrent UI reader + sync writer.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def last_successful_sync(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT MAX(finished_at) FROM sync_runs WHERE exit_code = 0"
    ).fetchone()
    return row[0] if row and row[0] else None


def start_sync_run(conn: sqlite3.Connection, trigger: str) -> int:
    cur = conn.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        (_now_iso(), trigger),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def finish_sync_run(
    conn: sqlite3.Connection,
    run_id: int,
    exit_code: int,
    recordings_new: int,
    recordings_skipped: int,
    recordings_failed: int,
) -> None:
    conn.execute(
        "UPDATE sync_runs SET finished_at = ?, exit_code = ?, "
        "recordings_new = ?, recordings_skipped = ?, recordings_failed = ? "
        "WHERE run_id = ?",
        (_now_iso(), exit_code, recordings_new, recordings_skipped,
         recordings_failed, run_id),
    )
    conn.commit()


def recording_exists_and_downloaded(conn: sqlite3.Connection, plaud_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM recordings WHERE plaud_id = ? AND status = 'downloaded'",
        (plaud_id,),
    ).fetchone()
    return row is not None


def record_recording(
    conn: sqlite3.Connection,
    meta: object,  # duck-typed: needs .plaud_id, .title, .created_at
    status: str,
    local_path: str,
    run_id: int,
    classifier_label: str = "_unclassified",
) -> None:
    """UPSERT semantics: never overwrite a 'downloaded' row.

    - If row absent: INSERT.
    - If row present with status='failed' and incoming status='downloaded': UPDATE.
    - Otherwise: noop (downloaded → anything is rejected to honor immutability).
    """
    plaud_id = getattr(meta, "plaud_id")
    title = getattr(meta, "title")
    created_at = getattr(meta, "created_at")

    existing = conn.execute(
        "SELECT status FROM recordings WHERE plaud_id = ?", (plaud_id,)
    ).fetchone()

    if existing is None:
        conn.execute(
            "INSERT INTO recordings (plaud_id, title, created_at_plaud, "
            "downloaded_at, local_path, classifier_label, status, sync_run_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (plaud_id, title, created_at, _now_iso(), local_path,
             classifier_label, status, run_id),
        )
    elif existing[0] == "failed" and status == "downloaded":
        conn.execute(
            "UPDATE recordings SET title = ?, created_at_plaud = ?, "
            "downloaded_at = ?, local_path = ?, classifier_label = ?, "
            "status = ?, sync_run_id = ? WHERE plaud_id = ?",
            (title, created_at, _now_iso(), local_path, classifier_label,
             status, run_id, plaud_id),
        )
    # else: existing.status == 'downloaded' → noop (immutable per Decision #5)
    conn.commit()


def open_state(state_root: Path) -> sqlite3.Connection:
    db_dir = state_root / ".plaudsync"
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_dir / "state.db")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn
