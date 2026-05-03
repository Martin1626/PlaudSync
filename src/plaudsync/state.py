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
    plaud_id              TEXT PRIMARY KEY,
    title                 TEXT NOT NULL,
    created_at_plaud      TEXT NOT NULL,
    downloaded_at         TEXT NOT NULL,
    local_path            TEXT NOT NULL,
    classifier_label      TEXT NOT NULL,
    status                TEXT NOT NULL CHECK (status IN ('downloaded','failed','skipped','skipped_unknown_project','trashed')),
    sync_run_id           INTEGER REFERENCES sync_runs(run_id),
    file_size             INTEGER,
    content_status        TEXT,
    content_path          TEXT,
    content_task_ids      TEXT,
    classification_source TEXT,
    plaud_folder_id       TEXT
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
    meta: object,  # duck-typed: needs .plaud_id, .title, .created_at; .file_size optional
    status: str,
    local_path: str,
    run_id: int,
    classifier_label: str = "_unclassified",
    classification_source: str | None = None,
    content_status: str | None = None,
    content_path: str | None = None,
    content_task_ids: str | None = None,
    plaud_folder_id: str | None = None,
) -> None:
    """UPSERT semantics: never overwrite a 'downloaded' row.

    - If row absent: INSERT.
    - If row present with status='failed' or 'skipped_unknown_project' and
      incoming status='downloaded': UPDATE.
    - Otherwise: noop (downloaded → anything is rejected to honor immutability).

    BL-4/BL-X new kwargs (all nullable):
    - classification_source: 'name' | 'folder' | 'none' | None
    - content_status: 'pending' | 'complete' | 'not_applicable' | None
    - content_path: absolute path to .md sourozenec
    - content_task_ids: JSON-encoded {trans, outline, summary} for BL-5 fingerprint

    BL-6 new kwarg:
    - plaud_folder_id: Plaud folder ID (FiletagCache key); UI resolves to name
    """
    plaud_id = getattr(meta, "plaud_id")
    title = getattr(meta, "title")
    created_at = getattr(meta, "created_at")
    file_size = getattr(meta, "file_size", None) or None

    existing = conn.execute(
        "SELECT status FROM recordings WHERE plaud_id = ?", (plaud_id,)
    ).fetchone()

    if existing is None:
        conn.execute(
            "INSERT INTO recordings (plaud_id, title, created_at_plaud, "
            "downloaded_at, local_path, classifier_label, status, sync_run_id, "
            "file_size, classification_source, content_status, content_path, "
            "content_task_ids, plaud_folder_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (plaud_id, title, created_at, _now_iso(), local_path,
             classifier_label, status, run_id, file_size,
             classification_source, content_status, content_path,
             content_task_ids, plaud_folder_id),
        )
    elif existing[0] in ("failed", "skipped_unknown_project", "skipped", "trashed") and status == "downloaded":
        conn.execute(
            "UPDATE recordings SET title = ?, created_at_plaud = ?, "
            "downloaded_at = ?, local_path = ?, classifier_label = ?, "
            "status = ?, sync_run_id = ?, file_size = ?, "
            "classification_source = ?, content_status = ?, content_path = ?, "
            "content_task_ids = ?, plaud_folder_id = ? "
            "WHERE plaud_id = ?",
            (title, created_at, _now_iso(), local_path, classifier_label,
             status, run_id, file_size, classification_source, content_status,
             content_path, content_task_ids, plaud_folder_id, plaud_id),
        )
    # else: existing.status == 'downloaded' → noop (immutable per Decision #5)
    conn.commit()


def _migrate_status_check_constraint(conn: sqlite3.Connection) -> None:
    """Rebuild `recordings` table when its CHECK constraint pre-dates BL-3.

    SQLite cannot ALTER a CHECK constraint in place. Detect old definition
    via sqlite_master.sql and rebuild via temp-table copy.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='recordings'"
    ).fetchone()
    if row is None or "skipped_unknown_project" in row[0]:
        return
    conn.executescript(
        """
        BEGIN;
        CREATE TABLE recordings_new (
            plaud_id          TEXT PRIMARY KEY,
            title             TEXT NOT NULL,
            created_at_plaud  TEXT NOT NULL,
            downloaded_at     TEXT NOT NULL,
            local_path        TEXT NOT NULL,
            classifier_label  TEXT NOT NULL,
            status            TEXT NOT NULL CHECK (status IN ('downloaded','failed','skipped','skipped_unknown_project')),
            sync_run_id       INTEGER REFERENCES sync_runs(run_id),
            file_size         INTEGER
        );
        INSERT INTO recordings_new (plaud_id, title, created_at_plaud, downloaded_at, local_path, classifier_label, status, sync_run_id)
            SELECT plaud_id, title, created_at_plaud, downloaded_at, local_path, classifier_label, status, sync_run_id FROM recordings;
        DROP TABLE recordings;
        ALTER TABLE recordings_new RENAME TO recordings;
        CREATE INDEX IF NOT EXISTS idx_recordings_downloaded_at ON recordings(downloaded_at DESC);
        COMMIT;
        """
    )


def _migrate_add_file_size_column(conn: sqlite3.Connection) -> None:
    """Add nullable file_size column to recordings for existing DBs.

    SQLite's ALTER TABLE ADD COLUMN is idempotent in practice via try/except —
    OperationalError fires when the column already exists (new DBs from current
    schema, or post-migration runs).
    """
    try:
        conn.execute("ALTER TABLE recordings ADD COLUMN file_size INTEGER")
    except sqlite3.OperationalError:
        pass


def _migrate_add_plaud_folder_id_column(conn: sqlite3.Connection) -> None:
    """Add nullable plaud_folder_id column (BL-6 source-aware badge).

    Stores Plaud's folder ID per recording (from meta.plaud_folder). UI
    state_reader resolves the folder NAME via FiletagCache.lookup_by_id().
    Legacy rows stay NULL — frontend treats null as 'name'-source legacy
    behavior. Idempotent via OperationalError swallowing.
    """
    try:
        conn.execute("ALTER TABLE recordings ADD COLUMN plaud_folder_id TEXT")
    except sqlite3.OperationalError:
        pass


def _migrate_status_add_trashed(conn: sqlite3.Connection) -> None:
    """Rebuild recordings.status CHECK to include 'trashed' (BL-8).

    Fires when current constraint lacks 'trashed'. Idempotent via early
    return on detection. Runs after _migrate_status_check_constraint
    (chains via successive table rebuilds).
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='recordings'"
    ).fetchone()
    if row is None or "'trashed'" in row[0]:
        return
    conn.executescript(
        """
        BEGIN;
        CREATE TABLE recordings_new (
            plaud_id              TEXT PRIMARY KEY,
            title                 TEXT NOT NULL,
            created_at_plaud      TEXT NOT NULL,
            downloaded_at         TEXT NOT NULL,
            local_path            TEXT NOT NULL,
            classifier_label      TEXT NOT NULL,
            status                TEXT NOT NULL CHECK (status IN ('downloaded','failed','skipped','skipped_unknown_project','trashed')),
            sync_run_id           INTEGER REFERENCES sync_runs(run_id),
            file_size             INTEGER,
            content_status        TEXT,
            content_path          TEXT,
            content_task_ids      TEXT,
            classification_source TEXT,
            plaud_folder_id       TEXT
        );
        INSERT INTO recordings_new SELECT * FROM recordings;
        DROP TABLE recordings;
        ALTER TABLE recordings_new RENAME TO recordings;
        CREATE INDEX IF NOT EXISTS idx_recordings_downloaded_at ON recordings(downloaded_at DESC);
        COMMIT;
        """
    )


def _migrate_add_content_columns(conn: sqlite3.Connection) -> None:
    """Add nullable BL-4 / BL-X columns to recordings for existing DBs.

    - content_status        (NULL = legacy = not_applicable; pending / complete)
    - content_path          (absolute path to .md sourozenec)
    - content_task_ids      (JSON snapshot of task_id_info — BL-5 fingerprint)
    - classification_source (name / folder / none — for kill criterion #19)

    Idempotent via try/except (duplicate-column OperationalError swallowed).
    """
    for column_def in (
        "content_status TEXT",
        "content_path TEXT",
        "content_task_ids TEXT",
        "classification_source TEXT",
    ):
        try:
            conn.execute(f"ALTER TABLE recordings ADD COLUMN {column_def}")
        except sqlite3.OperationalError:
            pass


def open_state(state_root: Path) -> sqlite3.Connection:
    db_dir = state_root / ".plaudsync"
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_dir / "state.db")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    _migrate_status_check_constraint(conn)
    _migrate_add_file_size_column(conn)
    _migrate_add_content_columns(conn)
    _migrate_add_plaud_folder_id_column(conn)
    _migrate_status_add_trashed(conn)
    conn.commit()
    return conn
