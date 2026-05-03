"""classification_source transition coverage — round-trip across name/folder/none.

Audit triggered by Hotfix L 2026-04-30. Hotfix F covered name→name (rename
within name strategy). Hotfix I covered name(unknown)→folder (fall-through).
Missing: folder→name (Plaud rename adds project code in title) and
classification_source persistence under content drift retry.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from plaudsync.classifiers.name import NameClassifier
from plaudsync.config import Config, ProjectEntry
from plaudsync.state import open_state, start_sync_run
from plaudsync.sync import _reclassify_recent


def _live(plaud_id: str, title: str, plaud_folder: str = "_unknown"):
    return SimpleNamespace(
        plaud_id=plaud_id, title=title,
        created_at="2026-04-30T08:00:00+00:00",
        plaud_folder=plaud_folder,
        start_time_ms=1745000000000, duration_seconds=60, file_size=1024,
    )


def _seed_downloaded(
    tmp_path: Path, *, plaud_id: str, title: str, label: str,
    source: str, folder_id: str | None, local_path: str,
) -> "sqlite3.Connection":
    import sqlite3
    from datetime import datetime, timezone
    conn = open_state(tmp_path)
    start_sync_run(conn, "manual")
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, downloaded_at, "
        "local_path, classifier_label, status, sync_run_id, classification_source, "
        "plaud_folder_id) "
        "VALUES (?, ?, ?, ?, ?, ?, 'downloaded', 1, ?, ?)",
        (plaud_id, title, "2026-04-30T08:00:00+00:00",
         datetime.now(timezone.utc).isoformat(), local_path, label,
         source, folder_id),
    )
    conn.commit()
    return conn


def test_classification_source_folder_to_name_after_plaud_rename(tmp_path: Path) -> None:
    """Recording originally folder-classified (no project code in title,
    just in mapped Plaud folder). User renames on Plaud to add project
    code matching a configured project. Reclassify pass picks up live
    title, returns name source. DB row's classification_source updates.
    """
    skoleni_dir = tmp_path / "Školení"
    alza_dir = tmp_path / "ALZA"
    unclassified = tmp_path / "U"
    for d in (skoleni_dir, alza_dir, unclassified):
        d.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={
            "Školení": ProjectEntry(path=skoleni_dir, plaud_folder_id="skol_id"),
            "ALZA": ProjectEntry(path=alza_dir, plaud_folder_id="alza_id"),
        },
        classify_by_folder=True,
    )

    plaud_id = "rec_renamed"
    db_title = "Random meeting recording"  # no name regex match
    live_title = "04-30 ALZA: kickoff diskuze"  # rename adds project code
    mp3 = skoleni_dir / "rec_renamed.mp3"
    mp3.write_bytes(b"X")

    conn = _seed_downloaded(
        tmp_path, plaud_id=plaud_id, title=db_title, label="Školení",
        source="folder", folder_id="skol_id", local_path=str(mp3),
    )
    try:
        # Reclassify with live_metas — Plaud-side rename triggered.
        moved, failed = _reclassify_recent(
            conn, NameClassifier(), config, run_id=1,
            live_metas={plaud_id: _live(plaud_id, live_title, "skol_id")},
            days=14,
        )
        # NOTE: current _reclassify_recent uses NameClassifier (not full
        # waterfall). Live title is "04-30 ALZA: kickoff" → NameClassifier
        # returns "ALZA" (in config) → label changes from Školení to ALZA.
        # _reclassify_recent.UPDATE persists new title + label but does NOT
        # currently update classification_source (TODO follow-up).
        assert moved == 1
        assert failed == 0
        new_mp3 = alza_dir / "rec_renamed.mp3"
        assert new_mp3.exists()

        row = conn.execute(
            "SELECT title, classifier_label, classification_source "
            "FROM recordings WHERE plaud_id = ?", (plaud_id,),
        ).fetchone()
        assert row[0] == live_title
        assert row[1] == "ALZA"
        # Hotfix M (2026-04-30): classification_source NOW correctly
        # updates from 'folder' to 'name' when reclassify triggers via
        # name regex match.
        assert row[2] == "name"
    finally:
        conn.close()


def test_classification_source_persisted_when_label_unchanged(tmp_path: Path) -> None:
    """Hotfix F path: title changes but resolves to same label. The row
    should be left alone on file move (no actual project change), but
    title DOES update."""
    project = tmp_path / "ALZA"
    unclassified = tmp_path / "U"
    project.mkdir()
    unclassified.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": ProjectEntry(path=project, plaud_folder_id="alza_id")},
        classify_by_folder=True,
    )

    plaud_id = "rec_minor_rename"
    mp3 = project / "rec.mp3"
    mp3.write_bytes(b"X")
    conn = _seed_downloaded(
        tmp_path, plaud_id=plaud_id,
        title="04-30 ALZA: original",
        label="ALZA", source="name",
        folder_id="alza_id",
        local_path=str(mp3),
    )
    try:
        moved, failed = _reclassify_recent(
            conn, NameClassifier(), config, run_id=1,
            live_metas={
                plaud_id: _live(plaud_id, "04-30 ALZA: minor edit", "alza_id"),
            },
            days=14,
        )
        assert moved == 0  # label unchanged, no file move
        assert failed == 0
        row = conn.execute(
            "SELECT title, classifier_label, classification_source "
            "FROM recordings WHERE plaud_id=?",
            (plaud_id,),
        ).fetchone()
        assert row[0] == "04-30 ALZA: minor edit"  # title persisted
        assert row[1] == "ALZA"
        assert row[2] == "name"  # source preserved
    finally:
        conn.close()


def test_classification_source_unchanged_for_idempotent_resync(tmp_path: Path) -> None:
    """Sanity: row already in correct state, sync re-runs → no spurious
    UPDATE that could mutate classification_source."""
    project = tmp_path / "Školení"
    unclassified = tmp_path / "U"
    project.mkdir()
    unclassified.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"Školení": ProjectEntry(path=project, plaud_folder_id="skol")},
        classify_by_folder=True,
    )

    plaud_id = "rec_stable"
    mp3 = project / "rec.mp3"
    mp3.write_bytes(b"X")
    conn = _seed_downloaded(
        tmp_path, plaud_id=plaud_id,
        title="meeting on whatever",  # no name regex
        label="Školení", source="folder",
        folder_id="skol",
        local_path=str(mp3),
    )
    try:
        # Same title in live_metas — no rename, no work.
        moved, failed = _reclassify_recent(
            conn, NameClassifier(), config, run_id=1,
            live_metas={plaud_id: _live(plaud_id, "meeting on whatever", "skol")},
            days=14,
        )
        assert moved == 0
        assert failed == 0
        row = conn.execute(
            "SELECT title, classifier_label, classification_source "
            "FROM recordings WHERE plaud_id=?",
            (plaud_id,),
        ).fetchone()
        assert row[0] == "meeting on whatever"
        assert row[1] == "Školení"
        assert row[2] == "folder"
    finally:
        conn.close()
