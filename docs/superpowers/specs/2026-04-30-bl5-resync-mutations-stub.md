# BL-5 — Re-sync Plaud-side mutations (rename / folder move / trash)

> **Status:** stub v0.1 (2026-04-30). NOT YET IMPLEMENTED. This is a scope
> doc for the next brainstorm session — captures requirements + design
> direction so when you pick this up, you don't restart from scratch.
>
> **Trigger:** real-world friction surfaced 2026-04-30 — recordings
> renamed / moved / trashed on Plaud after first sync are invisible to
> PlaudSync. See [DEV_LOG.md](../../../DEV_LOG.md) entry for that date.
>
> **Predecessor:** BL-4/BL-X
> ([2026-04-29-bl4-bl-x-content-classifier-design.md](2026-04-29-bl4-bl-x-content-classifier-design.md)).
> A+B+C fixes (commit `6c74d50`) handle the *not-yet-downloaded* (skipped)
> case via live title in retry pass. **Hotfix F (commit `bd44722`,
> 2026-04-30)** shipped rename detection for *already-downloaded* rows
> via expansion of `_reclassify_recent`. BL-5 remaining scope is the
> three sub-cases below.

## 1. Problem

After BL-4/BL-X + 6c74d50 + Hotfix F (commit `bd44722`), the rename
sub-case is shipped. Three Plaud-side mutations remain unhandled
for `status=downloaded` recordings:

| Mutation | Current behavior | Desired |
|---|---|---|
| ~~User renames recording on Plaud~~ | ✅ **SHIPPED Hotfix F** — `_reclassify_recent` reads live title from listing, moves files + updates DB on label change | — |
| User moves recording to a different Plaud folder | If `classify_by_folder=true`, classification could change. Currently no re-eval. | Detect via `filetag_id` diff, re-classify, move to new project dir, atomic. |
| User trashes recording on Plaud | Listing filter `is_trash=0` hides trashed → PlaudSync sees nothing. Local MP3 + .md remain orphan. | Detect via separate `is_trash=1` listing, delete local files, mark DB row `trashed`. |

Plus a fourth case from BL-4 spec carry-forward:

| Mutation | Current behavior | Desired |
|---|---|---|
| Plaud regenerates summary / outline / transcript (user replaces speaker, edits transcript, etc.) | Local .md is frozen at first download. | Detect via `task_id_info` fingerprint diff vs. stored `recordings.content_task_ids`. Re-fetch + overwrite .md. |

## 2. Non-goals (out of scope BL-5)

- **User-edited local .md preservation:** if user manually edits the local
  `.md` and Plaud also regenerates content, we cannot merge. Detect (mtime
  newer than download) → log warning + skip overwrite + Sentry capture.
  Do NOT attempt 3-way merge.
- **Recording UN-trash:** if user pulls a trashed recording back, we don't
  resurrect the local file. Forward-only — fresh download.
- **Plaud account migration / region change:** out of BL-5; falls under
  region probe semantics.
- **Bidirectional sync:** PlaudSync remains pull-only. Local edits are
  never pushed back to Plaud.

## 3. Decisions to lock in (during brainstorm)

1. **Detection cadence:**
   - (a) Every sync run does full diff of all `downloaded` rows against listing → high cost on large accounts (1000+ recordings)
   - (b) Sliding 30d window — re-eval only recent rows (analogous to BL-3 retry)
   - (c) On-demand only — UI button "Re-sync Plaud changes"

2. **Trash semantic:**
   - (a) Hard delete local file + .md when Plaud trash detected
   - (b) Soft — move to a `_trashed/` subfolder under `unclassified_dir`, leave for user
   - (c) Mark DB row only, leave files (user manages cleanup)

3. **Rename collision:** new slug already exists locally (e.g., from another recording). Options:
   - (a) Suffix `-2`, `-3`, etc. on the new file
   - (b) Skip + log warning (don't rename — keep old)
   - (c) Compare file_md5 / size; if same → assume duplicate, delete one

4. **Folder change for name-classified recordings:**
   - If recording is classified by NAME regex (`source='name'`), folder
     change on Plaud is irrelevant — local stays in regex-derived project.
   - Only `source='folder'` recordings re-classify on folder move.
   - Confirm: this is the right rule, or should we always honor folder
     hints when present?

5. **content_task_ids fingerprint scope:**
   - All 3 task IDs (trans + outline + summary) compared as a set?
   - Or per-section (only re-fetch the changed section)?
   - Per-section is more efficient but `compose_markdown` re-emits the
     full file anyway, so not much savings.

6. **DB schema delta:**
   - New `status` value `'trashed'` — needs CHECK constraint update
     (rebuild table; see existing `_migrate_status_check_constraint`)
   - Or new boolean `recordings.is_trashed`?
   - Or repurpose `status='skipped'` with a new sub-reason field?

## 4. Architecture sketch

```
src/plaudsync/sync.py:

def _resync_downloaded_rows(conn, client, classifier, config, live_metas, *, days=30):
    """Periodic pre-pass — reconcile already-downloaded rows with live Plaud state.

    Detects:
    - title rename → atomic file rename + DB update
    - folder move (source='folder' only) → re-classify + cross-project move
    - trash → delete local files + DB status='trashed'
    - content task_id drift → re-fetch + overwrite .md

    Only operates on rows with downloaded_at >= now - days (default 30 days)
    to bound cost. Older downloaded rows are frozen — assumed stable.
    """
```

Pre-pass order in `run_sync` (after BL-5):
1. `_retry_skipped_unknown_project` (BL-3)
2. `_reclassify_recent` (existing)
3. `_retry_pending_content` (BL-4)
4. **`_resync_downloaded_rows` (BL-5 — NEW)**
5. Main download loop

`_resync_downloaded_rows` reuses the same `live_metas` dict pre-fetched
at top of `run_sync`. Plus one separate `is_trash=1` listing call to
detect trashed rows (~one HTTP roundtrip).

## 5. Forward-compat already in place (BL-4)

DB schema already has:
- `content_task_ids TEXT` — JSON snapshot of `task_id_info` at download
  time. BL-5 compares fresh task IDs from `/file/detail/{id}` against
  this snapshot.
- `classification_source TEXT` — `'name'` / `'folder'` / `'none'` —
  BL-5 reads to decide whether folder move triggers re-classify.
- `local_path TEXT`, `content_path TEXT` — both updated atomically on
  rename / move.

No new columns needed for rename + move + content drift detection. The
`status='trashed'` enum value requires the `_migrate_status_check_constraint`
pattern (see [state.py:135](../../../src/plaudsync/state.py#L135)).

## 6. Risks / kill criteria carry-over

- **Concurrent sync vs. resync:** if `_resync_downloaded_rows` is moving
  files while UI/file-watcher is reading, race → reader sees half-state.
  Mitigation: existing `SyncLock` covers main sync; resync runs under
  same lock.
- **User-edited .md overwrite:** content drift re-fetch overwrites local
  edits silently. Mitigation: mtime check + skip + warn.
- **Cost on large accounts:** 30d sliding window keeps it bounded; if
  over 5000 rows per pass observed, switch to (b) sampled or (c)
  on-demand cadence.
- **Kill criterion #19 dependency:** `classification_source` distribution
  measurement assumes downloaded rows stay accurately labeled. Folder
  re-classify in BL-5 changes the source mid-life — make sure telemetry
  query accounts for this (e.g., latest snapshot only).

## 7. Estimated effort

- 1 spike (probe `is_trash=1` listing endpoint shape, confirm filetag_id
  diff semantics on folder move)
- 1 brainstorm session (lock decisions 1–6 above)
- 1 spec doc + plan
- 8–12 implementation tasks (TDD, mostly mock-based; needs 2 new cassettes
  for trash listing + content regen)
- LoC: ~400-600 net new (within remaining backend budget per
  [SPEC.md](../../../SPEC.md))

## 8. Triggers to start BL-5

- User reports recurring friction (rename/move/trash mismatch) — already
  observed once (2026-04-30). Tolerable threshold: 3 incidents in 30 days
  → start BL-5.
- Or: run for 30 days post-BL-4 with kill-criterion-19 telemetry; if
  folder-classified rows >30 % of total, BL-5 needed before scaling
  classify_by_folder use.

Do not start until BL-4/BL-X has 30 days of soak — premature optimization
risk if BL-4 surface area changes during that window.
