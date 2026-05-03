# BL-8 — Plaud-side trash detection (subset of BL-5)

> **Status:** SUPERSEDED by [2026-05-03-bl8-trash-detection-design.md](2026-05-03-bl8-trash-detection-design.md)
> (locked design v1.0). Shipped 2026-05-03 in commit `6a99071`. This stub
> remains for historical context — open decisions in §6 were resolved in
> the design doc, plus one new decision (batch safety threshold).
>
> **Predecessor / Parent:** BL-5 stub (`2026-04-30-bl5-resync-mutations-stub.md`)
> identified trash-detection as one of three remaining sub-cases. Hotfix F
> (commit `bd44722`) shipped the rename sub-case. BL-8 carves out trash
> detection as standalone — it has different scope (separate `is_trash=1`
> listing call) and different trigger conditions (orphan local files) than
> rename or folder-move. Folder-move + content-drift remain in BL-5.

## 1. Problem

PlaudClient's `list_recordings` hardcodes `is_trash=0`:

```python
resp = self._session.get(url, params={"skip": skip, "limit": page_size, "is_trash": 0})
```

Trashed recordings are invisible to PlaudSync at API level. Consequence
for **already-downloaded** recordings that user later trashes on Plaud:

- DB row stays as `status='downloaded'` (forever).
- Local MP3 + .md sourozenec stay on disk (orphan files).
- UI Recordings list keeps showing the recording as fine (until pagination
  drops it). User has no idea Plaud-side state changed.

Privacy + housekeeping concern: trashed recordings often = sensitive content
the user explicitly wanted to delete. Local copies surviving silently is
a leak risk.

## 2. Desired behavior

When user trashes a recording on Plaud:

1. PlaudSync detects the trash on next sync.
2. Configurable response (decision to lock during brainstorm):
   - **Hard delete** local MP3 + .md, mark DB row `status='trashed'`.
   - **Soft archive** — move local files to `${unclassified_dir}/_trashed/`,
     mark DB row `status='trashed'`, retain for user manual cleanup.
   - **Mark only** — leave files in place, just flip DB status. User decides
     cleanup manually.

UI gains visual indicator for trashed recordings (red strikethrough? gray
"(odstraněno na Plaude)" pill?).

## 3. Detection mechanism

### 3.1 New listing call

Each sync run calls `/file/simple/web?is_trash=1` once (separate from the
existing `is_trash=0` listing). Returns list of trashed recordings.

Cost: +1 HTTP request per sync. Trashed list is typically small (Plaud may
auto-purge after N days). Acceptable.

### 3.2 Diff against downloaded rows

```python
trashed_ids = {meta.plaud_id for meta in client.list_trashed()}
downloaded_ids = {row[0] for row in conn.execute(
    "SELECT plaud_id FROM recordings WHERE status='downloaded'").fetchall()}
to_resolve = trashed_ids & downloaded_ids
```

For each `to_resolve` row → apply chosen response (delete / archive / mark).

### 3.3 Edge case: untrashed recording

User puts recording back from trash. PlaudSync would re-discover via
normal `is_trash=0` listing, but what state does it end up in?

- If we deleted local files: row was marked `status='trashed'`. Recording
  comes back via main loop, `recording_exists_and_downloaded` returns
  False (status≠downloaded), main loop downloads fresh copy. OK.
- If we soft-archived: same path; old file in `_trashed/` stays orphan.
  User cleanup needed.
- If we marked-only: status flip back to `'downloaded'` requires UPSERT
  rule extension (Hotfix L lesson — audit checklist).

## 4. Schema delta

New `status` enum value: `'trashed'`. Requires `_migrate_status_check_constraint`
rebuild (existing pattern).

Wire model + TS types add `'trashed'`. UI Badge variant.

## 5. Sync engine architecture

New pre-pass `_detect_trashed(conn, client)` runs at top of `run_sync`,
analogous to `_retry_skipped_unknown_project`:

```python
def _detect_trashed(conn, client) -> tuple[int, int]:
    """Returns (trashed_count, failed_count).

    Lists trashed recordings on Plaud; for each that matches a local
    downloaded row, applies the configured trash policy.
    """
    if not hasattr(client, "list_trashed"):
        return 0, 0
    ...
```

Plus new `PlaudClient.list_trashed()` method (mirrors `list_recordings`
but with `is_trash=1`).

## 6. Decisions to lock during brainstorm

1. **Default trash policy:** hard delete / soft archive / mark only?
   Recommend **soft archive** as default — user has 14d to undo via filesystem
   without complex undo machinery. Configurable via new
   `trash_policy: hard | archive | mark` flag.

2. **Untrash recovery semantic:** if soft-archived, do we reuse the archived
   file or download fresh? Recommend fresh download — Plaud may have
   regenerated content (BL-5 task_ids drift territory). Old archived MP3
   could differ from current Plaud state.

3. **Sentry alert on trash with content_status='complete':** the `.md` file
   has business content. User trashing the recording probably wants the
   sensitive material gone. Sentry capture on auto-delete vs. silent?
   Recommend silent (this is intentional user action) but log structured
   event for audit.

4. **UI strike-through vs. removal:** show trashed rows with visual
   indicator vs. exclude from list with "X recordings deleted on Plaud"
   counter? Recommend show with strike-through — user keeps awareness.

5. **Pagination impact** (same as BL-7): trashed rows could clog the UI
   list. Filter chip "show deleted" toggle?

## 7. Privacy considerations

- Trashed recording filename → DB row may persist with title. Per
  CLAUDE.md privacy rules, never inline title in exception messages.
  Extend existing scrubbing (`observability.py`) to handle new
  `error_kind='trash_detection_failed'` tag if applicable.
- If hard-delete chosen, ensure file is securely overwritten (consider
  tempfile.SpooledTemporaryFile semantics)? Probably overkill for v1 —
  OS-level delete suffices for normal user expectations.

## 8. Estimated effort

- Spike: 1 small (probe `/file/simple/web?is_trash=1` shape, confirm
  endpoint behavior + scrubbing for cassette test).
- Brainstorm: 1 session (decisions 1-5 above).
- Implementation: ~150 LoC backend (`PlaudClient.list_trashed` method,
  `_detect_trashed` pass, `record_recording` UPSERT extension for
  `'trashed'` status, schema migration, trash_policy config flag).
- Frontend: ~50 LoC (TS type + badge variant + tooltip).
- Tests: ~10 (parametrized over policy flag, untrash path, schema
  migration).

## 9. Triggers to start

BL-5 stub had this sub-case at "wait for first incident" trigger.

**Suggested trigger threshold (relaxed from BL-5):** start BL-8 brainstorm
after **3 incidents in 30 days** OR **post-BL-X 14-day soak complete**
(extends BL-5 7d soak — see DEV_LOG 2026-04-30 entry on hotfix-storm).
This gives breathing room before adding more state machine surface area.

## 10. Forward-compat with BL-5 sub-cases

BL-8 is fully independent:
- **Folder move detection** (BL-5 remaining): different signal source
  (`filetag_id` change vs. `is_trash` flag), different mitigation (move
  files to new project dir vs. delete).
- **Content drift** (BL-5 remaining): different signal (`task_id_info`
  change vs. listing diff), different mitigation (re-fetch + overwrite
  .md vs. delete).

All three could ship independently; BL-8 first if user trashing is the
primary friction surface.
