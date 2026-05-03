# BL-7 — Surface ignored recordings in UI

> **Status:** stub v0.1 (2026-04-30). NOT YET IMPLEMENTED. Backlog ticket
> filed to capture requirements + design direction.
>
> **Predecessor:** BL-X waterfall (commit `78b6176`) introduced
> `outcome.source == "skip"` semantic — recording invisible to PlaudSync
> when no classification strategy applies AND `sync_unclassified=False`.
> User confusion surfaced 2026-04-30 (recordings silently dropped, user
> couldn't tell if PlaudSync saw them at all). BL-7 surfaces them so the
> drop is observable + actionable.

## 1. Problem

Today's WaterfallClassifier flow drops recordings outright when:
- Title doesn't match name regex (`MM-DD KOD:`)
- AND folder doesn't map to any configured project (`classify_by_folder=true` but folder not in projects' `plaud_folder_id`)
- AND `sync_unclassified=False`

`_process_recording` returns immediately at the `outcome.source == "skip"` check; **no DB row is created**, no log entry beyond debug-level.

User-facing consequence: Plaud has the recording, PlaudSync ignored it, UI shows nothing. User has no signal:
- Did PlaudSync see the recording at all?
- Why was it dropped?
- What action recovers it?

This is exactly the friction surfaced by `04-30 Strategický rozpor mezi evidencí…` (no `:` in title, in `_unknown` folder) — user assumed sync was broken, actually was working as designed but invisibly.

## 2. Desired behavior

| State | Today | After BL-7 |
|---|---|---|
| Recording matches strategy | row='downloaded' / 'skipped' / 'skipped_unknown_project' | unchanged |
| Recording matches no strategy + `sync_unclassified=true` | row='downloaded' label='_unclassified' source='none' | unchanged |
| **Recording matches no strategy + `sync_unclassified=false`** | **NO ROW (invisible)** | **row='ignored' source='skip' visible in UI** |

UI Recordings list gains a visual indicator (gray "ignored" pill, with tooltip explaining why) for skip-source rows. Optional: "X ignored" counter at top of the list with click-to-filter.

## 3. Schema delta

Add new `status` enum value: `'ignored'`.

Schema CHECK constraint update via existing `_migrate_status_check_constraint` pattern (rebuild table). Wire model + frontend `RecordingStatus` type adds `'ignored'` literal.

Or simpler: reuse existing `'skipped'` status with a new `classification_source='skip'` discriminator. Avoids schema migration. UI distinguishes via source field.

**Decision to lock:** new enum value vs. reuse skipped + source discriminator. Recommend the latter — simpler migration, leverages existing `classification_source` column from BL-X.

## 4. Sync engine change

`_process_recording` change:

```python
if outcome.source == "skip":
    # BL-7 (NEW): record metadata for UI visibility instead of silent drop.
    record_recording(
        conn, meta, status="skipped",
        local_path="", run_id=run_id,
        classifier_label="_unclassified",
        classification_source="skip",
        plaud_folder_id=_meta_folder_id(meta),
    )
    return
```

This is a 1-method extension. No new logic, just persistence.

## 5. UI changes

### 5.1 Wire model

`RecordingRow.classification_source` already includes `'skip'` literal? Currently `Literal["name", "folder", "none"] | None` per state.py. Add `'skip'` to the union.

### 5.2 Badge component (BL-6 dependency)

When BL-6 ships source-aware badges:
- `source='skip'` → gray pill "(ignorováno)" with tooltip:
  > Recording neodpovídá žádné klasifikační strategii. Možnosti:
  > - Přidat KOD: do názvu na Plaude
  > - Přesunout recording do mapované Plaud složky
  > - Zapnout „Synchronizovat i to, co nelze roztřídit" v Settings

### 5.3 Optional: ignored count chip

Top of Recordings list: `12 položek · 3 ignorováno`. Click → filter view.

## 6. Edge cases

1. **User adds project to config** that matches a previously-ignored recording's title. BL-3 retry pass currently ignores `'skipped'` rows (only checks `'skipped_unknown_project'`). Need to extend retry pass to also re-evaluate skip-source rows when classifier could now classify them.

2. **User toggles `sync_unclassified=true`.** Previously-ignored rows should upgrade. State.py UPSERT logic (per Hotfix L lessons) needs to allow `'skipped' → 'downloaded'` transition for source='skip' rows. Already handled by Hotfix L.

3. **Pagination impact.** Adding ignored rows could blow up the 50-row Recordings list. Default state_reader limit may need increase or filter (e.g., toggle "show ignored" off by default).

## 7. Estimated effort

- Backend: ~30 LoC + retry pass extension. 4-5 tests (write skip row, retry on config change, UPSERT round-trip, etc.).
- Frontend: ~50 LoC (BL-6 dependency for badge styling + tooltip + optional filter chip).
- Total: ~80 LoC + 6 tests. Depends on BL-6 for nice badge UX, but core surface (DB row exists, basic gray badge) is BL-6-independent.

## 8. Open questions

1. **Status value: new enum `'ignored'` or reuse `'skipped'` + source='skip' discriminator?** Recommend reuse (no schema migration).
2. **Pagination treatment**: default visible vs. hidden filter chip?
3. **Auto-classify when config changes**: should retry pass actively re-evaluate skip-source rows on every sync, or only on explicit user trigger? Reactive vs. proactive.
4. **Tooltip in Czech vs. English**: SPEC.md is bilingual; UI is primarily Czech. Lean Czech for tooltips.

## 9. Triggers to start

- Independent of other BLs. Can ship anytime.
- Soft prerequisite: BL-6 source-aware badge for nice rendering. Without BL-6, ignored row appears as `'skipped'` with no project — usable but not great UX.
- Recommend ship after 7 consecutive bug-free days post-BL-X stabilization (current: day 0 of cool-down).
