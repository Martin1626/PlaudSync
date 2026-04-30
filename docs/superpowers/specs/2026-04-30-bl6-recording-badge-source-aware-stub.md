# BL-6 — Source-aware recording badge in Dashboard

> **Status:** stub v0.1 (2026-04-30). NOT YET IMPLEMENTED. Backlog ticket
> filed to capture requirements + design direction.
>
> **Predecessor:** BL-X (commit `78b6176`) introduced
> `classification_source` enum (`name` / `folder` / `none`) — required
> source-of-truth for this feature. BL-6 surfaces it through to UI.

## 1. Problem

Today's Dashboard ([frontend/src/pages/Dashboard/ProjectBadge.tsx](../../../frontend/src/pages/Dashboard/ProjectBadge.tsx))
renders the colored project badge for every recording with
`classification_status='matched'`, regardless of `status`. So skipped /
failed rows still display a badge — confusing UX, the user sees "ALZA"
on a recording that was never actually downloaded into the ALZA folder.

Plus when `classify_by_folder=true` matches a folder-only recording, the
badge shows the project code (`ALZA`) but not which **Plaud folder**
triggered the match. The user has no signal that the recording was
classified via folder fallback rather than title regex.

## 2. Desired behavior

| `status` | `classification_source` | Badge text | Badge visible? |
|---|---|---|---|
| `downloaded` | `name` | project code (e.g. `ALZA`) | ✅ |
| `downloaded` | `folder` | Plaud folder NAME (e.g. `Alza.sk`) | ✅ — different visual hint (icon?) |
| `downloaded` | `none` | nezatříděno | ✅ (existing gray badge) |
| `skipped` / `failed` | any | — | ❌ no badge |

The semantic: badge = "this recording was successfully placed into a
project folder". For folder-classified recordings, surface the folder
NAME (the user's mental model — they assigned the recording to a folder
in Plaud) rather than the abstract project code.

## 3. Backend changes needed

### 3.1 Persist `plaud_folder_id` per recording

Currently [state_reader.py:104](../../../src/plaudsync/ui/state_reader.py#L104)
hardcodes `plaud_folder: "_unknown"` because the column doesn't exist.
Add nullable column:

```sql
ALTER TABLE recordings ADD COLUMN plaud_folder_id TEXT;
```

Populated during `_process_recording` from `meta.plaud_folder`. Idempotent
migration via existing `_migrate_*` pattern.

### 3.2 Extend wire model

`RecordingRow` (Pydantic + TS types) gains 2 new fields:

```python
class RecordingRow(BaseModel):
    # existing fields…
    classification_source: Literal["name", "folder", "none"] | None = None
    plaud_folder_name: str | None = None
```

`plaud_folder_name` is resolved at serialize time from `FiletagCache.lookup_by_id(plaud_folder_id)`. NULL when:
- `plaud_folder_id IS NULL`
- folder no longer in catalog (deleted / renamed in Plaud) — graceful degradation: send empty string, frontend shows "(neznámá složka)"

### 3.3 Backward-compat for legacy rows

Pre-BL-6 rows have `classification_source IS NULL`. Wire response sends
`null` → frontend treats as "name" (preserves existing badge behavior for
old recordings). No backfill migration — gradually phases in as new syncs
populate the column.

## 4. Frontend changes needed

### 4.1 ProjectBadge component signature

```tsx
interface Props {
  project: string | null;
  classification: ClassificationStatus;
  source: "name" | "folder" | "none" | null;
  folderName: string | null;
  status: RecordingStatus;  // NEW — gate visibility
}
```

Render rules:
1. `status !== "downloaded"` → return `null` (no badge at all)
2. `classification === "unclassified" || source === "none"` → existing gray
   "nezatříděno" pill
3. `source === "folder" && folderName` → display folderName with a small
   folder-icon prefix (visual differentiator from name-classified)
4. otherwise → existing colored project badge with `project` text

### 4.2 RecordingsList wiring

Pass new fields from `RecordingRow` payload through to `<ProjectBadge>`.

## 5. Testing

- **Backend:** `tests/test_ui_state_reader.py` — existing test cases extend
  to assert new fields surface. Add row fixtures for each
  `classification_source` value × each `status` value matrix (12 cases,
  but most collapse — failed/skipped don't need source variation).
- **Frontend:** new test for ProjectBadge component covering the 4 render
  branches. Existing dev panel mock data
  ([frontend/src/dev/MockProvider.tsx](../../../frontend/src/dev/MockProvider.tsx))
  needs new fixture rows with `source: 'folder'` examples.

## 6. Open questions to lock during brainstorm

1. **Folder name fallback when not in catalog:** `(neznámá složka)` placeholder
   vs. silent fallback to project code. Going with placeholder feels right
   (signals to user that filetag_cache may need refresh) — confirm.
2. **Folder NAME vs. folder ID in badge:** if user prefers compact ID
   (`8ed7ab6e…`), might fit narrow tables better. Likely no — names are
   the user's mental model. Default name; ID only on hover tooltip.
3. **Visual distinction name-vs-folder:** icon prefix? different shade
   of the same color? subtle border style?
4. **Length truncation:** project codes are typically 3-5 chars. Folder
   names can be longer (`Moravia Cans`, 12 chars). Truncation at 16 char
   with hover tooltip showing full name?

## 7. Estimated effort

- Backend: ~50 LoC + 4 tests (DB column, state_reader, wire model, tests).
- Frontend: ~30 LoC + 4 component tests.
- Total: ~100 LoC net new + 8 tests.
- Dependencies: none — `classification_source` and `filetag_cache` already
  in place from BL-X.

## 8. Triggers to start

- After BL-5 lands (or in parallel — independent surface).
- Or sooner if user explicitly asks. UX polish only — no correctness impact.
