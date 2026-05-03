# BL-8 — Plaud-side trash detection (design)

> **Status:** locked design v1.0 (2026-05-03). Supersedes the v0.1 stub at
> `2026-04-30-bl8-trash-detection-stub.md`. All open decisions in stub
> sekce 6 are resolved below; one new decision (batch safety threshold)
> was added during brainstorm.
>
> **Brainstorm session:** 2026-05-03. 6 decisions locked (4 stub-original
> + batch safety + sentinel-policy clarifications).

## 1. Problem (recap)

`PlaudClient.list_recordings` hardcodes `is_trash=0`. Trashed recordings
are invisible to PlaudSync at API level. Consequences for an
already-downloaded recording the user later trashes on Plaud:

- DB row stays as `status='downloaded'` (forever).
- Local MP3 + `.md` sourozenec stay on disk (orphan files).
- UI Recordings list keeps showing the recording as fine (until pagination
  drops it). User has no idea Plaud-side state changed.

Privacy + housekeeping concern: trashed recordings often = sensitive
content the user explicitly wanted to delete. Local copies surviving
silently is a leak risk.

## 2. Locked decisions

### Decision 1 — Trash policy: **hard delete** (no config flag)

When a downloaded recording is detected as trashed on Plaud:

1. Delete local MP3 (`local_path`).
2. Delete local `.md` (`content_path`) if present.
3. UPSERT DB row: `status='trashed'`, retain title/created_at/classifier_label
   for UI surface (gray "smazáno" pill needs them).

**Rationale:** trashing on Plaud is intentional user signal "this should
be gone". Soft-archive duplicates state and creates a `_trashed/` housekeeping
problem. Configurability (`trash_policy: hard | archive | mark`) was rejected
as YAGNI: 3× tests, 3× UI explanations, 3× edge cases for a feature where
~all users use the default. Untrash recovery (Decision 2) handles the
"oops" case via fresh download from Plaud.

### Decision 2 — Untrash recovery: **fresh download via main loop**

When user un-trashes on Plaud, the recording reappears in `is_trash=0`
listing. Main download loop:

- `recording_exists_and_downloaded(plaud_id)` returns False (status='trashed' ≠ 'downloaded').
- `_process_recording` runs as on a fresh recording.
- `record_recording` UPSERT must allow `'trashed' → 'downloaded'` transition.

**UPSERT whitelist extension** in [state.py:143](../../src/plaudsync/state.py#L143):

```python
elif existing[0] in ("failed", "skipped_unknown_project", "skipped", "trashed") \
     and status == "downloaded":
    # Same UPDATE as today — content_task_ids/path repopulate from incoming kwargs
```

Plaud may have regenerated content (different `task_id_info` from before
trash). Fresh download is correct semantic — old `content_task_ids`
fingerprint is invalidated by the trip through trash.

### Decision 3 — Sentry alert: **hybrid** (per-record silent, mass-detect captured)

**Per-record trash** (normal path): `logger.bind(plaud_id=..., content_existed=...,
classifier_label=...).info("trash_auto_delete")`. No Sentry capture. Audit
lives in rotating Loguru file.

**Safety threshold trip** (Decision 6): full `sentry_sdk.capture_message`
with `error_kind='trash_mass_detection'`. See Decision 6.

**Rationale:** Sentry stays as error/anomaly channel. BL-X established
`error_kind='content_stale'` as "Plaud's fault, user should know" pattern;
trash auto-delete is success path, not anomaly. Per-record Sentry pings
would dilute signal/noise. Loguru rotated file already captures `info`
events for audit.

### Decision 4 — UI surface: **gray "smazáno" pill**, BL-7 analog

In [frontend/src/pages/Dashboard/ProjectBadge.tsx](../../frontend/src/pages/Dashboard/ProjectBadge.tsx),
add new variant before the existing `status === 'skipped'` branch:

```tsx
if (status === "trashed") {
  return (
    <span className={classNames(PILL_BASE, GRAY)}
          title="Záznam byl smazán na Plaude. Lokální kopie odstraněna.">
      smazáno
    </span>
  );
}
```

`RecordingStatus` TS type extended: `"downloaded" | "failed" | "skipped" | "trashed"`.

`StatusIcon` gets no new variant in this iteration. Row stays in list (no
strike-through, no filter chip, no exclusion). User awareness preserved
via persistent badge.

**Rationale:** consistency with BL-7 pattern users already learned (gray
pill = abnormal state, tooltip explains). Strike-through + filter chip
were rejected as premature complexity — kill criterion #19 dynamic
surface area trigger candidate if user later asks for filter.

### Decision 5 — UPSERT untrash: **'trashed' added to whitelist**

See Decision 2. Schema CHECK constraint must accept `'trashed'`; UPSERT
allows `('failed', 'skipped_unknown_project', 'skipped', 'trashed') →
'downloaded'`.

### Decision 6 — Batch safety threshold: **combo (>10 AND >50%)**

Hard delete is destructive. Failure mode: API regression / auth glitch
/ Plaud server migration causing `is_trash=1` listing to return non-trash
rows would mass-delete the local collection in one sync.

**Guard logic** in `_detect_trashed`, before any deletion:

```python
MAX_BATCH_ABSOLUTE = 10
MAX_BATCH_RATIO = 0.5

to_delete = trashed_ids & downloaded_ids
if len(to_delete) > MAX_BATCH_ABSOLUTE \
   and len(to_delete) / max(len(downloaded_ids), 1) > MAX_BATCH_RATIO:
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("error_kind", "trash_mass_detection")
        scope.set_tag("trashed_count", len(to_delete))
        scope.set_tag("downloaded_count", len(downloaded_ids))
        scope.fingerprint = ["trash_mass_detection"]
        sentry_sdk.capture_message("trash_mass_detection_aborted")
    logger.warning(
        "trash_mass_detection_aborted: would delete {} of {} downloaded — skipping",
        len(to_delete), len(downloaded_ids),
    )
    return 0, 0  # no-op, sync continues with normal flow
```

**Constants:** hard-coded in [src/plaudsync/sync.py](../../src/plaudsync/sync.py).
Not exposed as config (kill criterion #19 dynamic surface; user can revisit
if false positives ever appear).

**False positive: large-collection user with legitimate burst-trash.**
A user with 20 downloaded recordings who legitimately trashes 11 of them
in one Plaud session would trigger the guard (11/20 = 55% > 50%, 11 > 10).
Mitigation: user notices via Sentry email, then trashes them in two
batches across separate sync runs (each batch ≤ 10 stays under absolute
threshold), or manually deletes local files and DB rows. Acceptable
tradeoff vs. mass-delete blast radius from API bug. Burst trashes ≤ 10
or in collections ≤ 10 always proceed, no friction.

## 3. Architecture: new `_detect_trashed` pre-pass

### 3.1 New PlaudClient method

```python
def list_trashed(self) -> Iterator[RecordingMeta]:
    """Yield trashed RecordingMeta. Same shape as list_recordings,
    just is_trash=1 query parameter."""
    skip = 0
    page_size = 50
    while True:
        url = f"{self._base_url}/file/simple/web"
        resp = self._session.get(
            url, params={"skip": skip, "limit": page_size, "is_trash": 1}
        )
        if resp.status_code == 401:
            raise PlaudTokenExpired("token rejected mid-trash-listing")
        resp.raise_for_status()
        body = resp.json()
        page = body.get("data_file_list") or []
        if not page:
            return
        for raw in page:
            yield RecordingMeta.from_raw(raw)
        skip += page_size
```

Mirrors `list_recordings` but no `since` filter — trashed list is
typically small and user can have old trashed items lingering.

### 3.2 New pre-pass `_detect_trashed`

Position in `run_sync`: **after listing, before all retry passes**. Reason:
no point reclassifying / retry-content-ing a row that's about to be deleted.

```python
def _detect_trashed(
    conn: sqlite3.Connection, client
) -> tuple[int, int]:
    """Returns (trashed_count, failed_count).

    Lists trashed recordings on Plaud; for each that matches a local
    downloaded row, hard-deletes local files and UPSERTs status='trashed'.
    Includes batch safety guard (Decision 6) — aborts if trash batch is
    suspiciously large.
    """
    if not hasattr(client, "list_trashed"):
        return 0, 0  # forward-compat for mocked clients in unit tests
    try:
        trashed_ids = {meta.plaud_id for meta in client.list_trashed()}
    except Exception as e:  # noqa: BLE001
        logger.exception("list_trashed crashed")
        sentry_sdk.capture_exception(e)
        return 0, 1

    downloaded_rows = conn.execute(
        "SELECT plaud_id, local_path, content_path FROM recordings "
        "WHERE status = 'downloaded'"
    ).fetchall()
    downloaded_ids = {row[0] for row in downloaded_rows}
    to_delete_ids = trashed_ids & downloaded_ids

    if not to_delete_ids:
        return 0, 0

    # Batch safety guard
    if len(to_delete_ids) > MAX_BATCH_ABSOLUTE \
       and len(to_delete_ids) / max(len(downloaded_ids), 1) > MAX_BATCH_RATIO:
        # capture + return 0, 0 (see Decision 6)
        ...
        return 0, 0

    # Per-row delete loop
    trashed_count = 0
    failed_count = 0
    rows_by_id = {r[0]: r for r in downloaded_rows}
    for plaud_id in to_delete_ids:
        _, local_path, content_path = rows_by_id[plaud_id]
        try:
            _hard_delete_local(local_path, content_path)
            conn.execute(
                "UPDATE recordings SET status = 'trashed' WHERE plaud_id = ?",
                (plaud_id,),
            )
            conn.commit()
            logger.bind(
                plaud_id=plaud_id,
                content_existed=(content_path is not None),
            ).info("trash_auto_delete")
            trashed_count += 1
        except Exception as e:  # noqa: BLE001
            logger.bind(plaud_id=plaud_id).exception("trash_delete_failed")
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("error_kind", "trash_delete_failed")
                scope.set_tag("recording_id", plaud_id)
                scope.fingerprint = ["trash_delete_failed", type(e).__name__]
                sentry_sdk.capture_exception(e)
            failed_count += 1

    return trashed_count, failed_count


def _hard_delete_local(local_path: str, content_path: str | None) -> None:
    """OS-level delete. Missing files = no-op (idempotent re-runs)."""
    for path_str in (local_path, content_path):
        if not path_str:
            continue
        path = Path(path_str)
        if path.exists():
            path.unlink()
```

### 3.3 Position in `run_sync`

Insert **between listing fetch and `_retry_skipped_unknown_project`** in
[sync.py:567](../../src/plaudsync/sync.py#L567):

```python
metas = list(client.list_recordings(since=None))
live_metas = {m.plaud_id: m for m in metas}

# BL-8: detect Plaud-side trash and hard-delete local files.
# Runs first so retry/reclassify passes don't waste cycles on
# rows about to be deleted.
trashed_count, trashed_failed = _detect_trashed(conn, client)

retry_downloaded, retry_failed = _retry_skipped_unknown_project(...)
# ... rest unchanged
```

`failed_count` aggregation absorbs `trashed_failed`. `new_count` /
`skipped_count` are unaffected (trashed != new, trashed != skipped).

### 3.4 Schema migration

New `status` enum value: `'trashed'`. CHECK constraint rebuild via existing
`_migrate_status_check_constraint` pattern, but the migration only fires
when old constraint is detected. We need a NEW migration function:

```python
def _migrate_status_add_trashed(conn: sqlite3.Connection) -> None:
    """Rebuild recordings.status CHECK to include 'trashed' (BL-8).

    Fires when current constraint lacks 'trashed' (any pre-BL-8 DB).
    Idempotent via early return on detection.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='recordings'"
    ).fetchone()
    if row is None or "'trashed'" in row[0]:
        return
    conn.executescript("""
        BEGIN;
        CREATE TABLE recordings_new (
            plaud_id              TEXT PRIMARY KEY,
            title                 TEXT NOT NULL,
            created_at_plaud      TEXT NOT NULL,
            downloaded_at         TEXT NOT NULL,
            local_path            TEXT NOT NULL,
            classifier_label      TEXT NOT NULL,
            status                TEXT NOT NULL CHECK (status IN ('downloaded','failed','skipped','skipped_unknown_project','trashed')),
            sync_run_id           INTEGER REFERENCES sync_runs(run_id),
            file_size             INTEGER,
            content_status        TEXT,
            content_path          TEXT,
            content_task_ids      TEXT,
            classification_source TEXT,
            plaud_folder_id       TEXT
        );
        INSERT INTO recordings_new SELECT * FROM recordings;
        DROP TABLE recordings;
        ALTER TABLE recordings_new RENAME TO recordings;
        CREATE INDEX IF NOT EXISTS idx_recordings_downloaded_at ON recordings(downloaded_at DESC);
        COMMIT;
    """)
```

Update inline `_SCHEMA` literal at [state.py:21](../../src/plaudsync/state.py#L21)
to include `'trashed'` in CHECK for fresh DBs.

Update `_migrate_status_check_constraint` is left untouched — it only fires
on pre-BL-3 DBs and gates on `"skipped_unknown_project" in row[0]`. New
migration uses different gate (`"'trashed'" not in row[0]`), runs after
the BL-3 one.

### 3.5 UPSERT extension

[state.py:143](../../src/plaudsync/state.py#L143):

```python
elif existing[0] in ("failed", "skipped_unknown_project", "skipped", "trashed") \
     and status == "downloaded":
```

One-token change. Untrash → fresh download flow becomes legal.

## 4. Wire model + UI

### 4.1 RecordingRow Pydantic model

[src/plaudsync/ui/state_reader.py:42](../../src/plaudsync/ui/state_reader.py#L42):

```python
status: Literal["downloaded", "failed", "skipped", "trashed"]
```

`wire_status` collapsing in same file: only `'skipped_unknown_project'` →
`'skipped'`. `'trashed'` passes through as-is.

### 4.2 Frontend types

[frontend/src/api/types.ts](../../frontend/src/api/types.ts) (path inferred —
verify): add `"trashed"` to `RecordingStatus` union.

### 4.3 ProjectBadge variant

[frontend/src/pages/Dashboard/ProjectBadge.tsx:69](../../frontend/src/pages/Dashboard/ProjectBadge.tsx#L69),
new branch BEFORE the `skipped` branch:

```tsx
if (status === "trashed") {
  return (
    <span
      className={classNames(PILL_BASE, GRAY)}
      title="Záznam byl smazán na Plaude. Lokální kopie odstraněna."
    >
      smazáno
    </span>
  );
}
```

Existing `if (status !== "downloaded")` early return at line 82 handles
`'trashed'` correctly (no project pill rendered after the badge branch).

## 5. Testing strategy

CLAUDE.md mandates TDD integration-first. Test layers:

### 5.1 Unit tests (pure logic) — `tests/unit/test_detect_trashed.py`

Mock `PlaudClient` (no cassette). Cover:

1. **Empty trash listing** → no-op, returns (0, 0).
2. **Trash listing with 1 ID matching downloaded row** → file deleted, DB updated, returns (1, 0).
3. **Trash listing with ID matching `status='failed'` row** → no-op (only `downloaded` rows touched).
4. **Trash listing with ID NOT in downloaded rows** → no-op.
5. **Batch safety guard fires (>10 AND >50%)** → no-op, no deletes, Sentry captured.
6. **Batch safety guard does NOT fire (small collection 7/12 — fails absolute threshold? no: 7>10? no, 7<10 so guard does NOT fire)** → 7 deletes proceed.

Wait, re-read Decision 6: `>10 AND >50%`. So 7/12 → `7 > 10` is False → guard does NOT fire → 7 deletes proceed. Correct. Test name: "burst_trash_below_absolute_threshold_proceeds".

7. **`local_path` file already missing from disk** → idempotent, DB still updated to `'trashed'`.
8. **`content_path` is None (audio-only mode, no `.md`)** → MP3 deleted, no `.md` attempt, DB updated.
9. **Per-row delete failure (e.g. permission error on unlink)** → that row stays `'downloaded'`, error captured, other rows still processed; returns (N-1, 1).

### 5.2 Integration test (cassette) — `tests/test_sync_trash_detection.py`

`@pytest.mark.vcr()` decorated. Records `/file/simple/web?is_trash=1` once.
Asserts:
- `_detect_trashed` integrates correctly into `run_sync`.
- DB row transitions from `'downloaded'` to `'trashed'` end-to-end.
- Local files removed.

**Cassette:** needs fresh recording from real Plaud account with at least
one trashed recording. Per `cassette-refresh` skill — will need explicit
session step.

### 5.3 Untrash integration test — `tests/test_sync_untrash_recovery.py`

Two-phase test:
- Seed DB with `status='trashed'` row.
- Run sync; mock listing returns the recording in `is_trash=0`.
- Assert DB row becomes `status='downloaded'`, file re-downloaded.

### 5.4 Schema migration test — `tests/test_state_migrations.py`

Existing migration test pattern; add case: pre-BL-8 DB (CHECK without
`'trashed'`) gets migrated to include `'trashed'`. Pre-BL-3 DB still
migrates to BL-3 form first, then BL-8 form (chained migrations).

### 5.5 Frontend test (manual)

Spin up dev server, manually verify:
- Recording in `status='trashed'` shows gray "smazáno" pill.
- Tooltip text correct.
- No project badge rendered alongside.

(BL-7 had a similar manual verification path — no Vitest infrastructure
exists yet for this UI; not adding it for BL-8.)

## 6. Privacy + observability

Per CLAUDE.md:
- Never inline title/recording filename in messages.
- Use `logger.bind(plaud_id=...)` and `scope.set_tag("recording_id", ...)`.
- `error_kind` tags: `'trash_mass_detection'` (Decision 6), `'trash_delete_failed'` (per-row failure).

`observability.py` scrubbing already handles structured tags. New
`error_kind` values are scrubber-safe by construction (they don't carry
business data).

## 7. Out of scope

- Trashed `status='failed'` rows: their DB row stays `'failed'` forever
  if Plaud trashes them. No filesystem to clean (failed = no download).
  Edge case is harmless; future BL-9 "DB hygiene" could reconcile.
- Trashed `status='skipped'` rows: same — no local files, just DB row.
- Plaud auto-purge from trash (Plaud's own retention): if Plaud purges
  before PlaudSync sees the row in `is_trash=1` listing, recording
  becomes invisible to PlaudSync. DB row stays `'downloaded'`,
  files stay orphan. **Mitigation:** out of scope for v1; would require
  full reconciliation pass (compare DB downloaded ∪ Plaud listings ∪
  Plaud trashed → orphan set). Track as forward-compat note for BL-9.
- Soft archive / mark-only policies: rejected per Decision 1.
- Filter chip "show deleted": rejected per Decision 4.

## 8. Estimated effort

- Backend: ~150 LoC (`list_trashed` ~25 + `_detect_trashed` ~70 +
  `_hard_delete_local` ~15 + schema migration ~25 + UPSERT extension 1
  token + sync.py wiring ~5 + run_sync stat aggregation ~3).
- Frontend: ~15 LoC (`RecordingStatus` type expansion + ProjectBadge
  branch + new tooltip string). Smaller than stub estimate (50) — no
  new component, just one branch.
- Tests: ~12 (unit 1-9 + integration cassette + untrash + migration).

## 9. Implementation order (TDD)

1. **Failing test first** — `tests/unit/test_detect_trashed.py` with
   case 1 (empty trash) AND case 2 (single trash deletes file). Commit
   the failing test alone.
2. **Schema migration** — add `'trashed'` to CHECK + new
   `_migrate_status_add_trashed`. Test migration first, then add.
3. **`PlaudClient.list_trashed`** — implement, with structural unit test
   (mock requests.Session). Cassette recording deferred to integration step.
4. **`_detect_trashed`** core — make unit test cases 1, 2 pass.
5. **Batch safety guard** — make unit test case 5 pass.
6. **Edge cases** — cases 3, 4, 6, 7, 8, 9.
7. **UPSERT extension** — write untrash test, then make pass (~1 line).
8. **`run_sync` wiring** — integration test with mocked client.
9. **Cassette recording** — invoke `cassette-refresh` skill for
   `is_trash=1` endpoint.
10. **Frontend** — types + ProjectBadge variant.
11. **`/review` slash command** before commit.
12. **`/security-review` + `bandit -r src/`** before merge to main.
13. **DEV_LOG.md update** + supersede stub.

## 10. Forward-compat notes

- BL-5 remaining sub-cases (folder move, content drift): independent
  surfaces. BL-8 doesn't block.
- BL-9 "DB hygiene" candidate: orphan reconciliation if Plaud auto-purge
  from trash before PlaudSync detection becomes a real incident.
