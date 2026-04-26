"""Integration tests for rolling re-classify pass in sync.run_sync."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plaudsync.classifier import CategorizationClassifier
from plaudsync.config import Config
from plaudsync.state import open_state, start_sync_run
from plaudsync.sync import run_sync


def _seed_unclassified_row(
    conn: sqlite3.Connection,
    *,
    plaud_id: str,
    title: str,
    created_at: str,
    downloaded_at: str,
    local_path: str,
    run_id: int,
) -> None:
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, "
        "downloaded_at, local_path, classifier_label, status, sync_run_id) "
        "VALUES (?, ?, ?, ?, ?, '_unclassified', 'downloaded', ?)",
        (plaud_id, title, created_at, downloaded_at, local_path, run_id),
    )
    conn.commit()


class _EmptyClient:
    def list_recordings(self, since=None):
        return iter([])

    def download_audio(self, _):
        raise AssertionError("must not download — no new recordings")


def test_reclassify_moves_unclassified_in_window(tmp_path: Path) -> None:
    """Rows with classifier_label='_unclassified' and downloaded_at within
    last 14 days are re-evaluated; matched rows get moved to project folder
    and DB updated."""
    alza_dir = tmp_path / "ALZA"
    fhb_dir = tmp_path / "FHB"
    unclassified = tmp_path / "Unclassified" / "_unknown"
    alza_dir.mkdir()
    fhb_dir.mkdir()
    unclassified.mkdir(parents=True)

    config = Config(
        unclassified_dir=tmp_path / "Unclassified",
        projects={"ALZA": alza_dir, "FHB": fhb_dir},
    )
    conn = open_state(tmp_path)
    seed_run_id = start_sync_run(conn, "manual")

    now = datetime.now(timezone.utc)

    # Row 1: in window (1h ago), title matches Alza
    file_1 = unclassified / "row1.mp3"
    file_1.write_bytes(b"row1-content")
    _seed_unclassified_row(
        conn,
        plaud_id="row1",
        title="04-26 Alza: test1",
        created_at=(now - timedelta(hours=1)).isoformat(),
        downloaded_at=(now - timedelta(hours=1)).isoformat(),
        local_path=str(file_1),
        run_id=seed_run_id,
    )

    # Row 2: in window (13 days ago), title matches FHB
    file_2 = unclassified / "row2.mp3"
    file_2.write_bytes(b"row2-content")
    _seed_unclassified_row(
        conn,
        plaud_id="row2",
        title="2026-04-13 FHB: test2",
        created_at=(now - timedelta(days=13)).isoformat(),
        downloaded_at=(now - timedelta(days=13)).isoformat(),
        local_path=str(file_2),
        run_id=seed_run_id,
    )

    # Row 3: outside window (15 days ago), title matches Alza but should be skipped
    file_3 = unclassified / "row3.mp3"
    file_3.write_bytes(b"row3-content")
    _seed_unclassified_row(
        conn,
        plaud_id="row3",
        title="04-09 Alza: old",
        created_at=(now - timedelta(days=15)).isoformat(),
        downloaded_at=(now - timedelta(days=15)).isoformat(),
        local_path=str(file_3),
        run_id=seed_run_id,
    )

    # Row 4: in window, title does NOT match regex
    file_4 = unclassified / "row4.mp3"
    file_4.write_bytes(b"row4-content")
    _seed_unclassified_row(
        conn,
        plaud_id="row4",
        title="random untitled recording",
        created_at=(now - timedelta(hours=2)).isoformat(),
        downloaded_at=(now - timedelta(hours=2)).isoformat(),
        local_path=str(file_4),
        run_id=seed_run_id,
    )

    exit_code = run_sync(_EmptyClient(), CategorizationClassifier(), conn, config, "manual")
    assert exit_code == 0

    # Row 1 → moved to ALZA, label updated
    row1 = conn.execute(
        "SELECT classifier_label, local_path FROM recordings WHERE plaud_id = 'row1'"
    ).fetchone()
    assert row1[0] == "Alza"
    assert Path(row1[1]).parent == alza_dir
    assert Path(row1[1]).exists()
    assert not file_1.exists(), "source file in _unknown/ must be gone after move"

    # Row 2 → moved to FHB, label updated
    row2 = conn.execute(
        "SELECT classifier_label, local_path FROM recordings WHERE plaud_id = 'row2'"
    ).fetchone()
    assert row2[0] == "FHB"
    assert Path(row2[1]).parent == fhb_dir

    # Row 3 → outside window, untouched
    row3 = conn.execute(
        "SELECT classifier_label, local_path FROM recordings WHERE plaud_id = 'row3'"
    ).fetchone()
    assert row3[0] == "_unclassified"
    assert Path(row3[1]) == file_3
    assert file_3.exists()

    # Row 4 → in window but title does not match, untouched
    row4 = conn.execute(
        "SELECT classifier_label, local_path FROM recordings WHERE plaud_id = 'row4'"
    ).fetchone()
    assert row4[0] == "_unclassified"
    assert Path(row4[1]) == file_4
    assert file_4.exists()

    conn.close()
