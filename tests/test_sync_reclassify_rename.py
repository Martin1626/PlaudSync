"""Hotfix F (BL-X 2026-04-30) — _reclassify_recent re-evaluates downloaded
rows when Plaud-side title change implies a different project label.

Pre-fix: only ``classifier_label='_unclassified'`` rows entered reclassify.
A downloaded row labelled 'Test' (matched at first sync) stayed forever
in the Test project folder even when the user renamed it on Plaud to
'OEZ:'.

Hotfix F: live_metas dict (passed from run_sync) provides current title
per plaud_id. When live title differs from DB title, reclassify the row
against the live title. If new label is in config, move MP3 + .md
sourozenec to the new project dir + update DB.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from plaudsync.classifiers.name import NameClassifier
from plaudsync.config import Config, ProjectEntry
from plaudsync.state import open_state
from plaudsync.sync import _reclassify_recent


def _seed_downloaded_row(
    tmp_path: Path,
    *,
    plaud_id: str,
    title: str,
    created_at: str,
    local_path: str,
    classifier_label: str,
    content_path: str | None = None,
) -> sqlite3.Connection:
    conn = open_state(tmp_path)
    conn.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        (datetime.now(timezone.utc).isoformat(), "manual"),
    )
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, downloaded_at, "
        "local_path, classifier_label, status, sync_run_id, classification_source, "
        "content_status, content_path) "
        "VALUES (?, ?, ?, ?, ?, ?, 'downloaded', 1, 'name', "
        "?, ?)",
        (plaud_id, title, created_at, datetime.now(timezone.utc).isoformat(),
         local_path, classifier_label,
         "complete" if content_path else "not_applicable",
         content_path),
    )
    conn.commit()
    return conn


def _live(plaud_id: str, title: str):
    return SimpleNamespace(plaud_id=plaud_id, title=title)


def test_reclassify_moves_mp3_and_md_after_plaud_rename(tmp_path: Path) -> None:
    """User on Plaud renames '04-30 Test: …' → '04-30 OEZ: …'. PlaudSync's
    _reclassify_recent picks up live title from listing, re-classifies as
    OEZ, moves both MP3 + .md sourozenec to OEZ project folder, updates DB."""
    test_dir = tmp_path / "Testy"
    oez_dir = tmp_path / "OEZ"
    unclassified = tmp_path / "U"
    test_dir.mkdir()
    oez_dir.mkdir()
    unclassified.mkdir()

    config = Config(
        unclassified_dir=unclassified,
        projects={
            "Test": ProjectEntry(path=test_dir),
            "OEZ": ProjectEntry(path=oez_dir),
        },
    )

    # Seed: row downloaded as Test, both MP3 + .md in Testy/
    plaud_id = "rec_renamed_001"
    db_title = "04-30 Test: Úprava procesu picking finish"
    live_title = "04-30 OEZ: Úprava procesu picking finish"
    mp3_path = test_dir / "2026-04-30_04-30_Test_Uprava.mp3"
    md_path = test_dir / "2026-04-30_04-30_Test_Uprava.md"
    mp3_path.write_bytes(b"AAAA")
    md_path.write_text("# Old md content", encoding="utf-8")

    conn = _seed_downloaded_row(
        tmp_path, plaud_id=plaud_id, title=db_title,
        created_at="2026-04-30T08:00:00+00:00",
        local_path=str(mp3_path), classifier_label="Test",
        content_path=str(md_path),
    )

    live_metas = {plaud_id: _live(plaud_id, live_title)}

    moved, failed = _reclassify_recent(
        conn, NameClassifier(), config, run_id=1, live_metas=live_metas, days=14,
    )
    assert moved == 1
    assert failed == 0

    # Original files gone, both moved to OEZ/
    assert not mp3_path.exists()
    assert not md_path.exists()
    new_mp3 = oez_dir / "2026-04-30_04-30_Test_Uprava.mp3"  # filename preserved per design
    new_md = oez_dir / "2026-04-30_04-30_Test_Uprava.md"
    assert new_mp3.exists()
    assert new_md.exists()
    assert new_mp3.read_bytes() == b"AAAA"

    # DB row updated: label, paths, AND title (live title persisted).
    row = conn.execute(
        "SELECT title, classifier_label, local_path, content_path "
        "FROM recordings WHERE plaud_id = ?",
        (plaud_id,),
    ).fetchone()
    assert row[0] == live_title
    assert row[1] == "OEZ"
    assert row[2] == str(new_mp3)
    assert row[3] == str(new_md)
    conn.close()


def test_reclassify_unchanged_when_label_stays_same(tmp_path: Path) -> None:
    """Plaud-side rename within the same project (Test → Test still) doesn't
    trigger move but DOES persist title change."""
    test_dir = tmp_path / "Testy"
    unclassified = tmp_path / "U"
    test_dir.mkdir()
    unclassified.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"Test": ProjectEntry(path=test_dir)},
    )

    plaud_id = "rec_test_001"
    db_title = "04-30 Test: Old title"
    live_title = "04-30 Test: Updated description"
    mp3_path = test_dir / "rec.mp3"
    mp3_path.write_bytes(b"X")

    conn = _seed_downloaded_row(
        tmp_path, plaud_id=plaud_id, title=db_title,
        created_at="2026-04-30T08:00:00+00:00",
        local_path=str(mp3_path), classifier_label="Test",
    )

    moved, failed = _reclassify_recent(
        conn, NameClassifier(), config, run_id=1,
        live_metas={plaud_id: _live(plaud_id, live_title)}, days=14,
    )
    assert moved == 0  # No file move — same label
    assert failed == 0
    assert mp3_path.exists()  # Still in original location

    # Title persisted to DB even though no move happened.
    row = conn.execute(
        "SELECT title FROM recordings WHERE plaud_id = ?", (plaud_id,),
    ).fetchone()
    assert row[0] == live_title
    conn.close()


def test_reclassify_skips_when_new_label_not_in_config(tmp_path: Path) -> None:
    """Plaud rename to a project NOT in config — leave the row alone (BL-3
    semantic: user must add project before move happens)."""
    test_dir = tmp_path / "Testy"
    unclassified = tmp_path / "U"
    test_dir.mkdir()
    unclassified.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"Test": ProjectEntry(path=test_dir)},  # OEZ NOT in config
    )

    plaud_id = "rec_unknown_001"
    mp3_path = test_dir / "rec.mp3"
    mp3_path.write_bytes(b"X")

    conn = _seed_downloaded_row(
        tmp_path, plaud_id=plaud_id, title="04-30 Test: original",
        created_at="2026-04-30T08:00:00+00:00",
        local_path=str(mp3_path), classifier_label="Test",
    )

    moved, failed = _reclassify_recent(
        conn, NameClassifier(), config, run_id=1,
        live_metas={plaud_id: _live(plaud_id, "04-30 OEZ: renamed")}, days=14,
    )
    assert moved == 0  # No move — OEZ not in config
    assert failed == 0
    assert mp3_path.exists()

    # Label stays Test; title NOT updated either (label-classify failed,
    # so we don't trust the new title for now — BL-3 retry path will
    # pick it up via _retry_skipped_unknown_project after user adds OEZ).
    row = conn.execute(
        "SELECT title, classifier_label FROM recordings WHERE plaud_id = ?",
        (plaud_id,),
    ).fetchone()
    assert row[1] == "Test"
    conn.close()


def test_reclassify_skips_when_no_live_title_change(tmp_path: Path) -> None:
    """Hot-path optimization: row with current_label != _unclassified AND
    live title matches DB title → skip the per-row classify (cheap)."""
    test_dir = tmp_path / "Testy"
    unclassified = tmp_path / "U"
    test_dir.mkdir()
    unclassified.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"Test": ProjectEntry(path=test_dir)},
    )

    plaud_id = "rec_stable_001"
    title = "04-30 Test: stable"
    mp3_path = test_dir / "rec.mp3"
    mp3_path.write_bytes(b"X")

    conn = _seed_downloaded_row(
        tmp_path, plaud_id=plaud_id, title=title,
        created_at="2026-04-30T08:00:00+00:00",
        local_path=str(mp3_path), classifier_label="Test",
    )

    moved, failed = _reclassify_recent(
        conn, NameClassifier(), config, run_id=1,
        live_metas={plaud_id: _live(plaud_id, title)}, days=14,  # same title
    )
    assert moved == 0
    assert failed == 0
    conn.close()


def test_reclassify_legacy_unclassified_path_still_works(tmp_path: Path) -> None:
    """BL-3 era behavior preserved: row with classifier_label='_unclassified'
    + name regex now matches → move to project folder."""
    alza_dir = tmp_path / "ALZA"
    unclassified = tmp_path / "Unclassified"
    alza_dir.mkdir()
    unclassified.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": ProjectEntry(path=alza_dir)},
    )

    plaud_id = "rec_legacy_001"
    src_path = unclassified / "old.mp3"
    src_path.write_bytes(b"X")

    conn = _seed_downloaded_row(
        tmp_path, plaud_id=plaud_id, title="04-29 ALZA: kickoff",
        created_at="2026-04-29T08:00:00+00:00",
        local_path=str(src_path), classifier_label="_unclassified",
    )

    # No live_metas — pure legacy path (DB title is authoritative).
    moved, failed = _reclassify_recent(
        conn, NameClassifier(), config, run_id=1, days=14,
    )
    assert moved == 1
    assert failed == 0
    assert (alza_dir / "old.mp3").exists()
    conn.close()
