"""Fix A — retry_skipped_unknown_project re-classifies against LIVE Plaud
title (from listing) instead of stale DB title.

Scenario: recording uploaded with name 'Konzultace: …' → BL-3 skip → user
renames on Plaud to 'OEZ: …' → next sync's retry pass must pick up the
new title. Without this, retry pass loops on stale DB title forever and
recording stays skipped.

Bug discovered 2026-04-30 (real-world: 04-30 Konzultace renamed to OEZ).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from plaudsync.classifiers.name import NameClassifier
from plaudsync.config import Config, ProjectEntry
from plaudsync.state import open_state
from plaudsync.sync import _retry_skipped_unknown_project


def _recent_iso(*, days_ago: int = 1) -> str:
    """created_at within _retry_skipped_unknown_project's rolling `days` window.

    Must be relative to now, NOT a hard-coded date: the retry pass only selects
    rows with created_at_plaud >= now-`days`, so an absolute date silently ages
    out of the window and the SELECT returns zero rows (downloaded == 0).
    """
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _seed_skipped(
    tmp_path: Path, *, plaud_id: str, db_title: str, created_at: str,
) -> sqlite3.Connection:
    conn = open_state(tmp_path)
    conn.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        (datetime.now(timezone.utc).isoformat(), "manual"),
    )
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, downloaded_at, "
        "local_path, classifier_label, status, sync_run_id, file_size) "
        "VALUES (?, ?, ?, ?, '', 'Konzultace', 'skipped_unknown_project', 1, 1024)",
        (plaud_id, db_title, created_at,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return conn


def _live_meta(plaud_id: str, title: str, plaud_folder: str = "_unknown"):
    return SimpleNamespace(
        plaud_id=plaud_id,
        title=title,
        created_at="2026-04-30T05:15:03+00:00",
        start_time_ms=1745000000000,
        duration_seconds=1800,
        file_size=1024,
        plaud_folder=plaud_folder,
    )


def test_retry_uses_live_title_after_plaud_rename(tmp_path: Path) -> None:
    """User renamed 'Konzultace: …' → 'OEZ: …' on Plaud after first sync skip.
    Retry pass must pick up live title and download into OEZ project."""
    project_dir = tmp_path / "OEZ"
    unclassified = tmp_path / "U"
    project_dir.mkdir()
    unclassified.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"OEZ": ProjectEntry(path=project_dir)},
    )

    plaud_id = "rec_renamed_001"
    db_title = "04-30 Konzultace: úprava layoutu"
    live_title = "04-30 OEZ: Úprava layoutu stanice s AGV"

    conn = _seed_skipped(
        tmp_path, plaud_id=plaud_id, db_title=db_title,
        created_at=_recent_iso(),
    )

    # spec=["download_audio"] limits MagicMock attribute set so hasattr(
    # client, "fetch_detail") is False — content fetch path is skipped.
    client = MagicMock(spec=["download_audio"])
    client.download_audio.return_value = iter([b"A" * 1024])

    live_metas = {plaud_id: _live_meta(plaud_id, live_title)}

    downloaded, failed = _retry_skipped_unknown_project(
        conn, client, NameClassifier(), config, run_id=1,
        live_metas=live_metas, days=14,
    )
    assert downloaded == 1
    assert failed == 0

    # MP3 lands in OEZ project folder + DB row updated to live title
    mp3 = list(project_dir.rglob("*.mp3"))
    assert len(mp3) == 1
    # Filename slug derives from LIVE title, not DB title
    assert "OEZ" in mp3[0].stem or "rava" in mp3[0].stem.lower()

    row = conn.execute(
        "SELECT title, status, classifier_label FROM recordings WHERE plaud_id = ?",
        (plaud_id,),
    ).fetchone()
    assert row[0] == live_title
    assert row[1] == "downloaded"
    assert row[2] == "OEZ"
    conn.close()


def test_retry_falls_back_to_db_title_when_live_meta_absent(tmp_path: Path) -> None:
    """Recording removed/trashed on Plaud — live_metas dict has no entry.
    Retry pass falls back to DB title (existing pre-fix behavior)."""
    project_dir = tmp_path / "ALZA"
    unclassified = tmp_path / "U"
    project_dir.mkdir()
    unclassified.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": ProjectEntry(path=project_dir)},
    )

    plaud_id = "rec_removed_001"
    db_title = "04-30 ALZA: kickoff"
    conn = _seed_skipped(
        tmp_path, plaud_id=plaud_id, db_title=db_title,
        created_at=_recent_iso(),
    )

    # spec=["download_audio"] limits MagicMock attribute set so hasattr(
    # client, "fetch_detail") is False — content fetch path is skipped.
    client = MagicMock(spec=["download_audio"])
    client.download_audio.return_value = iter([b"A" * 1024])

    # live_metas={} simulates Plaud-side removal/trash
    downloaded, failed = _retry_skipped_unknown_project(
        conn, client, NameClassifier(), config, run_id=1,
        live_metas={}, days=14,
    )
    assert downloaded == 1  # DB title was already valid → still works
    conn.close()


def test_retry_works_when_live_metas_is_none(tmp_path: Path) -> None:
    """Pre-Fix-A callers passing live_metas=None must keep working."""
    project_dir = tmp_path / "ALZA"
    unclassified = tmp_path / "U"
    project_dir.mkdir()
    unclassified.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": ProjectEntry(path=project_dir)},
    )

    plaud_id = "rec_default_001"
    conn = _seed_skipped(
        tmp_path, plaud_id=plaud_id, db_title="04-30 ALZA: kickoff",
        created_at=_recent_iso(),
    )

    # spec=["download_audio"] limits MagicMock attribute set so hasattr(
    # client, "fetch_detail") is False — content fetch path is skipped.
    client = MagicMock(spec=["download_audio"])
    client.download_audio.return_value = iter([b"A" * 1024])

    downloaded, failed = _retry_skipped_unknown_project(
        conn, client, NameClassifier(), config, run_id=1, days=14,
        # live_metas not passed — defaults to None
    )
    assert downloaded == 1
    conn.close()


def test_retry_recovers_renamed_unclassified_skip(tmp_path: Path) -> None:
    """A plain 'skipped' (unclassified) recording renamed on Plaud so its title
    now matches a configured project must be recovered by the retry pass within
    the window — the main loop no longer re-checks skips."""
    project_dir = tmp_path / "OEZ"; unclassified = tmp_path / "U"
    project_dir.mkdir(); unclassified.mkdir()
    config = Config(unclassified_dir=unclassified,
                    projects={"OEZ": ProjectEntry(path=project_dir)})

    plaud_id = "rec_uncl_001"
    conn = open_state(tmp_path)
    conn.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        (datetime.now(timezone.utc).isoformat(), "manual"),
    )
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, downloaded_at, "
        "local_path, classifier_label, classification_source, status, sync_run_id, file_size) "
        "VALUES (?, ?, ?, ?, '', '_unclassified', 'skip', 'skipped', 1, 1024)",
        (plaud_id, "2026-05-20 09:12:46", _recent_iso(),
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()

    client = MagicMock(spec=["download_audio"])
    client.download_audio.return_value = iter([b"A" * 1024])
    live_metas = {plaud_id: _live_meta(plaud_id, "05-20 OEZ: Úprava layoutu")}

    downloaded, failed = _retry_skipped_unknown_project(
        conn, client, NameClassifier(), config, run_id=1,
        live_metas=live_metas, days=14,
    )
    assert downloaded == 1
    row = conn.execute(
        "SELECT status, classifier_label FROM recordings WHERE plaud_id = ?",
        (plaud_id,),
    ).fetchone()
    assert row == ("downloaded", "OEZ")
    conn.close()


def test_retry_recovers_skip_after_folder_move(tmp_path: Path) -> None:
    """A plain 'skipped' recording moved into a project-mapped Plaud folder is
    recovered via folder fallback within the window (classify_by_folder=true)."""
    project_dir = tmp_path / "OEZ"; unclassified = tmp_path / "U"
    project_dir.mkdir(); unclassified.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"OEZ": ProjectEntry(path=project_dir, plaud_folder_id="fld_oez")},
        classify_by_folder=True,
    )

    plaud_id = "rec_folder_move"
    conn = open_state(tmp_path)
    conn.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        (datetime.now(timezone.utc).isoformat(), "manual"),
    )
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, downloaded_at, "
        "local_path, classifier_label, classification_source, status, sync_run_id, file_size) "
        "VALUES (?, ?, ?, ?, '', '_unclassified', 'skip', 'skipped', 1, 1024)",
        (plaud_id, "2026-05-20 09:12:46", _recent_iso(),
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()

    client = MagicMock(spec=["download_audio"])
    client.download_audio.return_value = iter([b"A" * 1024])
    live_metas = {plaud_id: _live_meta(plaud_id, "2026-05-20 09:12:46", plaud_folder="fld_oez")}

    downloaded, failed = _retry_skipped_unknown_project(
        conn, client, NameClassifier(), config, run_id=1,
        live_metas=live_metas, days=14,
    )
    assert downloaded == 1
    row = conn.execute(
        "SELECT status, classifier_label, classification_source FROM recordings WHERE plaud_id = ?",
        (plaud_id,),
    ).fetchone()
    assert row == ("downloaded", "OEZ", "folder")
    conn.close()


def test_retry_ignores_artifact_disabled_matched_skip(tmp_path: Path) -> None:
    """A recording matched to a known project but skipped because BOTH artifact
    toggles are off (classification_source='name') must NOT be re-downloaded by
    the retry pass — that would override the user's download_audio=false."""
    project_dir = tmp_path / "OEZ"; unclassified = tmp_path / "U"
    project_dir.mkdir(); unclassified.mkdir()
    config = Config(unclassified_dir=unclassified,
                    projects={"OEZ": ProjectEntry(path=project_dir)},
                    download_audio=False, download_content=False)

    plaud_id = "rec_artifact_off"
    conn = open_state(tmp_path)
    conn.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        (datetime.now(timezone.utc).isoformat(), "manual"),
    )
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, downloaded_at, "
        "local_path, classifier_label, classification_source, status, sync_run_id, file_size) "
        "VALUES (?, ?, ?, ?, '', 'OEZ', 'name', 'skipped', 1, 1024)",
        (plaud_id, "05-20 OEZ: schuzka", _recent_iso(),
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()

    client = MagicMock(spec=["download_audio"])
    client.download_audio.return_value = iter([b"A" * 1024])
    live_metas = {plaud_id: _live_meta(plaud_id, "05-20 OEZ: schuzka")}

    downloaded, failed = _retry_skipped_unknown_project(
        conn, client, NameClassifier(), config, run_id=1,
        live_metas=live_metas, days=14,
    )
    assert downloaded == 0
    client.download_audio.assert_not_called()
    row = conn.execute(
        "SELECT status FROM recordings WHERE plaud_id = ?", (plaud_id,)
    ).fetchone()
    assert row[0] == "skipped"
    conn.close()
