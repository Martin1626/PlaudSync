"""Sync pipeline orchestration.

See docs/superpowers/specs/2026-04-25-sync-core-design.md.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path

import sentry_sdk
from loguru import logger

from plaudsync.categorization import ClassificationResult
from plaudsync.classifier import Classifier
from plaudsync.config import Config
from plaudsync.path_resolver import resolve_target_path
from plaudsync.plaud_client import (
    PlaudDownloadCorrupted,
)
from plaudsync.state import (
    finish_sync_run,
    last_successful_sync,
    record_recording,
    recording_exists_and_downloaded,
    start_sync_run,
)


_SLUG_RE = re.compile(r"[^\w\-]+", re.UNICODE)


def _slugify(title: str, max_len: int = 60) -> str:
    slug = _SLUG_RE.sub("_", title).strip("_")
    return slug[:max_len] or "untitled"


def run_sync(
    client,
    classifier: Classifier,
    conn: sqlite3.Connection,
    config: Config,
    trigger: str = "task_scheduler",
) -> int:
    run_id = start_sync_run(conn, trigger=trigger)
    since = last_successful_sync(conn)

    new_count = 0
    skipped_count = 0
    failed_count = 0

    for meta in client.list_recordings(since=since):
        if recording_exists_and_downloaded(conn, meta.plaud_id):
            skipped_count += 1
            continue
        try:
            _process_recording(meta, client, classifier, config, conn, run_id)
            new_count += 1
        except Exception as e:  # noqa: BLE001 — wide on purpose, we re-raise into Sentry
            logger.bind(recording_id=meta.plaud_id).exception("recording failed")
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("error_kind", "recording_failed")
                scope.set_tag("recording_id", meta.plaud_id)
                scope.fingerprint = ["recording_failed", type(e).__name__]
                sentry_sdk.capture_exception(e)
            record_recording(conn, meta, status="failed",
                             local_path="", run_id=run_id)
            failed_count += 1

    exit_code = 4 if failed_count > 0 else 0
    finish_sync_run(
        conn, run_id, exit_code=exit_code,
        recordings_new=new_count, recordings_skipped=skipped_count,
        recordings_failed=failed_count,
    )
    return exit_code


def _process_recording(
    meta,
    client,
    classifier: Classifier,
    config: Config,
    conn: sqlite3.Connection,
    run_id: int,
) -> None:
    label = classifier.classify(meta)
    if label == "_unclassified":
        result = ClassificationResult(status="unclassified", project=None, matched_date=None)
    else:
        created_dt = datetime.fromisoformat(meta.created_at.replace("Z", "+00:00"))
        result = ClassificationResult(
            status="matched", project=label, matched_date=created_dt.date()
        )

    # File name: {YYYY-MM-DD}_{slug}.mp3
    date_prefix = meta.created_at[:10]
    filename = f"{date_prefix}_{_slugify(meta.title)}.mp3"

    target_path = resolve_target_path(
        result, plaud_folder=meta.plaud_folder, config=config, filename=filename
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)

    bytes_written = 0
    with open(target_path, "wb") as f:
        for chunk in client.download_audio(meta.plaud_id):
            f.write(chunk)
            bytes_written += len(chunk)

    if meta.file_size and bytes_written != meta.file_size:
        # Partial-write cleanup.
        try:
            target_path.unlink()
        except OSError:
            pass
        raise PlaudDownloadCorrupted(
            f"size mismatch: expected={meta.file_size}, written={bytes_written}"
        )

    record_recording(
        conn, meta, status="downloaded",
        local_path=str(target_path), run_id=run_id,
        classifier_label=label,
    )
