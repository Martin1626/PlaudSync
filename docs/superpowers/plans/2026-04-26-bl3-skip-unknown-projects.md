# BL-3 — Skip Unknown Project Codes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recordings whose title regex matches a project NOT in `config.yaml` are skipped (no download), persisted in DB with `status='skipped_unknown_project'`, and retried on later sync runs against the current config (14d rolling window).

**Architecture:** Pre-download gate in `sync._process_recording` rejects matched-but-unknown recordings. New `sync._retry_skipped_unknown_project` pass re-evaluates skipped rows in last 14d against current config and downloads them when config now matches. Reuses existing `_reclassify_recent` patterns. Classifier and path_resolver remain unchanged.

**Tech Stack:** Python 3.11+, sqlite3, pytest, loguru, sentry_sdk. No new deps.

**Spec:** [docs/superpowers/specs/2026-04-26-bl3-skip-unknown-projects-design.md](../specs/2026-04-26-bl3-skip-unknown-projects-design.md)

---

## File Structure

**Modify:**
- [src/plaudsync/sync.py](../../../src/plaudsync/sync.py) — add gate in `_process_recording`, add `_retry_skipped_unknown_project`, wire into `run_sync`.
- [src/plaudsync/state.py](../../../src/plaudsync/state.py) — extend `record_recording` UPSERT to allow `skipped_unknown_project → downloaded` upgrade.

**Create:**
- `tests/test_sync_skip_unknown_project.py` — integration tests for gate + retry + 14d cutoff.

**No changes:** `categorization.py`, `classifier.py`, `path_resolver.py`, `config.py`, DB schema (reuse existing `recordings.status` column with new enum value).

---

## Task 1: Gate — skip matched-but-unknown recordings

**Files:**
- Test: `tests/test_sync_skip_unknown_project.py` (create)
- Modify: [src/plaudsync/sync.py](../../../src/plaudsync/sync.py) — `_process_recording` (around line 184)

- [ ] **Step 1.1: Write the failing test**

Create `tests/test_sync_skip_unknown_project.py`:

```python
"""Integration tests for BL-3: skip recordings with unknown project codes."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plaudsync.classifier import CategorizationClassifier
from plaudsync.config import Config
from plaudsync.state import open_state
from plaudsync.sync import run_sync


@dataclass
class _MetaStub:
    plaud_id: str
    title: str
    created_at: str
    file_size: int = 0
    plaud_folder: str = ""


class _ClientWithOneUnknownProject:
    """Lists 1 recording whose title regex-matches an unknown project code."""

    def __init__(self, meta: _MetaStub) -> None:
        self._meta = meta
        self.download_calls: list[str] = []

    def list_recordings(self, since=None):
        yield self._meta

    def download_audio(self, plaud_id: str):
        self.download_calls.append(plaud_id)
        yield b"audio-bytes"


def test_unknown_project_is_skipped_not_downloaded(tmp_path: Path) -> None:
    """Title `MM-DD UNKNOWN: foo` with UNKNOWN absent from config →
    no download, DB row status='skipped_unknown_project', local_path=''.
    """
    alza_dir = tmp_path / "ALZA"
    alza_dir.mkdir()
    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir()

    config = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": alza_dir},  # UNKNOWN is NOT in projects
    )
    conn = open_state(tmp_path)

    meta = _MetaStub(
        plaud_id="rec-unknown-1",
        title="04-26 UNKNOWN: foo",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    client = _ClientWithOneUnknownProject(meta)

    exit_code = run_sync(client, CategorizationClassifier(), conn, config, "manual")

    assert exit_code == 0
    assert client.download_calls == [], "download_audio must NOT be called"

    # No MP3 anywhere on disk
    mp3s = list(tmp_path.rglob("*.mp3"))
    assert mp3s == [], f"expected no MP3 files, found: {mp3s}"

    # DB row exists with skipped status
    row = conn.execute(
        "SELECT status, local_path, classifier_label FROM recordings "
        "WHERE plaud_id = 'rec-unknown-1'"
    ).fetchone()
    assert row is not None, "DB row must be inserted for audit"
    assert row[0] == "skipped_unknown_project"
    assert row[1] == ""
    assert row[2] == "UNKNOWN"

    conn.close()
```

- [ ] **Step 1.2: Run test — verify it fails**

Run: `pytest tests/test_sync_skip_unknown_project.py::test_unknown_project_is_skipped_not_downloaded -v`

Expected: FAIL — record gets either downloaded into `_unmapped_UNKNOWN/` or status='downloaded' (current pre-BL-3 behavior).

- [ ] **Step 1.3: Commit failing test**

```bash
git add tests/test_sync_skip_unknown_project.py
git commit -m "test(bl-3): failing test — unknown project must skip download"
```

- [ ] **Step 1.4: Implement the gate in `_process_recording`**

Edit [src/plaudsync/sync.py](../../../src/plaudsync/sync.py), in `_process_recording` (line ~184) — insert gate AFTER `classifier.classify(meta)` and BEFORE building `result`/path:

```python
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
        # ... existing code unchanged
```

(Keep all existing code from `if label == "_unclassified":` onward unchanged.)

- [ ] **Step 1.5: Run test — verify it passes**

Run: `pytest tests/test_sync_skip_unknown_project.py::test_unknown_project_is_skipped_not_downloaded -v`

Expected: PASS.

- [ ] **Step 1.6: Run full test suite — verify no regressions**

Run: `pytest tests/ -x -q`

Expected: all green. If `test_sync_reclassify` or `test_sync` fail, the gate is firing on cases it shouldn't — debug before continuing.

- [ ] **Step 1.7: Commit**

```bash
git add src/plaudsync/sync.py
git commit -m "feat(sync): BL-3 gate — skip download when project not in config"
```

---

## Task 2: Retry pass — re-download skipped rows when config matches

**Files:**
- Test: `tests/test_sync_skip_unknown_project.py` (extend)
- Modify: [src/plaudsync/state.py](../../../src/plaudsync/state.py) — extend `record_recording` upgrade rules
- Modify: [src/plaudsync/sync.py](../../../src/plaudsync/sync.py) — add `_retry_skipped_unknown_project`, wire into `run_sync`

- [ ] **Step 2.1: Write the failing test**

Append to `tests/test_sync_skip_unknown_project.py`:

```python
class _ClientNoListing:
    """Returns no new recordings on listing, but supports download_audio
    when retry pass calls it for previously-skipped rows."""

    def __init__(self, audio_bytes: dict[str, bytes]) -> None:
        self._audio = audio_bytes
        self.download_calls: list[str] = []

    def list_recordings(self, since=None):
        return iter([])

    def download_audio(self, plaud_id: str):
        self.download_calls.append(plaud_id)
        yield self._audio[plaud_id]


def test_skipped_recording_retried_after_config_update(tmp_path: Path) -> None:
    """After sync 1 skips UNKNOWN, user adds UNKNOWN to config; sync 2 must
    download and classify the previously-skipped recording."""
    alza_dir = tmp_path / "ALZA"
    alza_dir.mkdir()
    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir()

    # --- Sync 1: UNKNOWN not in config → record gets skipped ---
    config_v1 = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": alza_dir},
    )
    conn = open_state(tmp_path)

    meta = _MetaStub(
        plaud_id="rec-retry-1",
        title="04-26 UNKNOWN: bar",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    client_v1 = _ClientWithOneUnknownProject(meta)

    exit_v1 = run_sync(client_v1, CategorizationClassifier(), conn, config_v1, "manual")
    assert exit_v1 == 0
    assert client_v1.download_calls == []

    row_v1 = conn.execute(
        "SELECT status FROM recordings WHERE plaud_id = 'rec-retry-1'"
    ).fetchone()
    assert row_v1[0] == "skipped_unknown_project"

    # --- Sync 2: UNKNOWN added to config → retry pass downloads ---
    unknown_dir = tmp_path / "UNKNOWN"
    unknown_dir.mkdir()
    config_v2 = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": alza_dir, "UNKNOWN": unknown_dir},
    )
    client_v2 = _ClientNoListing({"rec-retry-1": b"the-audio-bytes"})

    exit_v2 = run_sync(client_v2, CategorizationClassifier(), conn, config_v2, "manual")
    assert exit_v2 == 0
    assert client_v2.download_calls == ["rec-retry-1"]

    # File now in UNKNOWN/ folder
    mp3s = list(unknown_dir.glob("*.mp3"))
    assert len(mp3s) == 1, f"expected 1 mp3 in UNKNOWN/, found: {mp3s}"
    assert mp3s[0].read_bytes() == b"the-audio-bytes"

    # DB row upgraded to downloaded
    row_v2 = conn.execute(
        "SELECT status, local_path, classifier_label "
        "FROM recordings WHERE plaud_id = 'rec-retry-1'"
    ).fetchone()
    assert row_v2[0] == "downloaded"
    assert Path(row_v2[1]) == mp3s[0]
    assert row_v2[2] == "UNKNOWN"

    conn.close()
```

- [ ] **Step 2.2: Run test — verify it fails**

Run: `pytest tests/test_sync_skip_unknown_project.py::test_skipped_recording_retried_after_config_update -v`

Expected: FAIL — sync 2 listing is empty, no retry pass exists, row stays at `skipped_unknown_project`.

- [ ] **Step 2.3: Commit failing test**

```bash
git add tests/test_sync_skip_unknown_project.py
git commit -m "test(bl-3): failing test — retry pass after config update"
```

- [ ] **Step 2.4: Extend `record_recording` to allow skipped → downloaded upgrade**

Edit [src/plaudsync/state.py:117](../../../src/plaudsync/state.py#L117) — extend the upgrade condition. Replace:

```python
    elif existing[0] == "failed" and status == "downloaded":
```

with:

```python
    elif existing[0] in ("failed", "skipped_unknown_project") and status == "downloaded":
```

Rationale: same UPSERT pattern, expanded set of upgradeable predecessor states. `downloaded` rows remain immutable.

- [ ] **Step 2.5: Implement `_retry_skipped_unknown_project`**

Edit [src/plaudsync/sync.py](../../../src/plaudsync/sync.py) — add new function AFTER `_reclassify_recent` (around line 126) and BEFORE `run_sync`:

```python
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
        "SELECT plaud_id, title, created_at_plaud "
        "FROM recordings "
        "WHERE status = 'skipped_unknown_project' "
        "AND created_at_plaud >= ?",
        (cutoff,),
    ).fetchall()

    downloaded = 0
    failed = 0
    for plaud_id, title, created_at in rows:
        try:
            class _MetaLike:
                pass
            meta_like = _MetaLike()
            meta_like.plaud_id = plaud_id  # type: ignore[attr-defined]
            meta_like.title = title  # type: ignore[attr-defined]
            meta_like.created_at = created_at  # type: ignore[attr-defined]

            label = classifier.classify(meta_like)
            if label == "_unclassified" or config.lookup_project(label) is None:
                # Still no match — leave row as-is.
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

            conn.execute(
                "UPDATE recordings SET status = 'downloaded', "
                "local_path = ?, classifier_label = ?, downloaded_at = ? "
                "WHERE plaud_id = ?",
                (str(target_path), label,
                 datetime.now(timezone.utc).isoformat(), plaud_id),
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
```

Note: `_now_iso` is in `state.py` not imported here — use inline `datetime.now(timezone.utc).isoformat()` (already imported).

- [ ] **Step 2.6: Wire retry pass into `run_sync`**

Edit [src/plaudsync/sync.py:140-148](../../../src/plaudsync/sync.py#L140-L148) — add retry call BEFORE `_reclassify_recent`. Replace:

```python
    # Rolling re-classify pass: re-evaluate recent _unclassified rows against
    # current config (e.g. user added a project, or fixed a typo). Failures
    # roll into failed_count via exit_code semantics.
    reclassify_moved, reclassify_failed = _reclassify_recent(
        conn, classifier, config, run_id, days=14,
    )

    since = last_successful_sync(conn)

    new_count = 0
    skipped_count = 0
    failed_count = reclassify_failed
```

with:

```python
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
```

- [ ] **Step 2.7: Run test — verify it passes**

Run: `pytest tests/test_sync_skip_unknown_project.py::test_skipped_recording_retried_after_config_update -v`

Expected: PASS.

- [ ] **Step 2.8: Run full test suite**

Run: `pytest tests/ -x -q`

Expected: all green.

- [ ] **Step 2.9: Commit**

```bash
git add src/plaudsync/sync.py src/plaudsync/state.py
git commit -m "feat(sync): BL-3 retry pass — re-download skipped rows when config matches"
```

---

## Task 3: 14d cutoff — old skipped rows must not be retried

**Files:**
- Test: `tests/test_sync_skip_unknown_project.py` (extend)

The cutoff logic is already implemented in Step 2.5 (`created_at_plaud >= cutoff`). This task adds an explicit failing test that locks in the boundary behavior.

- [ ] **Step 3.1: Write the failing test**

Append to `tests/test_sync_skip_unknown_project.py`:

```python
def _seed_skipped_row(
    conn: sqlite3.Connection,
    *,
    plaud_id: str,
    title: str,
    created_at: str,
) -> None:
    from plaudsync.state import start_sync_run
    run_id = start_sync_run(conn, "manual")
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, "
        "downloaded_at, local_path, classifier_label, status, sync_run_id) "
        "VALUES (?, ?, ?, ?, '', ?, 'skipped_unknown_project', ?)",
        (plaud_id, title, created_at, created_at,
         title.split(":")[0].split()[-1], run_id),
    )
    conn.commit()


def test_skipped_recording_outside_14d_window_not_retried(tmp_path: Path) -> None:
    """Row with created_at_plaud older than 14d must NOT be retried even
    when config now has the project."""
    unknown_dir = tmp_path / "UNKNOWN"
    unknown_dir.mkdir()
    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir()

    config = Config(
        unclassified_dir=unclassified,
        projects={"UNKNOWN": unknown_dir},
    )
    conn = open_state(tmp_path)

    old_ts = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
    _seed_skipped_row(
        conn,
        plaud_id="rec-old-1",
        title="04-09 UNKNOWN: ancient",
        created_at=old_ts,
    )

    client = _ClientNoListing({"rec-old-1": b"should-never-be-fetched"})
    exit_code = run_sync(client, CategorizationClassifier(), conn, config, "manual")

    assert exit_code == 0
    assert client.download_calls == [], "must NOT call download for >14d row"

    mp3s = list(unknown_dir.glob("*.mp3"))
    assert mp3s == [], "no file must be written for old row"

    row = conn.execute(
        "SELECT status, local_path FROM recordings WHERE plaud_id = 'rec-old-1'"
    ).fetchone()
    assert row[0] == "skipped_unknown_project"
    assert row[1] == ""

    conn.close()
```

- [ ] **Step 3.2: Run test — verify it passes immediately**

Run: `pytest tests/test_sync_skip_unknown_project.py::test_skipped_recording_outside_14d_window_not_retried -v`

Expected: PASS (the cutoff is already implemented in Task 2). If it fails, the SQL `created_at_plaud >= cutoff` filter is wrong — fix and re-run.

- [ ] **Step 3.3: Run full test suite**

Run: `pytest tests/ -x -q`

Expected: all green.

- [ ] **Step 3.4: Commit**

```bash
git add tests/test_sync_skip_unknown_project.py
git commit -m "test(bl-3): regression — 14d cutoff for retry pass"
```

---

## Task 4: DEV_LOG entry + spec follow-ups

**Files:**
- Modify: [DEV_LOG.md](../../../DEV_LOG.md) (prepend new entry above "2026-04-26 — Backlog: 5 nových položek k implementaci")

- [ ] **Step 4.1: Add DEV_LOG entry**

Prepend to [DEV_LOG.md](../../../DEV_LOG.md) above the existing top entry:

```markdown
## 2026-04-26 — BL-3 implementace: skip unknown project codes

**Spec:** [docs/superpowers/specs/2026-04-26-bl3-skip-unknown-projects-design.md](docs/superpowers/specs/2026-04-26-bl3-skip-unknown-projects-design.md).
**Plan:** [docs/superpowers/plans/2026-04-26-bl3-skip-unknown-projects.md](docs/superpowers/plans/2026-04-26-bl3-skip-unknown-projects.md).

**Implementováno:**
- Pre-download gate v `_process_recording`: regex match + `config.lookup_project(label) is None` → DB row `status='skipped_unknown_project'`, žádný download.
- `_retry_skipped_unknown_project` pass v `run_sync` (před `_reclassify_recent`): SELECT skipped rows < 14d, re-evaluate proti current configu, downloaduje matched.
- `record_recording` extended UPSERT: `skipped_unknown_project → downloaded` upgrade allowed (vedle `failed → downloaded`).

**Kill criteria check:**
- `#5` (regex coverage <90 %): BL-3 zužuje "matched" definici — záznamy s neznámým project kódem se teď počítají jako "skipped", ne jako "matched". Watch monitoring metric.

**Follow-ups:**
- Cleanup helper / one-off skript pro existující `_unmapped_<Project>/` složky z období před BL-3 (samostatný ticket).
- UI badge "skipped: N" v tray menu (samostatný ticket).
- Stale title race v retry passu (DB title se neaktualizuje při Plaud-side rename) — pre-existing pattern, neřešíme.
```

- [ ] **Step 4.2: Run `/review` slash command**

Run `/review` (per CLAUDE.md, before merge gate). Address findings inline (Critical/Important fix; Minor/Suggestion log only per memory `feedback_plan_literal_vs_reviewer.md`).

- [ ] **Step 4.3: Run `/security-review` slash command**

Run `/security-review`. Verify no token/path leakage in new code.

- [ ] **Step 4.4: Run `bandit -r src/`**

Run: `bandit -r src/`

Expected: clean (per CLAUDE.md gate).

- [ ] **Step 4.5: Manual smoke test in tray UI**

Steps:
1. Backup or use isolated test env. Add temp test recording on Plaud with title `04-26 ZZTESTUNKNOWN: smoke`.
2. Ensure `ZZTESTUNKNOWN` is NOT in `config.yaml`.
3. Trigger sync via tray "Sync Now".
4. Verify: no MP3 in any project folder, log line `skipped: project not in config`, DB row exists with `status='skipped_unknown_project'`.
5. Add `ZZTESTUNKNOWN: <test_path>` to `config.yaml`. Save.
6. Trigger sync via tray "Sync Now".
7. Verify: MP3 appears in `<test_path>/`, log line shows retry, DB row updated to `status='downloaded'`.
8. Cleanup: delete test recording from Plaud, remove ZZTESTUNKNOWN from config, delete test files.

If any step fails, revert and debug per `sync-debug` skill.

- [ ] **Step 4.6: Commit DEV_LOG**

```bash
git add DEV_LOG.md
git commit -m "docs(dev-log): BL-3 implementation entry + follow-ups"
```

---

## Self-Review Notes

**Spec coverage check:**
- ✅ Skip-on-unknown gate → Task 1
- ✅ DB persistence with `skipped_unknown_project` → Task 1 (via `record_recording`)
- ✅ Retry pass with 14d window → Task 2
- ✅ Reuse `_reclassify_recent` pattern → Task 2 (analogous structure, separate function)
- ✅ `path_resolver` unchanged → confirmed (no edits)
- ✅ `categorization.py` unchanged → confirmed (no edits)
- ✅ Privacy: project name passed via `set_tag`/`logger.bind`, never f-string → Task 1 Step 1.4 + Task 2 Step 2.5
- ✅ Sentry fingerprint pattern → Task 2 Step 2.5
- ✅ `recording_exists_and_downloaded` checks `status='downloaded'` only → existing impl OK, no change needed
- ✅ Test #1 / #2 / #3 from spec → Task 1 / Task 2 / Task 3
- ✅ Manual smoke → Task 4 Step 4.5
- ✅ DEV_LOG entry → Task 4 Step 4.1

**Spec amendment (`downloaded_at` for skipped rows):** Spec said "NULL for skipped rows", but existing `record_recording` always sets `_now_iso()`. We keep current behavior (downloaded_at = time of last DB write) — it's the timestamp of the last DB transaction, useful for sorting/auditing regardless of status. No correctness impact on retry (which uses `created_at_plaud` for the cutoff).

**Placeholder scan:** No TBD/TODO. All steps contain runnable code or exact commands.

**Type consistency:** `_MetaLike` duck-typed pattern matches existing `_reclassify_recent`. `record_recording` sig (`status: str`) accepts arbitrary string — no type changes.
