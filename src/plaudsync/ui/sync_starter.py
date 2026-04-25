"""Spawn sync subprocess + 500 ms lock-detection window.

POST /api/sync/start handler routes the result kind to HTTP status:
- "started"        -> 202
- "conflict"       -> 409
- "spawn_failed"   -> 500
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict

from plaudsync.ui.state_reader import (
    read_running_started_at,
    read_running_trigger,
)


class StartedPayload(TypedDict):
    kind: Literal["started"]
    sync_id: str
    started_at: str


class ConflictPayload(TypedDict):
    kind: Literal["conflict"]
    reason: Literal["already_running"]
    started_at: str
    by: str


class SpawnFailedPayload(TypedDict):
    kind: Literal["spawn_failed"]
    exit_code: int


def start_sync_subprocess(
    state_root: Path,
    conn: sqlite3.Connection,
) -> StartedPayload | ConflictPayload | SpawnFailedPayload:
    env = {
        **os.environ,
        "PLAUDSYNC_TRIGGER": "ui_sync_now",
        "PLAUDSYNC_STATE_ROOT": str(state_root),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "plaudsync"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        proc.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        return {
            "kind": "started",
            "sync_id": str(uuid.uuid4()),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

    if proc.returncode == 5:
        # Lock held by another process — Task Scheduler or another UI.
        return {
            "kind": "conflict",
            "reason": "already_running",
            "started_at": read_running_started_at(conn) or "",
            "by": read_running_trigger(conn) or "",
        }

    return {"kind": "spawn_failed", "exit_code": int(proc.returncode or 0)}
