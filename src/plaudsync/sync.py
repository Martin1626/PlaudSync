"""Sync pipeline orchestration.

See docs/superpowers/specs/2026-04-25-sync-core-design.md.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
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


def _reclassify_recent(
    conn: sqlite3.Connection,
    classifier: Classifier,
    config: Config,
    run_id: int,
    *,
    days: int = 14,
) -> tuple[int, int]:
    """Re-classify recordings with classifier_label='_unclassified' and
    downloaded_at within the last `days` days. Move physical files to new
    target paths and update DB. Returns (moved_count, failed_count).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    rows = conn.execute(
        "SELECT plaud_id, title, created_at_plaud, local_path "
        "FROM recordings "
        "WHERE classifier_label = '_unclassified' "
        "AND status = 'downloaded' "
        "AND downloaded_at >= ?",
        (cutoff,),
    ).fetchall()

    moved = 0
    failed = 0
    for plaud_id, title, created_at, old_local_path in rows:
        try:
            class _MetaLike:
                pass
            meta_like = _MetaLike()
            meta_like.title = title  # type: ignore[attr-defined]
            meta_like.created_at = created_at  # type: ignore[attr-defined]

            label = classifier.classify(meta_like)
            if label == "_unclassified":
                continue

            old_path = Path(old_local_path)
            if not old_path.exists():
                logger.bind(recording_id=plaud_id).warning(
                    "reclassify skipped: source file missing"
                )
                continue

            result = ClassificationResult(
                status="matched", project=label, matched_date=None,
            )
            new_path = resolve_target_path(
                result,
                plaud_folder="(reclassify)",
                config=config,
                filename=old_path.name,
            )
            if new_path == old_path:
                # Path unchanged — just update label.
                conn.execute(
                    "UPDATE recordings SET classifier_label = ? WHERE plaud_id = ?",
                    (label, plaud_id),
                )
                conn.commit()
                continue

            if new_path.exists():
                logger.bind(recording_id=plaud_id).warning(
                    "reclassify skipped: target path already exists"
                )
                continue

            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)
            conn.execute(
                "UPDATE recordings SET classifier_label = ?, local_path = ? "
                "WHERE plaud_id = ?",
                (label, str(new_path), plaud_id),
            )
            conn.commit()
            moved += 1
        except Exception as e:  # noqa: BLE001
            logger.bind(recording_id=plaud_id).exception("reclassify failed")
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("error_kind", "reclassify_failed")
                scope.set_tag("recording_id", plaud_id)
                scope.fingerprint = ["reclassify_failed", type(e).__name__]
                sentry_sdk.capture_exception(e)
            failed += 1

    return moved, failed


def _retry_skipped_unknown_project(
    conn: sqlite3.Connection,
    client,
    classifier: Classifier,
    config: Config,
    run_id: int,
    *,
    days: int = 14,
) -> tuple[int, int]:
    """Re-evaluate rows with status='skipped_unknown_project' and
    created_at_plaud within the last `days` days. If the project is now
    present in config, download the audio and update the row.
    Returns (downloaded_count, failed_count).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    rows = conn.execute(
        "SELECT plaud_id, title, created_at_plaud, file_size "
        "FROM recordings "
        "WHERE status = 'skipped_unknown_project' "
        "AND created_at_plaud >= ?",
        (cutoff,),
    ).fetchall()

    downloaded = 0
    failed = 0
    for plaud_id, title, created_at, expected_size in rows:
        try:
            class _MetaLike:
                pass
            meta_like = _MetaLike()
            meta_like.plaud_id = plaud_id  # type: ignore[attr-defined]
            meta_like.title = title  # type: ignore[attr-defined]
            meta_like.created_at = created_at  # type: ignore[attr-defined]

            label = classifier.classify(meta_like)
            if label == "_unclassified" or config.lookup_project(label) is None:
                continue

            result = ClassificationResult(
                status="matched", project=label, matched_date=None,
            )
            date_prefix = created_at[:10]
            filename = f"{date_prefix}_{_slugify(title)}.mp3"
            target_path = resolve_target_path(
                result, plaud_folder="(retry)", config=config, filename=filename,
            )
            target_path.parent.mkdir(parents=True, exist_ok=True)

            bytes_written = 0
            try:
                with open(target_path, "wb") as f:
                    for chunk in client.download_audio(plaud_id):
                        f.write(chunk)
                        bytes_written += len(chunk)
            except Exception:
                target_path.unlink(missing_ok=True)
                raise

            if expected_size and bytes_written != expected_size:
                target_path.unlink(missing_ok=True)
                raise PlaudDownloadCorrupted(
                    f"size mismatch on retry: expected={expected_size}, "
                    f"written={bytes_written}"
                )

            conn.execute(
                "UPDATE recordings SET status = 'downloaded', "
                "local_path = ?, classifier_label = ?, downloaded_at = ?, "
                "sync_run_id = ? WHERE plaud_id = ?",
                (str(target_path), label,
                 datetime.now(timezone.utc).isoformat(), run_id, plaud_id),
            )
            conn.commit()
            downloaded += 1
        except Exception as e:  # noqa: BLE001
            logger.bind(recording_id=plaud_id).exception("retry_skipped failed")
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("error_kind", "retry_skipped_failed")
                scope.set_tag("recording_id", plaud_id)
                scope.fingerprint = ["retry_skipped_failed", type(e).__name__]
                sentry_sdk.capture_exception(e)
            failed += 1

    return downloaded, failed


def run_sync(
    client,
    classifier: Classifier,
    conn: sqlite3.Connection,
    config: Config,
    trigger: str = "task_scheduler",
) -> int:
    run_id = start_sync_run(conn, trigger=trigger)

    # Rolling retry pass for previously-skipped rows whose project may now
    # be in config. BL-3 — see specs/2026-04-26-bl3-skip-unknown-projects-design.md.
    retry_downloaded, retry_failed = _retry_skipped_unknown_project(
        conn, client, classifier, config, run_id, days=14,
    )

    # Rolling re-classify pass: re-evaluate recent _unclassified rows against
    # current config (e.g. user added a project, or fixed a typo). Failures
    # roll into failed_count via exit_code semantics.
    reclassify_moved, reclassify_failed = _reclassify_recent(
        conn, classifier, config, run_id, days=14,
    )

    since = last_successful_sync(conn)

    new_count = retry_downloaded
    skipped_count = 0
    failed_count = reclassify_failed + retry_failed

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

    # BL-3 gate: regex matched a project, but it is not in config.yaml.
    # Skip download — record metadata for audit + 14d retry pass.
    if label != "_unclassified" and config.lookup_project(label) is None:
        record_recording(
            conn, meta, status="skipped_unknown_project",
            local_path="", run_id=run_id,
            classifier_label=label,
        )
        logger.bind(recording_id=meta.plaud_id, project=label).info(
            "skipped: project not in config"
        )
        return

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
    try:
        with open(target_path, "wb") as f:
            for chunk in client.download_audio(meta.plaud_id):
                f.write(chunk)
                bytes_written += len(chunk)
    except Exception:
        # Mid-stream interruption (network drop, S3 RST, etc.) leaves a partial
        # file on disk. Remove it so a UI/file watcher does not surface a
        # half-recording with a real-looking name.
        target_path.unlink(missing_ok=True)
        raise

    if meta.file_size and bytes_written != meta.file_size:
        target_path.unlink(missing_ok=True)
        raise PlaudDownloadCorrupted(
            f"size mismatch: expected={meta.file_size}, written={bytes_written}"
        )

    record_recording(
        conn, meta, status="downloaded",
        local_path=str(target_path), run_id=run_id,
        classifier_label=label,
    )
