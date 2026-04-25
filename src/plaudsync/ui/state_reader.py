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


def _read_last_finished(conn: sqlite3.Connection) -> tuple[str, int] | None:
    row = conn.execute(
        "SELECT finished_at, exit_code FROM sync_runs "
        "WHERE finished_at IS NOT NULL ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return (row[0], row[1]) if row else None


def _read_recordings(conn: sqlite3.Connection) -> list[RecordingRowPayload]:
    rows = conn.execute(
        "SELECT plaud_id, title, created_at_plaud, downloaded_at, "
        "local_path, classifier_label, status "
        "FROM recordings ORDER BY downloaded_at DESC LIMIT 50"
    ).fetchall()
    payload: list[RecordingRowPayload] = []
    for r in rows:
        plaud_id, title, created_at, downloaded_at, local_path, label, status = r
        is_unclassified = label == "_unclassified"
        # local_path is the file path; the Dashboard wants the parent directory.
        target_dir = str(Path(local_path).parent) if local_path else ""
        payload.append({
            "plaud_id": plaud_id,
            "title": title,
            "created_at": created_at,
            "downloaded_at": downloaded_at,
            "plaud_folder": "_unknown",  # not currently persisted; v0 ships "_unknown" per Dashboard spec Gap 2
            "classification_status": "unclassified" if is_unclassified else "matched",
            "project": None if is_unclassified else label,
            "target_dir": target_dir,
            "status": status,
        })
    return payload


def read_state_snapshot(conn: sqlite3.Connection) -> StateResponsePayload:
    running = _read_running(conn)
    last_finished = _read_last_finished(conn)

    if running:
        started_at, trigger = running
        sync: SyncStatePayload = {
            "status": "running",
            "trigger": trigger,
            "started_at": started_at,
            "last_run_at": last_finished[0] if last_finished else None,
            "last_run_outcome": _outcome_for_exit_code(last_finished[1]) if last_finished else None,
            "last_run_exit_code": last_finished[1] if last_finished else None,
            "last_error_summary": None,
            "progress": None,
        }
    else:
        sync = {
            "status": "idle",
            "trigger": None,
            "started_at": None,
            "last_run_at": last_finished[0] if last_finished else None,
            "last_run_outcome": _outcome_for_exit_code(last_finished[1]) if last_finished else None,
            "last_run_exit_code": last_finished[1] if last_finished else None,
            "last_error_summary": None,
            "progress": None,
        }

    return {"sync": sync, "recordings": _read_recordings(conn)}


def read_running_started_at(conn: sqlite3.Connection) -> str | None:
    running = _read_running(conn)
    return running[0] if running else None


def read_running_trigger(conn: sqlite3.Connection) -> str | None:
    running = _read_running(conn)
    return running[1] if running else None
