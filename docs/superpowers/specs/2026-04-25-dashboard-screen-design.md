# Dashboard screen — design spec (extracted from prototype + review delta)

> **Status:** v0 (2026-04-25). Extracted from validated Claude Design prototype `frontend/PlaudSync UI.html` after review against [UI architecture umbrella spec v0.2](2026-04-25-ui-architecture-design.md) and [sync-core spec v0.2](2026-04-25-sync-core-design.md). **Not a brainstorm output** — design rozhodnutí byla učiněna v Claude Design prototype session; tento dokument je extracted contract + review findings + acceptance criteria pro implementaci.
> **Scope:** Dashboard screen (route `/`), one of two MVP screens. Sync trigger + recordings list. Empty / loading / running / idle / banner states.
> **Preceded by:** UI architecture umbrella v0.2, sync-core v0.2, categorization v0.2, [frontend/PlaudSync UI.html](../../../frontend/PlaudSync%20UI.html) prototype (commit `1ea6bd3`).
> **Next step:** UI backend writing-plans cyklus (po dokončení sync-core impl). Dashboard frontend writing-plans cyklus (po Settings spec + UI backend impl).

## Problem

Po SPEC pivotu (2026-04-24) je UI součástí MVP scope. UI architecture umbrella zafixovala napříč-screen kontrakty (FastAPI endpointy, polling pattern, error taxonomy, layout shell). Per-screen Dashboard design byl materializován v Claude Design jako interaktivní HTML+React+Tailwind prototype s 5 plně-funkčními scenarios (idle, running UI, running TS, partial_failure, failed, empty) + ConnectionLostOverlay + 12 sample recordings demonstrating per-project absolute path layout.

Tento dokument extrahuje implementation contract z prototypu (ne re-design) a identifikuje delta proti specs (gaps, missing edge cases, open implementation questions).

## Scope (tato feature)

- **Component tree** pro Dashboard route — `<SyncNowPanel>`, `<RecordingsList>` (s `<StatusIcon>`, `<ProjectBadge>` sub-components).
- **State→UI mapping table** — explicit binding between `StateResponse` Pydantic shape (UI architecture spec) a vizuální stavy v prototypu.
- **Interaction contract** — Sync Now button click handler, polling cadence behavior, banner→action mapping.
- **Empty / loading / error variants** — extracted z prototype.
- **Localization** — prototype je v češtině (per user preference). Implementation MUSÍ použít stejné stringy.
- **Animations** — `ps-pulse`, `ps-indeterminate`, `ps-toast-in` keyframes z prototype CSS (přesunout do Tailwind config / utility CSS modul).

## Out of scope (this screen)

- **Filtering / sorting / search** — out of MVP per SPEC.md / UI umbrella.
- **Click-row drill-down detail view** — `<li>` má `cursor-default` + hover state ale žádný onClick. v1.1+ rozšíření.
- **Pagination** — last 50 hard limit per UI architecture spec, žádný "load more".
- **Tray icon, autostart, push notifications** — out of MVP.
- **Manual cancel sync** — out of MVP per UI architecture spec.
- **"View log" link implementation detail** — banner má action label, ale konkrétní akce (open Notepad? new tab? console?) je v review nezodpovězená a ponechává se na backend implementation cyklus (viz "Open questions").

## Decisions extracted from prototype

### D1. Layout: full-width, vertical stack, max-w-6xl content

```
+-----------------------------------------------------+
| <Header> (sticky)                                   |
| Logo · [Dashboard] [Settings]    SyncStatusBadge    |
+-----------------------------------------------------+
| <BannerStack> (0+ banners)                          |
+-----------------------------------------------------+
|                                                     |
|   <SyncNowPanel>  (sync trigger + progress)         |
|                                                     |
|   <RecordingsList>  (empty | items)                 |
|                                                     |
+-----------------------------------------------------+
| <ToastContainer> (bottom-right, fixed)              |
| <ConnectionLostOverlay> (z-50 modal, when 3× retry) |
+-----------------------------------------------------+
```

`max-w-6xl mx-auto px-6` — content má fixed max width pro readability na wide monitors. Vertical gap `space-y-5` mezi panely.

### D2. SyncNowPanel — 6 visual states

| Server state | Visual |
|---|---|
| `sync.status="idle"` + `last_run_at` set | "Poslední běh <relative_time> · <exact_time>" + primary "Synchronizovat" button |
| `sync.status="idle"` + `last_run_at=null` | "Ještě nikdy neproběhla." + primary button |
| `sync.status="running"` + `progress.phase="listing"` | Disabled blue button "Synchronizace…" + indeterminate progress bar + "Načítám seznam nahrávek…" label |
| `sync.status="running"` + `progress.phase="downloading"` + counts | Disabled blue button "Synchronizace… 3 / 12" + determinate progress bar (% width) + "Stahuji 3 z 12" label |
| `sync.status="running"` + `progress.phase="categorizing"` | Same shape as downloading but label "Kategorizuji 8 z 12" |
| `sync.status="running"` + `progress.phase="finalizing"` | Same shape but label "Ukládám metadata…" + indeterminate bar (counts null) |

**"Started by Task Scheduler" hint:** subtle `<div>` pod progress bar s clock icon + text "Spuštěno Plánovačem úloh Windows" — zobrazený pouze pokud `sync.trigger="task_scheduler"`. UI/CLI sync trigger transparently merge into stejný running stav, hint je info-only.

### D3. RecordingsList row layout

```
[StatusIcon]  Title                                          [ProjectBadge]
              <folder-icon> plaud_folder  ·  relative_time
```

- **StatusIcon:** circular 5×5 (rounded-full), icon-only:
  - `downloaded` → ✓ green
  - `failed` → ✗ red
  - `skipped` → spinner-ish gray (looks like reload — semantic match for "skipped, will retry")
- **Title:** `text-sm text-gray-900 truncate font-medium` — single line, ellipsis, no wrap.
- **plaud_folder:** monospace (JetBrains Mono), gray, prefixed s folder icon. Truncate s tooltip "Plaud složka".
- **relative_time:** `relativeTime(downloaded_at, NOW)` — Czech localization (`právě teď`, `před 5 min`, `před 2 h`, `včera`, `před 3 dny`, fallback to `"23. dub"` short month + day).
- **ProjectBadge:** right-aligned, fixed width based on label.

### D4. ProjectBadge color taxonomy

- **`classification_status="unclassified"` || `project=null`:** gray badge "nezatříděno" (`bg-gray-100 text-gray-600`).
- **`classification_status="matched"` + project set:** stable hash-based color picker from `[blue, indigo, sky, violet]` palette. Hash function: `hash(project_name) % palette.length`. Same project always gets same color across renders.

**Open question (delta below):** prototype nepokrývá *_unmapped* case explicitly. Sync-core spec definuje path_resolver soft fallback `${unclassified_dir}/_unmapped_<project>/` když project je v title ale ne v config.projects. Současná logika UI by ho zobrazila s color-picked badge (stejně jako matched-in-config), což user nezavolá pozornost na chybějící config entry.

### D5. SyncStatusBadge — header right-aligned

5 states z prototype `SyncStatusBadge` komponenty:

| Server state | Dot color | Label |
|---|---|---|
| `sync.status="running"` | blue, pulsing | `phaseLabel(sync.progress)` (e.g., "Stahuji 3 z 12") |
| `last_run_outcome="failed"` | red, static | "Poslední synchronizace selhala" |
| `last_run_outcome="partial_failure"` | amber, static | "Poslední sync <relative_time> — částečný" |
| `last_run_outcome="success"` | green, static | "Poslední sync <relative_time>" |
| else (fresh / unknown) | gray, static | "Nečinný" |

### D6. BannerStack — persistent recoverable errors

Banner display rules (from prototype `setBannersFromState`):

- `last_run_outcome="failed"` → red banner "Poslední synchronizace selhala" + `last_error_summary` body + "Zobrazit log" action.
- `last_run_outcome="partial_failure"` → amber banner "Poslední synchronizace měla chyby" + summary + "Zobrazit log" action.
- (Settings-side) auth verify failure with `reason="PlaudTokenExpired"` → red banner "Token vypršel" + action "Otevřít Nastavení".

Dismissal:
- User klikne X → banner mizí v current session.
- `dismissedBanners: Set<string>` — banner dismissed se nezobrazí znovu **dokud server state se nezmění** (e.g., sync run completes, outcome changes).
- Banner s `last_run_outcome="failed"` zmizí automatically po next sync s `outcome="success"` (server state change → banner derivation re-runs).

### D7. Toast — transient success/error

Bottom-right, auto-dismiss 4s, click-to-dismiss. Slide-in animation `ps-toast-in` (fade + 8px translateY).

Triggered by:
- Sync transition `running` → `idle` + `outcome="success"` → "Synchronizace dokončena — N nových nahrávek"
- Settings auth verify success → "Token ověřen"
- Settings auth verify failure → "Ověření tokenu selhalo" (also banner)
- Settings config save success → "Konfigurace uložena"
- Settings config save 422 → "Konfigurace je neplatná — řádek N" (also inline error)

### D8. ConnectionLostOverlay — terminal error

Full-screen modal, z-50, dark backdrop with blur. Shown when:
- `useStateQuery` retries 3× exponential backoff (100/200/400 ms) and all fail.
- AppShell renders overlay; primary user action je zavřít okno (PyWebView shutdown). Dev-only "Skrýt" tlačítko v prototype (testing).

Body text: "Spojení s PlaudSync ztraceno. Místní sync služba neodpovídá. Zavři toto okno a otevři ho znovu." + monospace last error line (e.g., `ECONNREFUSED 127.0.0.1:8765`).

### D9. Live recordings during sync

Prototype mocked behavior: jak backend INSERT-uje nové `recordings` rows během sync, frontend polling (1.5s během running) je picknne v dalším ticku. UX: list **rozevírá se** na top — new rows jsou pre-pended. **Žádná animation** v prototype (žádný slide-down, žádný highlight) — jen new row appears v top position. Match s sync-core spec "live increment of recordings list".

### D10. Polling cadence

Per UI architecture spec:
- `sync.status="idle"` → 5000 ms poll (5s).
- `sync.status="running"` → 1500 ms poll (1.5s).

`refetchInterval` callback `(data) => data?.sync.status === "running" ? 1500 : 5000`. TanStack Query handles this idiomatically.

## Components

```
src/plaudsync/ui/static/  (after Vite build)
└── (mounted v FastAPI app.StaticFiles)

frontend/src/
├── App.tsx                              [QueryClientProvider + BrowserRouter]
├── main.tsx                             [bootstrap]
├── api/
│   ├── client.ts                        [fetch wrapper s retry]
│   ├── types.ts                         [TS mirror Pydantic models]
│   └── hooks.ts                         [useStateQuery, useStartSync, ...]
├── components/                          [shared, fixed contract]
│   ├── AppShell.tsx
│   ├── Header.tsx                       [Logo + tabs + SyncStatusBadge]
│   ├── SyncStatusBadge.tsx
│   ├── BannerStack.tsx
│   ├── Toast.tsx + ToastContainer.tsx
│   └── ConnectionLostOverlay.tsx
└── pages/
    └── Dashboard.tsx                    [<SyncNowPanel> + <RecordingsList>]
        ├── SyncNowPanel.tsx             [sync state + button + progress]
        ├── RecordingsList.tsx           [items list + empty state]
        ├── StatusIcon.tsx
        └── ProjectBadge.tsx
```

### Component LoC budget (proti UI architecture spec 500–1000 frontend LoC)

| Component | Estimated LoC |
|-----------|---------------|
| AppShell + Header + SyncStatusBadge | ~80 |
| BannerStack + Banner | ~60 |
| ToastContainer + Toast | ~40 |
| ConnectionLostOverlay | ~30 |
| Dashboard.tsx | ~30 |
| SyncNowPanel | ~80 |
| RecordingsList | ~70 |
| StatusIcon + ProjectBadge | ~40 |
| api/hooks.ts (Dashboard-relevant) | ~80 |
| api/types.ts (full StateResponse) | ~40 |
| api/client.ts (retry, error parsing) | ~60 |
| **Dashboard subtotal** | **~610** |
| **Settings subtotal (separate spec)** | ~200 |
| **Total frontend** | **~810** (within 500–1000 budget) |

### Public TS types (mirror Pydantic from UI architecture spec)

```ts
type SyncStatus = "idle" | "running";
type SyncTrigger = "task_scheduler" | "ui_sync_now" | "manual";
type SyncOutcome = "success" | "partial_failure" | "failed";
type SyncPhase = "listing" | "downloading" | "categorizing" | "finalizing";
type ClassificationStatus = "matched" | "unclassified";
type RecordingStatus = "downloaded" | "failed" | "skipped";

interface SyncProgress {
  phase: SyncPhase | null;
  processed_count: number | null;
  total_count: number | null;
}

interface SyncState {
  status: SyncStatus;
  trigger: SyncTrigger | null;
  started_at: string | null;
  last_run_at: string | null;
  last_run_outcome: SyncOutcome | null;
  last_run_exit_code: number | null;
  last_error_summary: string | null;
  progress: SyncProgress | null;
}

interface RecordingRow {
  plaud_id: string;
  title: string;
  created_at: string;
  downloaded_at: string;
  plaud_folder: string;          // UUID v0 (filetag_id), display name v1+
  classification_status: ClassificationStatus;
  project: string | null;
  target_dir: string;            // absolutní path, NOT zobrazený v Dashboard MVP
  status: RecordingStatus;
}

interface StateResponse {
  sync: SyncState;
  recordings: RecordingRow[];
}
```

### Public hooks (Dashboard-relevant subset)

```ts
function useStateQuery() {
  return useQuery({
    queryKey: ["state"],
    queryFn: fetchState,
    refetchInterval: (data) => data?.sync.status === "running" ? 1500 : 5000,
    keepPreviousData: true,
    retry: 3,
    retryDelay: (attempt) => 100 * 2 ** attempt,  // 100/200/400
  });
}

function useStartSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postStartSync,
    onError: (err) => {
      if (err.status === 409) {
        // Transparent: just invalidate state to pick up "running" stav
        qc.invalidateQueries({ queryKey: ["state"] });
      } else if (err.status === 500) {
        // Banner: spawn_failed
        // Pushed via global banner store (out of useStartSync scope)
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["state"] });
    },
  });
}
```

## Data flow

### Cold start

```
React mounts in WebView2:
  → BrowserRouter → / route → <Dashboard />
  → useStateQuery initial fetch
       ↓ retry 3× exp backoff if FastAPI not yet ready
  → on success: <Dashboard /> renders SyncNowPanel + RecordingsList
       (idle stav nebo prefilled if Task Scheduler ran recently)
```

### Sync Now click (happy path)

```
User clicks "Synchronizovat":
  → useStartSync.mutate()
       → POST /api/sync/start → 202 {sync_id, started_at}
  → invalidate ["state"] → useStateQuery refetches
  → server state: status="running", progress.phase="listing"
  → SyncNowPanel: button disabled "Synchronizace…" + indeterminate bar
  → SyncStatusBadge: blue pulsing dot + "Načítám seznam nahrávek…"
  → refetchInterval switches 5000 → 1500
  → každých 1.5s poll:
       progress.phase progresses listing → downloading → categorizing → finalizing
       recordings list pre-pends new rows as they land
  → final poll: status="idle", outcome="success"
  → refetchInterval back to 5000
  → frontend detects transition: pushToast("success", "Synchronizace dokončena — N nových nahrávek")
  → SyncStatusBadge: green dot + "Poslední sync právě teď"
```

### Sync Now click (concurrent lock with Task Scheduler)

```
Task Scheduler is mid-sync.
User clicks "Synchronizovat":
  → POST /api/sync/start
       → backend subprocess returncode=5 within 500ms
       → 409 {reason: "already_running", started_at, by: "task_scheduler"}
  → useStartSync.onError catches 409
       → invalidate ["state"] → poll picks running stav
       → no error toast, no banner — transparent
  → SyncNowPanel transition na running stav with isTaskScheduler=true
  → "Spuštěno Plánovačem úloh Windows" hint visible
```

### Auth verify failure during running sync

Out of Dashboard interaction scope — auth is Settings concern. Token expiry mid-sync surfaces as `last_run_outcome="failed"` + banner on next poll.

## Review delta (gaps vs prototype/specs)

### Gap 1: `_unmapped_<project>` not visually distinct

**Issue:** Prototype's `<ProjectBadge>` has only two variants — gray "nezatříděno" (unclassified) or hashed-color matched. Sync-core spec defines third path: `classification_status="matched"` + `project NOT in config.projects` → soft fallback `${unclassified_dir}/_unmapped_<project>/`. UI doesn't surface this — user adds new project to Plaud title without updating config, recording lands in `_unmapped_<project>/`, but Dashboard shows it identically to matched-in-config.

**Decision (recommend):** Add third badge variant — orange/amber `bg-amber-50 text-amber-700 border-amber-200`, label `_unmapped_<project>`. Backend signal: `target_dir.contains("_unmapped_")` OR add explicit `classification_route` field to `RecordingRow` with values `"matched_in_config" | "matched_not_in_config" | "unclassified"`. Recommended: extend `RecordingRow` with `classification_route` field (FastAPI deriving it from `target_dir` path heuristic before sending — sync-core writes it directly post-impl).

**Implementation note:** ne přidávat to teď — tracked v open questions.

### Gap 2: `plaud_folder` is UUID in v0, prototype mock shows readable strings

**Issue:** Prototype mock data has `plaud_folder: "Meetings/ProjektAlfa"`, `"Klienti/Beta"`, `"Inbox"` — readable folder names. Sync-core spec confirms Plaud API returns `filetag_id` UUID, NOT folder name (display name endpoint is undiscovered). Real production data will have `plaud_folder: "abc-12345-uuid"` strings. UI list will show those UUIDs as "folder name" line, which is opaque to user.

**Decision (recommend):** Accept UUID display in v0 with explicit user expectation set. Document in README setup section: "Plaud folder names appear as UUIDs — display name resolution is v1.1+ feature". Tooltip on the folder icon: "Plaud složka (ID)".

**Alternative:** Truncate/mask UUID to first 8 chars `abc-1234…` to reduce visual noise. Implementation: helper `truncateFolderId(plaud_folder)`.

### Gap 3: target_dir not displayed

**Issue:** `RecordingRow.target_dir` (absolute path on local FS, e.g., `C:\Projects\Alpha\Recordings`) is in StateResponse but Dashboard doesn't render it. User has no in-UI way to see "where on disk did this go".

**Decision (extracted from prototype):** Skip target_dir display in MVP. Reasons: (a) absolute paths bloat row height, (b) ProjectBadge already implies routing via stable color, (c) v1.1 detail view (click row) is natural location. Tooltip on ProjectBadge could show target_dir — minimal incremental addition. Recommendation: add as Phase 2 polish (after first user feedback from real syncs).

### Gap 4: "Zobrazit log" action behavior undefined

**Issue:** Banner has action label "Zobrazit log" but prototype just dismisses banner on click. Real implementation must do something. Options:

- **A)** Open `plaudsync.log` v default `.log` editor (Windows: Notepad). Cross-platform fragile.
- **B)** New tab with `GET /api/log/tail?lines=200` rendered as monospace `<pre>`. Requires backend endpoint not in UI architecture umbrella.
- **C)** Console output (dev only) + show toast "Logs in plaudsync.log".
- **D)** Modal with `<pre>` of last N log lines fetched from new backend endpoint.

**Decision:** Defer to UI backend writing-plans cycle. Recommend **C for MVP** (toast points user to log file path; user opens manually). **B/D for v1.1** if user feedback shows confusion.

### Gap 5: Loading state during cold start

**Issue:** Prototype assumes `useStateQuery` returns data immediately or shows ConnectionLostOverlay after 3× retry. No "loading…" intermediate state. UX: WebView2 paints React shell, Dashboard route renders, but `useStateQuery` is fetching for 100-400ms — user sees empty layout.

**Decision (recommend):** Add `<DashboardSkeleton>` rendered during `useStateQuery.isLoading && !data`. Skeleton: SyncNowPanel without content + recordings list with 3 placeholder rows (gray rectangles). Tailwind `animate-pulse` utility.

**Acceptable alternative:** show centered spinner + "Načítám…". Simpler, matches prototype empty state aesthetic.

### Gap 6: Live recordings list — no animation for new rows

**Issue:** Prototype pre-pends new rows during sync without visual cue. User watching list during running sync may not notice items appearing (unless watching closely).

**Decision:** Phase 2 polish. MVP without animation is acceptable per prototype. If user feedback shows missed new rows, add CSS keyframe `slide-in-from-top` on `<li>` mount.

### Gap 7: Banner persistence across sessions

**Issue:** `dismissedBanners: Set<string>` is in-memory React state — lost on window close. If user dismissses "last sync failed" banner, closes window, opens again, same `last_run_outcome="failed"` state → banner reappears. Acceptable or annoying?

**Decision (recommend):** Acceptable for v0. Rationale: dismissed banners shouldn't be silently forgotten across sessions — a persistent failure deserves re-surfacing. If user feedback complains, add localStorage-backed `dismissedBanners` keyed by `(banner_id, last_run_at)` so dismissal lasts until next sync transition.

## Open questions (for implementation cycle)

1. **`classification_route` field in `RecordingRow`** — add explicitly, or derive from `target_dir` heuristic? (Backend sync-core impl decision.)
2. **"Zobrazit log" action** — A/B/C/D from Gap 4. Default: C (toast pointing to file path).
3. **Loading skeleton vs spinner** — pick one; defer to first frontend impl PR.
4. **UUID truncation in `plaud_folder` display** — accept full UUID or truncate to 8 chars + ellipsis?

These are implementation-cycle questions, not blockers for spec approval.

## Acceptance criteria

Dashboard implementation je hotová pokud:

1. **Visual parity with prototype** — `frontend/PlaudSync UI.html` rendered side-by-side with built React app shows pixel-equivalent UI for all 6 SyncNowPanel states + RecordingsList rendering + empty state + ConnectionLostOverlay.
2. **All scenarios from prototype scenario picker reproducible** — manual smoke test toggles backend mock to feed each `StateResponse` shape; UI matches expected visual.
3. **Sync Now click → 202 → progress visible within 1500 ms** (one polling tick).
4. **Concurrent click while running** — button disabled, no double-mutation; if backend returns 409 mid-flow, transparent transition.
5. **Live row pre-pending** — during 5-recording mock sync, all 5 rows appear in list before sync completes (no batch landing at end).
6. **Toast on success transition** — exactly one toast per sync completion, not duplicate.
7. **Banner derivation from `last_run_outcome`** — failed → red, partial → amber, success → no banner. Dismissal works in-session.
8. **ConnectionLostOverlay** — manually kill backend during running sync, overlay appears within ~700 ms (3× retry × ~200 ms avg).
9. **TanStack Query polling adapts** — DevTools network tab shows 5s ticks idle, 1.5s ticks during running.
10. **Czech localization** — all strings match prototype (no English fallthrough).
11. **Frontend bundle ≤ 500 KB gzipped** — UI architecture umbrella W-U2 watch.
12. **Accessibility minimum** — keyboard nav: Tab cycles Dashboard → Settings → Sync button → recording rows. Focus rings visible (prototype has `focus-visible` outline). aria-labels on dismiss buttons (prototype has these).
13. **No console errors** in production build (test with `npm run build && npm run preview`).

## Implementation plan

→ `writing-plans` skill (next step **after**: sync-core impl on master + Settings spec).

Pořadí navazujících kroků:

1. **Tento spec** schválen userem (autonomní review, pokud OK, jinak revise).
2. **Sync-core implementation** dokončena (paralelně, jiná session).
3. **Settings spec** napsán (analogický review process — Settings part of same prototype).
4. **UI backend writing-plans** cyklus (FastAPI app.py + state_reader + config_io + sync_starter + runner; consumes both Dashboard a Settings specs).
5. **Frontend writing-plans** cyklus (React + TS + Tailwind + Vite; transcribes prototype HTML do `frontend/src/` Vite project; consumes Dashboard + Settings specs).
6. **Implementation execution** přes superpowers:subagent-driven-development.

## Revision history

- **2026-04-25 (v0):** Extracted z `frontend/PlaudSync UI.html` Claude Design prototype. Review delta proti UI architecture umbrella v0.2 + sync-core v0.2. 7 gaps identified, 4 deferred to implementation cycle, 3 with documented decisions.
