# BL-6 — Source-aware project badge + post-sync refresh

> **Status:** v0.1 design (2026-04-30). Ready for implementation plan.
>
> **Predecessor:** BL-X (commit `78b6176`) introduced `classification_source`
> enum (`name` / `folder` / `none`) — required source-of-truth for this
> feature. BL-6 surfaces it through to UI and pairs it with a refresh fix
> for the post-sync stale-data bug.

## 1. Problem

### 1.1 Project badge shows the wrong identity for folder-classified recordings

[`frontend/src/pages/Dashboard/ProjectBadge.tsx`](../../../frontend/src/pages/Dashboard/ProjectBadge.tsx)
renders one of two states for every recording: a colored project pill
(deterministic hash → palette) when `classification_status = matched`,
or a gray "nezatříděno" pill otherwise. The badge does not differentiate
how the recording was classified.

For recordings that didn't match any title regex but were placed by
folder fallback (BL-X's `classify_by_folder=true` path), the user sees
the abstract project code, not the Plaud folder name they assigned in
the Plaud app. The user's mental model is broken — they assigned the
recording to a folder, but the UI claims it landed in a project.

### 1.2 Recordings list goes stale after manual sync completes

[`useStateQuery`](../../../frontend/src/api/hooks.ts#L33) polls
`/api/state` at 1.5 s while a sync is running and 30 s while idle. When
a manual sync transitions `running → idle`, the polling drops back to
30 s and there is no explicit cache invalidation. Result: the freshly
synced recordings do not appear in the Dashboard list until the user
either waits 30 s, refocuses the window (`refetchOnWindowFocus`), or
navigates away and back. Sync status text ("Poslední běh před X")
exhibits the same staleness intermittently.

## 2. Desired behavior

### 2.1 Badge rendering rules

| `classification_source` | Badge text | Badge color |
|---|---|---|
| `name` (regex match) | project code (`FHB`, `OEZ`) | **blue** |
| `folder` (folder fallback) | Plaud folder name (`Školení`) | **green** |
| `none` / unclassified / NULL legacy | `nezatříděno` | **gray** |

Single fixed palette per source — no per-project hashing. All
`name`-classified recordings share one blue tone; all `folder`-classified
share one green tone.

### 2.2 Edge cases

- **Failed / skipped recordings** — badge renders identically to
  `downloaded` recordings. Status icon already conveys outcome; no second
  visual is needed. (Deviates from earlier BL-6 stub which proposed
  hiding the badge for non-downloaded; user opted to keep current
  behavior to minimize scope.)
- **Folder no longer in catalog** — `plaud_folder_id` resolves but
  `FiletagCache.lookup_by_id()` returns nothing (folder was renamed or
  deleted in Plaud). Backend serializes `plaud_folder_name = ""`.
  Frontend displays `(neznámá složka)` in the green folder badge,
  signaling the user that filetag cache may need refresh.
- **Legacy rows** — recordings written before BL-X have
  `classification_source IS NULL`. Backend forwards `null`. Frontend
  treats `null` as if it were `name` (renders `classifier_label` value
  in the blue badge). No DB backfill — naturally phases out as new syncs
  populate the column.

### 2.3 Refresh after sync

When the polling response transitions `sync.status` from `running` to
`idle` (already detected in
[`AppShell.tsx:65-79`](../../../frontend/src/components/AppShell.tsx#L65-L79)
to fire the post-sync toast), the same effect invalidates the
`STATE_QUERY_KEY` cache. A second invalidation fires 1500 ms later as a
safety net against the SQLite write race where the sync subprocess
commits `sync_runs.finished_at` before the last `recordings` row is
durable. If both refetches return identical data, the second is a no-op
re-render of the same payload.

## 3. Backend changes

### 3.1 DB schema

Add nullable column via the existing migration pattern in
[`state.py`](../../../src/plaudsync/state.py):

```sql
ALTER TABLE recordings ADD COLUMN plaud_folder_id TEXT;
```

Idempotent — wrap in `try / except sqlite3.OperationalError` like
`_migrate_add_content_columns`. Add a new helper
`_migrate_add_plaud_folder_id_column` and call it from `open_state()`.

Update the canonical `_SCHEMA` definition to include `plaud_folder_id
TEXT` so fresh DBs created today have the column from the start.

### 3.2 `record_recording`

Add `plaud_folder_id: str | None = None` kwarg. Persist in the same
INSERT and UPDATE branches that already handle `classification_source`.
No new code paths — this is a column extension to an existing wire.

### 3.3 Sync engine

In [`sync.py`](../../../src/plaudsync/sync.py) `_process_recording`,
pass `plaud_folder_id=getattr(meta, "plaud_folder", None)` when calling
`record_recording`. Reuse the same value the meta object already
exposes; no new Plaud API call.

### 3.4 `state_reader._read_recordings`

Extend the SELECT to fetch `classification_source, plaud_folder_id`.
For each row, resolve `plaud_folder_name`:

- `plaud_folder_id IS NULL` → `None`
- `FiletagCache.lookup_by_id(plaud_folder_id)` returns name → that name
- cache miss → `""` (empty string sentinel; frontend renders placeholder)

`FiletagCache` is the same instance used by the BL-X folder catalog
endpoint. Read it once per `read_state_snapshot()` call — no per-row
re-instantiation.

### 3.5 Wire model

Extend `RecordingRowPayload` in
[`state_reader.py`](../../../src/plaudsync/ui/state_reader.py):

```python
class RecordingRowPayload(TypedDict):
    # existing fields…
    classification_source: Literal["name", "folder", "none"] | None
    plaud_folder_name: str | None
```

`plaud_folder` (the existing `_unknown` hardcode) stays for
backward-compat with the folder-icon row in
[`RecordingsList.tsx`](../../../frontend/src/pages/Dashboard/RecordingsList.tsx),
but `plaud_folder_name` is the field that drives the new badge.

## 4. Frontend changes

### 4.1 Types

[`frontend/src/api/types.ts`](../../../frontend/src/api/types.ts) extends
`RecordingRow`:

```ts
export interface RecordingRow {
  // existing fields…
  classification_source: "name" | "folder" | "none" | null;
  plaud_folder_name: string | null;
}
```

### 4.2 ProjectBadge component

[`ProjectBadge.tsx`](../../../frontend/src/pages/Dashboard/ProjectBadge.tsx)
new signature:

```tsx
interface Props {
  project: string | null;
  classification: ClassificationStatus;
  source: "name" | "folder" | "none" | null;
  folderName: string | null;
}
```

Render decision tree (top to bottom, first match wins):

1. `classification === "unclassified"` OR `source === "none"`
   → gray "nezatříděno" pill
2. `source === "folder"` → green pill, text =
   `folderName || "(neznámá složka)"`
3. `source === "name"` OR `source === null` (legacy) → blue pill,
   text = `project || "—"`

Single fixed Tailwind class set per branch — no `projectBadgeColor()`
hash function, no per-project variation.

### 4.3 Color palette

| Source | bg | text | border |
|---|---|---|---|
| `name` | `bg-blue-100` | `text-blue-700` | `border-blue-200` |
| `folder` | `bg-green-100` | `text-green-700` | `border-green-200` |
| `none` / unclassified | `bg-gray-100` | `text-gray-600` | `border-gray-200` (existing) |

`projectBadgeColor()` in
[`colors.ts`](../../../frontend/src/utils/colors.ts) becomes unused.
Delete the export and the function — no compatibility shim.

### 4.4 RecordingsList wiring

[`RecordingsList.tsx`](../../../frontend/src/pages/Dashboard/RecordingsList.tsx)
passes the two new props from `RecordingRow` into `<ProjectBadge>`. No
other changes (folder-icon row stays as-is).

### 4.5 Mock fixtures

[`MockProvider.tsx`](../../../frontend/src/dev/MockProvider.tsx) gains
example rows for each `classification_source` value (`name`, `folder`,
`folder` with cache-miss, `none`, `null` legacy) so the dev panel
toggles can exercise all 5 render branches.

## 5. Refresh fix

[`AppShell.tsx`](../../../frontend/src/components/AppShell.tsx) imports
`useQueryClient` and `STATE_QUERY_KEY`. The existing `running → idle`
detection effect (lines 65-79) gains:

```tsx
qc.invalidateQueries({ queryKey: STATE_QUERY_KEY });
const t = setTimeout(() => {
  qc.invalidateQueries({ queryKey: STATE_QUERY_KEY });
}, 1500);
return () => clearTimeout(t);
```

Effect already gates on `prev === "running" && sync.status === "idle"`
plus the `seenRunRef` dedupe, so the invalidation fires exactly once
per completed run.

## 6. Testing

### 6.1 Backend

- **`tests/test_state_migrations.py`** — add `test_migration_adds_plaud_folder_id_column`:
  open `state_root` with a pre-BL-6 DB (manually create old schema in a
  tmp file), run `open_state()`, assert column exists via
  `PRAGMA table_info(recordings)`.
- **`tests/test_ui_state_reader.py`** — extend with parametrized cases:
  - `classification_source='name'` + valid `plaud_folder_id` → wire shows
    project text, source `"name"`, `plaud_folder_name` populated.
  - `classification_source='folder'` + valid id → wire shows folder name.
  - `classification_source='folder'` + cache miss → `plaud_folder_name = ""`.
  - `classification_source='none'` → both new fields populated per spec
    (source `"none"`, `plaud_folder_name` whatever).
  - `classification_source IS NULL` (legacy row) → wire forwards `null`.
- **`tests/unit/test_state_record.py`** (new file or merge into existing
  state test): assert `record_recording(plaud_folder_id="abc123")`
  persists and round-trips.
- No cassette tests — the change is pure SQLite + cache lookup; Plaud
  API surface unchanged.

### 6.2 Frontend

- **`frontend/src/pages/Dashboard/ProjectBadge.test.tsx`** (new):
  vitest + React Testing Library, 5 cases mirroring §4.2 decision tree
  (name, folder-resolved, folder-unknown, none, null-legacy).
- **`frontend/src/components/AppShell.test.tsx`** (new): vitest test
  that renders AppShell with a state query mock, transitions
  `sync.status` from `running` to `idle`, asserts `invalidateQueries`
  was called for `STATE_QUERY_KEY`.

### 6.3 Manual verification

After implementation, manual smoke test in dev panel:
- Toggle each mock row classification scenario, screenshot the 5 badge
  variants render correctly.
- Trigger a real sync (cassette-recorded) and watch the recordings list
  populate within ~100 ms of `sync.status` flipping to idle (instead of
  the prior ~30 s wait).

## 7. Out of scope

- Hiding the badge for `failed` / `skipped` recordings (deferred —
  current behavior preserved).
- Per-project color differentiation (explicitly removed; could be
  re-added as a config knob in a future iteration).
- Showing the folder ID alongside the name (kept simple — name only).
- Length truncation for long folder names (Tailwind `truncate` already
  applies via parent layout; no special handling).
- Backfilling `plaud_folder_id` for legacy rows (forward-only).

## 8. Estimated effort

- **Backend:** ~60 LoC (migration helper, `record_recording` kwarg,
  `state_reader` resolve, sync.py call site) + 4 tests.
- **Frontend:** ~40 LoC (types, ProjectBadge rewrite, AppShell
  invalidate, MockProvider fixtures) + 4 tests.
- **Total:** ~100 LoC net + 8 tests.
- **Dependencies:** none — `classification_source` and `FiletagCache`
  already in place from BL-X.

## 9. Risks

- **DB migration on first launch after upgrade** — adding a nullable
  column is the safest possible schema change; idempotent helper
  pattern is already exercised in `_migrate_add_content_columns`. Risk
  low.
- **Cache miss rate visibility** — if many recordings show
  `(neznámá složka)`, that's a signal `filetag_cache` is stale and the
  user should hit the refresh button in Settings. No new privacy or
  correctness concern.
- **Refresh fix masking real bug** — the 1500 ms second-pass invalidate
  could hide a deeper SQLite ordering issue. Acceptable for v0; if the
  pattern repeats elsewhere, escalate to a write-fence in `sync.py`.
