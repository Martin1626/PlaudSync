"""Unit tests for src/plaudsync/state.py."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from plaudsync.state import open_state


def test_open_state_creates_schema_and_wal_mode(tmp_path: Path) -> None:
    conn = open_state(tmp_path)
    try:
        # WAL mode active
        cur = conn.execute("PRAGMA journal_mode")
        assert cur.fetchone()[0].lower() == "wal"

        # Schema present
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('recordings','sync_runs')"
        )}
        assert tables == {"recordings", "sync_runs"}

        # Indexes present
        indexes = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'idx_%'"
        )}
        assert "idx_recordings_downloaded_at" in indexes
        assert "idx_sync_runs_started_at" in indexes
    finally:
        conn.close()
