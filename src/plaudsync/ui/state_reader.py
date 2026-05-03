"""Read-only SQLite queries for GET /api/state.

Reads sync_runs (current + last) and recordings (last 50 by downloaded_at).
Never writes - UI subprocess is the only writer to recordings/sync_runs.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Literal, TypedDict


class SyncProgressPayload(TypedDict):
    phase: str | None
    processed_count: int | None
    total_count: int | None


class SyncStatePayload(TypedDict):
    status: Literal["idle", "running"]
    trigger: str | None
    started_at: str | None
    last_run_at: str | None
    last_run_outcome: Literal["success", "partial_failure", "failed"] | None
    last_run_exit_code: int | None
    last_run_new_count: int | None
    last_run_skipped_count: int | None
    last_run_failed_count: int | None
    last_error_summary: str | None
    progress: SyncProgressPayload | None


class RecordingRowPayload(TypedDict):
    plaud_id: str
    title: str
    created_at: str
    downloaded_at: str
    plaud_folder: str
    classification_status: Literal["matched", "unclassified"]
    project: str | None
    target_dir: str
    status: Literal["downloaded", "failed", "skipped"]
    # BL-6: source-aware project badge.
    # BL-7: 'skip' added — recording fell through all strategies +
    # sync_unclassified=false; persisted with status='skipped' and surfaced
    # as a gray "ignorováno" pill so the user has a visible signal.
    classification_source: Literal["name", "folder", "none", "skip"] | None
    plaud_folder_name: str | None


class StateResponsePayload(TypedDict):
    sync: SyncStatePayload
    recordings: list[RecordingRowPayload]


def _outcome_for_exit_code(
    exit_code: int | None,
) -> Literal["success", "partial_failure", "failed"] | None:
    if exit_code is None:
        return None
    if exit_code == 0:
        return "success"
    if exit_code == 4:
        return "partial_failure"
    return "failed"


def _read_running(conn: sqlite3.Connection) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT started_at, trigger FROM sync_runs "
        "WHERE finished_at IS NULL ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return (row[0], row[1]) if row else None


def _read_last_finished(conn: sqlite3.Connection) -> tuple[str, int, int, int, int] | None:
    row = conn.execute(
        "SELECT finished_at, exit_code, recordings_new, recordings_skipped, "
        "recordings_failed FROM sync_runs "
        "WHERE finished_at IS NOT NULL ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return (row[0], row[1], row[2], row[3], row[4]) if row else None


def _read_recordings(
    conn: sqlite3.Connection,
    state_root: Path | None = None,
) -> list[RecordingRowPayload]:
    # Newest recording on top: order by Plaud-side creation time (when the user
    # actually recorded). downloaded_at is a tie-breaker for batches whose
    # created_at_plaud is identical or missing.
    rows = conn.execute(
        "SELECT plaud_id, title, created_at_plaud, downloaded_at, "
        "local_path, classifier_label, status, classification_source, "
        "plaud_folder_id "
        "FROM recordings ORDER BY created_at_plaud DESC, downloaded_at DESC "
        "LIMIT 50"
    ).fetchall()

    # BL-6: load FiletagCache once per snapshot for O(1) lookup_by_id calls.
    # Empty list when state_root not provided (defensive — used by some test
    # fixtures that don't pass it) or when cache file missing/unreadable.
    folder_name_by_id: dict[str, str] = {}
    if state_root is not None:
        from plaudsync.filetag_cache import FiletagCache
        cache = FiletagCache(state_root)
        for f in (cache.load() or []):
            folder_name_by_id[f.id] = f.name

    # BL-6 follow-up: resolve canonical project name from config.yaml.
    # Recording's classifier_label is whatever case the title used ('Foxconn'
    # vs 'FOXCONN'), but the badge should always show the configured key.
    # Build a casefold→canonical map once per snapshot. Config IO failure
    # (broken YAML, missing file) falls back to the raw label — degraded
    # but non-blocking; user fixes in Settings.
    project_canonical_by_casefold: dict[str, str] = {}
    if state_root is not None:
        try:
            from plaudsync.config import load_config
            cfg = load_config(state_root)
            for key in cfg.projects:
                project_canonical_by_casefold[key.casefold()] = key
        except Exception:  # noqa: BLE001 — best-effort UI render
            pass

    payload: list[RecordingRowPayload] = []
    for r in rows:
        (plaud_id, title, created_at, downloaded_at, local_path, label, status,
         classification_source, plaud_folder_id) = r
        is_unclassified = label == "_unclassified"
        # local_path is the file path; the Dashboard wants the parent directory.
        target_dir = str(Path(local_path).parent) if local_path else ""
        # Collapse engine-internal 'skipped_unknown_project' to wire 'skipped'.
        # DB keeps the distinct value so the retry pass at sync.py:148 can find
        # these rows after the user adds the missing project to config.yaml.
        wire_status = "skipped" if status == "skipped_unknown_project" else status

        # BL-6: resolve folder name. Cache miss for folder-classified row
        # → empty string sentinel (frontend renders '(neznámá složka)').
        # plaud_folder_id NULL OR no state_root (cache unreachable) → None.
        plaud_folder_name: str | None
        if plaud_folder_id is None or state_root is None:
            plaud_folder_name = None
        else:
            resolved = folder_name_by_id.get(plaud_folder_id)
            if resolved is not None:
                plaud_folder_name = resolved
            elif classification_source == "folder":
                plaud_folder_name = ""  # cache-miss sentinel
            else:
                plaud_folder_name = None

        # Folder-icon row (left of badge) shows the Plaud folder NAME for
        # any recording where we can resolve it via FiletagCache. Pre-BL-6
        # rows with NULL plaud_folder_id, cache-miss rows, and rows synced
        # before classification get an empty string — frontend renders "—".
        # The legacy "_unknown" sentinel is no longer surfaced to the UI.
        if plaud_folder_id is None or state_root is None:
            plaud_folder_display = ""
        else:
            plaud_folder_display = folder_name_by_id.get(plaud_folder_id, "")

        # Project text for the badge: use the configured canonical key when
        # the label matches case-insensitively. Falls back to the raw label
        # for unclassified rows or when config can't resolve (legacy /
        # project removed from config after sync).
        if is_unclassified:
            project_display: str | None = None
        else:
            project_display = (
                project_canonical_by_casefold.get(label.casefold(), label)
            )

        payload.append({
            "plaud_id": plaud_id,
            "title": title,
            "created_at": created_at,
            "downloaded_at": downloaded_at,
            "plaud_folder": plaud_folder_display,
            "classification_status": "unclassified" if is_unclassified else "matched",
            "project": project_display,
            "target_dir": target_dir,
            "status": wire_status,
            "classification_source": classification_source,
            "plaud_folder_name": plaud_folder_name,
        })
    return payload


def _read_progress_for_running(
    state_root: Path | None, running: tuple[str, str] | None,
) -> SyncProgressPayload | None:
    """Return progress payload only when a sync_run is open AND progress.json
    exists. Stale files (no open run) are ignored to handle subprocess crashes.
    """
    if state_root is None or running is None:
        return None
    from plaudsync.progress import read_progress
    payload = read_progress(state_root)
    if payload is None:
        return None
    return {
        "phase": payload.get("phase"),
        "processed_count": payload.get("processed_count"),
        "total_count": payload.get("total_count"),
    }


def read_state_snapshot(
    conn: sqlite3.Connection,
    state_root: Path | None = None,
) -> StateResponsePayload:
    running = _read_running(conn)
    last_finished = _read_last_finished(conn)
    progress = _read_progress_for_running(state_root, running)

    last_counts = (
        (last_finished[2], last_finished[3], last_finished[4])
        if last_finished else (None, None, None)
    )

    if running:
        started_at, trigger = running
        sync: SyncStatePayload = {
            "status": "running",
            "trigger": trigger,
            "started_at": started_at,
            "last_run_at": last_finished[0] if last_finished else None,
            "last_run_outcome": _outcome_for_exit_code(last_finished[1]) if last_finished else None,
            "last_run_exit_code": last_finished[1] if last_finished else None,
            "last_run_new_count": last_counts[0],
            "last_run_skipped_count": last_counts[1],
            "last_run_failed_count": last_counts[2],
            "last_error_summary": None,
            "progress": progress,
        }
    else:
        sync = {
            "status": "idle",
            "trigger": None,
            "started_at": None,
            "last_run_at": last_finished[0] if last_finished else None,
            "last_run_outcome": _outcome_for_exit_code(last_finished[1]) if last_finished else None,
            "last_run_exit_code": last_finished[1] if last_finished else None,
            "last_run_new_count": last_counts[0],
            "last_run_skipped_count": last_counts[1],
            "last_run_failed_count": last_counts[2],
            "last_error_summary": None,
            "progress": None,
        }

    return {"sync": sync, "recordings": _read_recordings(conn, state_root)}


def read_running_started_at(conn: sqlite3.Connection) -> str | None:
    running = _read_running(conn)
    return running[0] if running else None


def read_running_trigger(conn: sqlite3.Connection) -> str | None:
    running = _read_running(conn)
    return running[1] if running else None
