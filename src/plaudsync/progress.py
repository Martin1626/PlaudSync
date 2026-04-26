"""File-based sync progress tracking.

Sync subprocess writes a small JSON payload at well-defined points in the
run lifecycle; the UI process polls /api/state which reads this file.
Atomic write via os.replace so the reader never sees a half-written file.

Schema:
    {
        "sync_run_id": int,
        "phase": "listing" | "downloading" | "finalizing",
        "processed_count": int | None,
        "total_count": int | None,
        "updated_at": "<ISO-8601 UTC>"
    }
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


Phase = Literal["listing", "downloading", "finalizing"]


def progress_path(state_root: Path) -> Path:
    return state_root / ".plaudsync" / "progress.json"


def write_progress(
    state_root: Path,
    *,
    sync_run_id: int,
    phase: Phase,
    processed_count: int | None,
    total_count: int | None,
) -> None:
    """Atomically write progress payload to state_root/.plaudsync/progress.json.

    Uses tmp file in the same directory + os.replace for cross-platform atomicity
    (Windows + POSIX). Reader sees either the previous complete payload or the
    new complete payload — never a half-written one.
    """
    target = progress_path(state_root)
    target.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "sync_run_id": sync_run_id,
        "phase": phase,
        "processed_count": processed_count,
        "total_count": total_count,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    fd, tmp_path = tempfile.mkstemp(
        prefix=".progress.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
            f.flush()
            os.fsync(f.fileno())
        # Windows: os.replace can transiently fail with PermissionError when
        # a reader has the destination briefly open. Retry with short backoff.
        for attempt in range(20):
            try:
                os.replace(tmp_path, target)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.001 * (attempt + 1))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_progress(state_root: Path) -> dict | None:
    target = progress_path(state_root)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def clear_progress(state_root: Path) -> None:
    """Remove progress.json. No-op when file does not exist."""
    target = progress_path(state_root)
    try:
        target.unlink()
    except FileNotFoundError:
        pass
