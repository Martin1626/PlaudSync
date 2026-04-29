"""Sync pipeline orchestration.

See docs/superpowers/specs/2026-04-25-sync-core-design.md (v0.3 baseline)
and docs/superpowers/specs/2026-04-29-bl4-bl-x-content-classifier-design.md
(v0.4 — multi-layer waterfall + content artifacts).
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import sentry_sdk
from loguru import logger

from plaudsync.categorization import ClassificationResult
from plaudsync.classifier import Classifier, ClassificationOutcome, WaterfallClassifier
from plaudsync.classifiers.name import NameClassifier
from plaudsync.config import Config
from plaudsync.content_fetcher import ContentFetcher, FetchOutcome
from plaudsync.content_writer import compose as compose_markdown
from plaudsync.path_resolver import resolve_target_path
from plaudsync.plaud_client import (
    PlaudDownloadCorrupted,
)
from plaudsync.progress import clear_progress, write_progress
from plaudsync.state import (
    finish_sync_run,
    last_successful_sync,
    record_recording,
    recording_exists_and_downloaded,
    start_sync_run,
)


def should_download_artifact(
    kind: str,
    meta: Any,
    outcome: ClassificationOutcome,
    config: Config,
) -> bool:
    """Per-artifact download gate (BL-4/BL-X spec §6 "Artifact gate").

    Audio: ungated by classification — downloads if download_audio=true.
    Content: hardcoded extra rules — only when classified (source != 'none')
    AND has Plaud folder. These are safety policy, NOT user-configurable
    (text without classification = privacy risk; per spec §10).
    """
    if kind == "audio" and not config.download_audio:
        return False
    if kind == "content" and not config.download_content:
        return False
    if kind == "content":
        if outcome.source == "none":  # _unclassified catch-all
            return False
        if getattr(meta, "plaud_folder", "_unknown") == "_unknown":
            return False
    return True


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
    state_root: Path | None = None,
) -> int:
    run_id = start_sync_run(conn, trigger=trigger)

    def _emit(phase: str, processed: int | None, total: int | None) -> None:
        if state_root is None:
            return
        write_progress(
            state_root,
            sync_run_id=run_id,
            phase=phase,  # type: ignore[arg-type]
            processed_count=processed,
            total_count=total,
        )

    try:
        _emit("listing", None, None)

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
        metas = list(client.list_recordings(since=since))

        new_count = retry_downloaded
        skipped_count = 0
        failed_count = reclassify_failed + retry_failed
        total = len(metas)

        _emit("downloading", 0, total)

        for i, meta in enumerate(metas):
            if recording_exists_and_downloaded(conn, meta.plaud_id):
                skipped_count += 1
                _emit("downloading", i + 1, total)
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
            _emit("downloading", i + 1, total)

        _emit("finalizing", None, None)

        exit_code = 4 if failed_count > 0 else 0
        finish_sync_run(
            conn, run_id, exit_code=exit_code,
            recordings_new=new_count, recordings_skipped=skipped_count,
            recordings_failed=failed_count,
        )
        return exit_code
    finally:
        if state_root is not None:
            clear_progress(state_root)


def _normalize_classifier_output(value: Any) -> ClassificationOutcome:
    """Adapt either str (legacy CategorizationClassifier) or ClassificationOutcome
    (WaterfallClassifier) into a uniform ClassificationOutcome.

    Legacy str → source='name' for matched, source='none' for '_unclassified'.
    The catch-all source='none' bypasses the new outright-skip semantic, so
    legacy callers (tests, untouched call sites) preserve their pre-BL-X
    behavior: every recording lands in DB, _unclassified ones go to
    unclassified_dir.
    """
    if isinstance(value, ClassificationOutcome):
        return value
    label = str(value)
    if label == "_unclassified":
        return ClassificationOutcome(label=label, source="none")
    return ClassificationOutcome(label=label, source="name")


def _process_recording(
    meta,
    client,
    classifier: Any,  # WaterfallClassifier OR legacy str-returning Classifier
    config: Config,
    conn: sqlite3.Connection,
    run_id: int,
) -> None:
    """Process one recording: classify (waterfall) → gate → download MP3 → DB row.

    Content (.md sourozenec) emit lives in the same flow but is gated
    separately via should_download_artifact("content", ...). Pending
    content_status writes are handled here; retry pass picks up later.
    """
    outcome = _normalize_classifier_output(classifier.classify(meta))

    # No strategy matched + sync_unclassified=false → outright skip,
    # no DB row written. Replaces pre-BL-X sync_only_foldered semantic.
    if outcome.source == "skip":
        return

    label = outcome.label
    assert label is not None  # invariant: source != 'skip' implies label is set

    # BL-3 gate: matched-by-name but project not in config.yaml.
    # Folder-classified recordings always have a config project (folder
    # mapping comes from config), so this gate fires only for name-source.
    if (outcome.source == "name"
            and label != "_unclassified"
            and config.lookup_project(label) is None):
        record_recording(
            conn, meta, status="skipped_unknown_project",
            local_path="", run_id=run_id,
            classifier_label=label,
            classification_source=outcome.source,
        )
        logger.bind(recording_id=meta.plaud_id, project=label).info(
            "skipped: project not in config"
        )
        return

    # Audio gate — when off, skip download but still record DB row so UI sees
    # the recording (with status='skipped' marking artifact-level decline).
    if not should_download_artifact("audio", meta, outcome, config):
        record_recording(
            conn, meta, status="skipped",
            local_path="", run_id=run_id,
            classifier_label=label,
            classification_source=outcome.source,
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

    # Content artifact (.md sourozenec) — only when gate passes (folder
    # present + classified). All-or-nothing emit: any required Plaud
    # content_list type with task_status != 1 → status='pending', retry pass
    # picks up later. Missing required type → 'not_applicable' (no infinite
    # retry on recordings too short to summarize).
    content_status: str | None = "not_applicable"
    content_path: str | None = None
    content_task_ids_json: str | None = None

    if should_download_artifact("content", meta, outcome, config):
        try:
            fetch_outcome = ContentFetcher(client).fetch_artifacts(meta.plaud_id)
        except Exception as e:  # noqa: BLE001
            logger.bind(recording_id=meta.plaud_id).exception("content fetch failed")
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("error_kind", "content_fetch_failed")
                scope.set_tag("recording_id", meta.plaud_id)
                scope.fingerprint = ["content_fetch_failed", type(e).__name__]
                sentry_sdk.capture_exception(e)
            content_status = "pending"  # retry pass will re-attempt
        else:
            if fetch_outcome.task_ids:
                content_task_ids_json = json.dumps(fetch_outcome.task_ids)
            if fetch_outcome.status == "complete":
                md_path = target_path.with_suffix(".md")
                md_text = compose_markdown(
                    meta=meta,
                    detail=fetch_outcome.detail,
                    sections=fetch_outcome.sections,
                    project=label,
                    classification_source=outcome.source,
                )
                md_path.write_text(md_text, encoding="utf-8")
                content_status = "complete"
                content_path = str(md_path)
            else:
                content_status = fetch_outcome.status

    record_recording(
        conn, meta, status="downloaded",
        local_path=str(target_path), run_id=run_id,
        classifier_label=label,
        classification_source=outcome.source,
        content_status=content_status,
        content_path=content_path,
        content_task_ids=content_task_ids_json,
    )
