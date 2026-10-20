"""One-off, throttled, resumable speaker pass over an older period (spec §5.7)."""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from plaudsync.config import Config
from plaudsync.speakers.gallery import recompute_flags
from plaudsync.speakers.runner import (
    _SCOPE,
    SpeakerPassResult,
    _report,
    learn_recording,
    make_context,
    name_recording,
)


class _Throttled:
    """Client proxy: every call sleeps first, so backfill stays gentle on Plaud."""

    def __init__(self, client: Any, delay: float) -> None:
        self._client = client
        self._delay = delay

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._client, name)
        if not callable(attr):
            return attr

        def call(*args: Any, **kwargs: Any) -> Any:
            time.sleep(self._delay)
            return attr(*args, **kwargs)

        return call


def run_backfill(
    conn: sqlite3.Connection,
    client: Any,
    config: Config,
    state_root: Path,
    *,
    since: date,
    delay: float = 1.0,
    now: datetime | None = None,
) -> SpeakerPassResult:
    ctx = make_context(
        conn, _Throttled(client, delay), config, state_root, now=now, via_backfill=True
    )
    result = ctx.result
    since_iso = datetime(since.year, since.month, since.day, tzinfo=timezone.utc).isoformat()

    new_ids = [r[0] for r in conn.execute(
        "SELECT r.plaud_id FROM recordings r "
        "LEFT JOIN speaker_recordings s ON s.plaud_id = r.plaud_id "
        f"WHERE {_SCOPE} AND r.created_at_plaud >= ? AND s.plaud_id IS NULL "  # nosec B608
        "ORDER BY r.created_at_plaud",
        (since_iso,),
    )]
    if new_ids:
        try:
            ctx.extractor_factory()
        except Exception as exc:  # noqa: BLE001 — no model: no learning, still name
            _report(exc, None)
            result.failed += 1
            new_ids = []

    # Phase 1: learn everything first, so early recordings can be named from later ones.
    for plaud_id in new_ids:
        try:
            labels = learn_recording(ctx, plaud_id)
            if labels is None:
                continue  # no transcript yet; stays unprocessed
            conn.execute(
                "INSERT INTO speaker_recordings (plaud_id, labels, written, edit_marker, "
                "checked_at, state) VALUES (?, ?, '{}', NULL, ?, 'learned')",
                (plaud_id, json.dumps(labels), ctx.now.isoformat()),
            )
            conn.commit()
        except Exception as exc:  # noqa: BLE001 — one recording must not stop the rest
            _report(exc, plaud_id)
            result.failed += 1

    # Phase 2: name. Re-selected from the DB, so an interrupted run resumes here.
    pending = conn.execute(
        "SELECT s.plaud_id, s.labels FROM speaker_recordings s "
        "JOIN recordings r ON r.plaud_id = s.plaud_id "
        f"WHERE s.state = 'learned' AND {_SCOPE} AND r.created_at_plaud >= ? "  # nosec B608
        "ORDER BY r.created_at_plaud",
        (since_iso,),
    ).fetchall()
    for plaud_id, labels_json in pending:
        try:
            result.named += name_recording(ctx, plaud_id, json.loads(labels_json))
            conn.execute(
                "UPDATE speaker_recordings SET state='done', checked_at=? WHERE plaud_id=?",
                (ctx.now.isoformat(), plaud_id),
            )
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            _report(exc, plaud_id)
            result.failed += 1

    if ctx.touched:
        recompute_flags(conn, ctx.touched, window_cutoff=ctx.window_cutoff)
    logger.bind(named=result.named, failed=result.failed).info("speaker backfill finished")
    return result
