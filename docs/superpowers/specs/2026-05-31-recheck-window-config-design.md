# Recheck window config + process-only-new main loop (design)

> **Status:** locked design v1.0 (2026-05-31).
>
> **Brainstorm session:** 2026-05-31. Primary driver: processing time must not
> grow with total Plaud cloud size by re-checking old, settled recordings every
> run. Secondary: the re-check window must be user-configurable (currently a
> hardcoded 14 days).

## 1. Problem

`run_sync`'s main loop ([sync.py:800](../../../src/plaudsync/sync.py#L800))
iterates the **entire** Plaud listing every run (Fix B dropped the `since`
filter for correctness) and processes any recording whose status is not
`downloaded` — including ones already resolved as `skipped` /
`skipped_unknown_project`. `recording_exists_and_downloaded`
([state.py:85](../../../src/plaudsync/state.py#L85)) only short-circuits
`downloaded` rows, so every settled skip is re-classified and re-written
(`record_recording` UPSERT) on **every** run, forever.

Consequences:

- **Scaling:** per-run work grows with total cloud size, not with the number of
  genuinely new recordings. As the cloud accumulates hundreds/thousands of
  recordings the user will never change, sync time creeps up for no benefit.
- **Misleading counter:** all these re-skips increment `recordings_new`. Live DB
  shows `recordings_new=88` on every run although nothing new is downloaded
  (runs take ~3 s — confirming no real downloads, just re-classification +
  writes). The 88 are settled unknown-project / unclassified recordings.

There is already a bounded rolling re-check pass
(`_retry_skipped_unknown_project`, `days=14`) for `skipped_unknown_project`
rows, but the main loop re-checks **unboundedly in parallel**, defeating it.

## 2. Goal

1. Per-run processing cost proportional to **new** recordings, not total cloud
   size. Old, settled recordings cost at most a cheap existence check.
2. Re-check window (how far back settled recordings are re-evaluated) is a
   **user-configurable** number of days, default **14**, editable in the UI
   Settings panel.

## 3. Locked decisions (from brainstorm)

- **Cutoff date:** `created_at_plaud` (recording date). "N days back" = recording
  made within the last N days is re-checked; older is not.
- **Older-than-window skips:** stop re-checking; the DB row stays as `skipped`
  and the UI keeps surfacing it as "ignorováno". No data loss.
- **Approach B (chosen, cleaner):** the main loop processes only never-seen
  recordings; **all** re-checking of settled skips is delegated to the bounded
  rolling passes. (Approach A — age-gating inside the main loop — was rejected
  as leaving recent skips double-counted and keeping two re-check mechanisms.)
- **Configurable in UI:** dedicated numeric field in the Settings panel (not
  YAML-only).

## 4. Design

### 4.1 Config field

Add to `Config` ([config.py:48](../../../src/plaudsync/config.py#L48)):

```python
recheck_window_days: int = 14
```

- Validation: positive integer (`>= 1`). Absent key → default 14 (existing
  `config.yaml` files keep working, no migration). Invalid (≤0 / non-int) →
  `ConfigValidationError`, surfaced exactly as today (sync exit 7 / UI error).
- Serialized in `config_io.py` `ConfigResponsePayload` + the default YAML
  template; round-tripped on save.

### 4.2 Main loop — process only never-seen recordings

In `run_sync`, immediately before the download loop, prefetch the set of
already-resolved ids in **one** query:

```sql
SELECT plaud_id FROM recordings
WHERE status IN ('downloaded', 'skipped', 'skipped_unknown_project')
```

(Placed after the retry/reclassify passes at lines 766–791 so it reflects any
status upgrades they just made this run.)

Loop change:

```python
resolved = _resolved_plaud_ids(conn)   # set, one query
for i, meta in enumerate(metas):
    if meta.plaud_id in resolved:
        skipped_count += 1
        _emit("downloading", i + 1, total)
        continue
    try:
        _process_recording(...)
        new_count += 1
    except Exception:
        ... (unchanged) ...
```

- `failed` is deliberately **not** in the resolved set → failed downloads are
  retried next run (current behavior preserved).
- Never-seen recordings are processed regardless of age → preserves Fix B
  (delayed upload of an old recording is still downloaded the first time it is
  seen).
- A first-seen recording that gets skipped is counted in `recordings_new` once
  (the run it is discovered), then is in `resolved` forever → `recordings_new`
  settles to ~0 in steady state.

Implementation note: the per-record check becomes O(1) set membership; the
single prefetch query replaces N per-record `recording_exists_and_downloaded`
calls. Net per-run cost ∝ new recordings, not cloud size.

### 4.3 Rolling re-check passes driven by the config window

The three rolling passes currently hardcode `days=14`
([sync.py:767,777,786](../../../src/plaudsync/sync.py#L767)):

- `_retry_skipped_unknown_project`
- `_reclassify_recent`
- `_retry_pending_content`

Pass `days=config.recheck_window_days` to all three.

**Extend `_retry_skipped_unknown_project`** to cover both skip statuses:

```sql
WHERE status IN ('skipped', 'skipped_unknown_project')
  AND created_at_plaud >= ?   -- now - recheck_window_days
```

Rationale: with the main loop no longer re-checking skips, an *unclassified*
(`status='skipped'`) recording that the user renames on Plaud (so its title now
matches a project) must still be recovered within the window. The pass already
re-classifies against the live title (Fix A) and supports folder fallback via
`live_metas`, so widening the query is sufficient. The UPSERT path
`skipped → downloaded` is already supported (Hotfix L). Docstring updated to say
"recent skips (any skip reason)".

**Recovery triggers preserved within the window** (the main loop used to do all
of these via the full WaterfallClassifier; the bounded pass must match them so
delegation is regression-free):

1. **Title rename** → live-title re-classify (existing, Fix A).
2. **Folder move** → live-folder lookup via `lookup_by_folder_id` when
   `classify_by_folder=true` (existing).
3. **`sync_unclassified` flipped false→true** → when neither name nor folder
   matches but `config.sync_unclassified` is now true, the pass downloads the
   recording to `unclassified_dir` (label `_unclassified`) instead of
   `continue`-ing. This replaces the catch-all the unbounded main loop used to
   apply; without it, flipping the flag would no longer recover already-skipped
   unclassified recordings (regression). Bounded by the same window.

### 4.4 UI Settings field

- [types.ts](../../../frontend/src/api/types.ts): add `recheck_window_days: number`
  to the config type.
- [BlxSettingsPanel.tsx](../../../frontend/src/pages/Settings/BlxSettingsPanel.tsx)
  (or the Settings page): numeric input, `min=1`, labelled (e.g. "Re-kontrolovat
  záznamy zpětně (dní)").
- [configYaml.ts](../../../frontend/src/utils/configYaml.ts): serialize the
  field into YAML on save.
- [ui/app.py](../../../src/plaudsync/ui/app.py): `recheck_window_days` in the
  `ConfigResponse` / `ConfigSaveRequest` Pydantic models.

## 5. Data flow

```
list_recordings (all)  ─┐
                        ├─ retry/reclassify passes (window = config days)
resolved-ids prefetch ──┤      └ re-check + possibly upgrade settled skips
                        │
main loop: meta in resolved? ── yes ─► skipped_count++  (cheap, no work)
                        └──────── no ─► _process_recording → new_count++
```

## 6. Edge cases

- **Missing config key** → default 14, no migration.
- **Invalid value** (≤0, non-int) → `ConfigValidationError` (existing surfacing).
- **`failed` rows** → not resolved → retried by main loop next run.
- **Delayed upload of old recording** (Fix B) → never-seen → processed first time
  regardless of age.
- **Window shrink/grow at runtime** → next run simply uses the new value; no
  state to migrate.
- **Recording trashed on Plaud** → absent from `list_recordings`; `_detect_trashed`
  handles it independently (unchanged).

## 7. Testing

Backend (pytest):

- Main loop: an already-`skipped` recording is **not** re-processed (no
  `record_recording` write, `recordings_new` unchanged); a never-seen recording
  **is** processed; a `failed` recording **is** retried.
- Steady state: second run over the same listing yields `recordings_new == 0`.
- Retry pass — recovery within the window, not recovered outside it, for each
  trigger: (a) `skipped_unknown_project` whose project is added to config;
  (b) `skipped` (unclassified) renamed on Plaud so the title now matches;
  (c) `skipped` whose folder now maps to a project (`classify_by_folder=true`);
  (d) `skipped` (unclassified) after `sync_unclassified` is flipped true →
  downloaded to `unclassified_dir`.
- Config: absent key defaults to 14; `recheck_window_days <= 0` → validation
  error; round-trip through `config_io` preserves the value.

Frontend:

- Settings field renders, edits, and serializes into the saved YAML; rejects
  values < 1.

## 8. Out of scope

- Reducing the **listing fetch** cost itself (Plaud returns all recordings; a
  server-side `since` filter was removed by Fix B for correctness). This design
  bounds per-record *processing*, not the metadata fetch.
- Per-pass independent windows — one shared `recheck_window_days` governs all
  rolling re-checks (coherent: "how far back we re-check anything").
- Renaming `_retry_skipped_unknown_project` despite its now-broader scope (avoids
  churn across call sites/tests; docstring clarifies).
