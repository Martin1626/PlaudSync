# PlaudSync — Dev Log

Ruční journal pro tracking kill criteria a non-obvious rozhodnutí. Přidávej odshora (nejnovější nahoru). Formát: `## YYYY-MM-DD — short title` + body.

---

## 2026-04-26 — Classifier wire-up + 14d rolling re-classify

**Symptom:** 2 recordings staženy 2026-04-26 (`04-26 Alza: test1`, `2026-04-26 FHB: test2`) skončily v `Unclassified/_unknown/` přesto, že title formát match-uje regex a project klíče v `config.yaml` (`ALZA`, `FHB`) by byly rozpoznatelné case-insensitive.

**Layer (per `sync-debug` skill):** Layer 4 — categorization. Layers 1-3 byly clean.

**Root cause:** `__main__.py:141` injectoval `DefaultBucketClassifier()` (placeholder vracející `_unclassified` vždy), ne reálný `categorization.classify()`. Sekundárně: `path_resolver` indexoval `config.projects[project]` literálně, takže i po wire-up by `project='Alza'` vs. `config_key='ALZA'` skončilo v `_unmapped_Alza/`.

**Fix:**
1. `CategorizationClassifier` adapter v `classifier.py` zabaluje `categorization.classify()` do `Classifier` Protocol shape.
2. `Config.lookup_project(name)` provádí casefold-based lookup; `path_resolver` přechází na metodu; `load_config` odmítá duplicit casefold klíče.
3. `_reclassify_recent()` pass v `run_sync()` před hlavní download loop — re-klasifikuje rows s `classifier_label='_unclassified'` a `downloaded_at >= now-14d`, fyzicky přesouvá soubory + updatuje DB. Edge cases: missing source / target collision → warning + skip; IO error → Sentry capture + failed_count++.

**Spec:** [docs/superpowers/specs/2026-04-26-classifier-wireup-design.md](docs/superpowers/specs/2026-04-26-classifier-wireup-design.md).
**Plan:** [docs/superpowers/plans/2026-04-26-classifier-wireup.md](docs/superpowers/plans/2026-04-26-classifier-wireup.md).

**Kill criteria check:**
- `#5` (regex coverage <90 %): teprve s tímto fixem se začne reálně měřit. 30-day window monitoring stále není implementovaný — watch item.
- `#18` (Sentry scrubbing): re-classify pass přidává `recording_id` tag, použité scrubbing rules ho pokryjí (existující pattern, žádný nový exposure).

**Follow-ups (z code review, plan-suboptimal stick s plánem během execution):**
- `load_config` guard against non-string YAML project keys (Task 2 review I-1).
- `path_resolver` module docstring add case-insensitive note (Task 3 review M1).
- Drop `replace("Z", "+00:00")` across 5 sites — Python 3.11 `fromisoformat` handles Z natively (Task 4 review M1).
- Drop unused `run_id` param in `_reclassify_recent` + add `logger.info` reclassify summary (Task 6 review I-1, I-2).
- `SimpleNamespace` instead of `class _MetaLike: pass` inline (Task 6 review M-1).
- Explicit Sentry-tag assertion test for `reclassify_failed` error_kind (Task 7 review M2).
- Extract `_make_reclassify_env` fixture when test file > 6 tests (Task 7 review M3).

**Verifikace dnešních 2 souborů:** automaticky se přesunou při příštím `python -m plaudsync` běhu (Task Scheduler tick nebo manual). Task 9 plánu provede manuální production run.

---

## 2026-04-26 — v0 production-ready: Schedule + Phase 2 smoke + security review + Task Scheduler installer

Single-session batch wrapping v0 to shippable. 4 commits to origin/main.

### Schedule feature merged

`feat(schedule): work-hours/off-hours sync gating + UI endpoint` (`aa8d4dc`):
- `src/plaudsync/schedule.py` (270 LoC) + 26 tests (`test_schedule.py` 22 + `test_ui_schedule_endpoint.py` 4) — all green.
- `__main__.py` schedule gating block, exit 5 on skip (same as SyncLockHeld for benign alerting).
- `ui/app.py` GET/PUT `/api/schedule` endpoints with 422 validation.

`feat(ui/settings): Schedule panel + YAML syntax highlight` (`317e58d`):
- SchedulePanel.tsx (271 LoC) + yamlHighlight.ts (136 LoC; Settings spec Gap 5 deferred → shipped).
- YamlEditor overlay rendering with `escapeHtml` first (XSS-safe `dangerouslySetInnerHTML`).

### Code review (subagent) — 3 must-fix applied pre-commit

- **C1:** dropped dead `try/except sqlite3.OperationalError` in `__main__` (open_state has CREATE IF NOT EXISTS).
- **I1:** removed unused `timezone` import.
- **I2:** `save_schedule` now atomic via `os.replace` — prevents UI/CLI race producing torn JSON read.
- **Test mock parity:** `_setup_sync_pipeline_mocks` now bootstraps `_SCHEMA` in `:memory:` connection (regression fixed).

After fixes: 155/155 tests green, bandit 0 H / 0 M / 3 L (subprocess intentional).

### Phase 2 backend smoke PASS

`python -m plaudsync ui --dev` against tmp `PLAUDSYNC_STATE_ROOT`:

| Endpoint | Status | Verified |
|---|---|---|
| `/api/healthz` | 200 | `{"status":"ok"}` |
| `/api/state` | 200 | sync=idle, recordings=[] |
| `/api/config` | 200 | UI-seeded DEFAULT_YAML (lifespan auto-seed works) |
| `/api/schedule` | 200 | defaults: 15min work / 60min off, Mon-Fri 8-16 |

Lifespan handler auto-created `config.yaml`, `.plaudsync/state.db` (+ WAL + shm).

### `/security-review` — clean

`superpowers:code-reviewer` reviewed all 3 commits. **No HIGH-CONFIDENCE findings.** Verified: dangerouslySetInnerHTML is XSS-safe (escapeHtml + closed Cls union + CSP defense), `/api/schedule` PUT validates Pydantic shape + range, `save_schedule` writes fixed path, `load_schedule` uses `json.loads` (safe), schedule gating bypass only for `task_scheduler` trigger.

### Production go-live artifacts

`docs(production): Task Scheduler installer + README setup quickstart` (`ed089fc`):
- `scripts/install-task-scheduler.ps1` — PowerShell helper, idempotent, per-user Limited token, 15-min ticks.
- `README.md` — quickstart, Plaud token recipe, Task Scheduler one-liner, data flow diagram, ops triage table.

### Pending user actions for full go-live

1. `.\scripts\install-task-scheduler.ps1` (per-user, no admin).
2. Wait 15 min OR `Start-ScheduledTask -TaskName "PlaudSync"`. Verify `<STATE_ROOT>\plaudsync.log` + Sentry.
3. Tune Schedule via UI Settings if 15-min default needs adjusting.

### Status

**v0 shippable end-to-end.** Auth + sync core + categorization + UI backend + frontend + schedule gating live on `main`. 155 tests green, bandit clean, Sentry scrubbing verified, CSP locked, no security findings.

**v1.1 backlog:** Dashboard `_unmapped_<project>` badge variant, log viewer modal, Plaud `filetag_id` UUID → display name resolution, click-row drill-down detail.

---

## 2026-04-25 — UI frontend Phase 1 smoke (mock data) PASS

Branch `feat/ui-frontend` complete: 15 plan tasks + 4 follow-up fix
commits = 19 commits total. ~25 TSX modules transcribing prototype
`frontend/_prototype/PlaudSync UI.html` (validated Claude Design
prototype) into Vite + React 19 + TS strict + Tailwind 4 project at
`frontend/`. Worktree-isolated impl path: `c:/tmp/PlaudSync-ui-frontend`.

### Phase 1 verification matrix (mock-data only, no live backend)

All 12 automated checks passed:

| Check | Result |
|---|---|
| `npm run typecheck` (TS strict, all flags) | exit 0 |
| `npm run build` end-to-end | clean |
| Bundle gzip size | **94.9 KB** (budget 200 KB; W-U2 threshold 500 KB) |
| `src/plaudsync/ui/static/` populated post-build | yes |
| Static dir gitignored (clean working tree post-build) | yes |
| No inline `<script>` in production index.html (CSP) | clean |
| Privacy grep — no business labels in toast/banner strings | PASS |
| `npm run dev` startup | VITE ready in ~300 ms |
| Dev mock layer tree-shaken from production bundle | confirmed |
| Czech localization spot-check (D10 lock) | 12 matches |
| Component file count (components/9, Dashboard/5, Settings/5, dev/3) | match |
| Commit count on branch | 19 |

### Bundle composition (gzipped)

- `assets/index-HASH.js` (app code) — 62.6 KB
- `assets/react-HASH.js` (React + ReactDOM + react-router-dom chunk) — 15.0 KB
- `assets/query-HASH.js` (TanStack Query chunk) — 10.0 KB
- `assets/index-HASH.css` (Tailwind 4 generated) — 7.0 KB
- `index.html` — 0.3 KB

### Deviations from plan resolved during execution

- **Task 1 fix:** `vite.config.ts` `__dirname` → `fileURLToPath(new URL("./src", import.meta.url))` (ESM-idiomatic; the original CJS-style worked only via Vite's internal esbuild shim).
- **Task 2 fix #1:** focus-visible block moved from unlayered into `@layer base` (lets Tailwind `ring-*` utilities override where needed).
- **Task 2 fix #2:** Tailwind 4.0.0 `@tailwindcss/postcss` had an oxide-rust scanner crash (`Missing field 'negated' on ScannerOptions.sources`); bumped tailwindcss + @tailwindcss/postcss to 4.0.17 AND migrated keyframes from `tailwind.config.ts` to CSS-native `@theme` block in `index.css`. Also moved `@plugin "@tailwindcss/forms"` registration into CSS. `tailwind.config.ts` reduced to a stub kept for IDE tooling.
- **Task 1/14:** package.json forced bumps (Vite 7 peer deps): `@vitejs/plugin-react` 4.3.4 → 5.2.0, `@types/node` 22.10.2 → 22.12.0.
- **Task 13:** added `frontend/src/vite-env.d.ts` (`/// <reference types="vite/client" />`) so tsc strict knows about `import.meta.env`. Standard Vite reference fix.
- **Task 6 chore:** appended `*.tsbuildinfo`, `vite.config.d.ts`, `vite.config.js` to `frontend/.gitignore` (tsc -b composite outputs).

### Phase 1 ACs covered

Dashboard ACs (mock-data testable): 1, 2, 7, 8, 10, 12, 13.
Settings ACs (mock-data testable): 1, 5, 14, 15, 16, 17, 18, 19, 20.

### Phase 2 ACs deferred (need live backend)

Dashboard: 3, 4, 5, 6, 9, 11.
Settings: 2, 3, 4, 5 (live verify), 6, 7, 8, 9, 10, 11, 12, 13.

### Next step

Phase 2 smoke schedule: after `feat/ui-backend` merges to master, spin
up `python -m plaudsync ui` + `cd frontend && npm run dev` with
`PLAUDSYNC_DEV_PORT=8765`, walk through deferred ACs, append Phase 2
DEV_LOG entry. **Manual `/security-review` recommended before merging
`feat/ui-frontend` to main** (CLAUDE.md "before merging to main" gate).

### Open follow-ups (not blockers, captured pre-v1.1)

- Dashboard Gap 1: `_unmapped_<project>` badge variant — needs backend
  `RecordingRow.classification_route` field (sync-core spec follow-up).
- Dashboard Gap 4: log viewer modal vs current toast-points-to-log —
  deferred to v1.1+.
- Settings Gap 5: YAML syntax highlight — deferred per spec.
- Task 4 client.ts: `{ raw: text }` fallback for non-JSON bodies could
  collide with a real `raw` JSON key; consider boxing differently in v1.1.
- Task 4 client.ts: `AbortSignal` plumbing not yet done (TanStack v5
  passes `signal` to queryFn — currently dropped). Defer to v1.1+.

---

## 2026-04-25 — UI backend implementation done + smoke test PASS

Implementation execution of `docs/superpowers/plans/2026-04-25-ui-backend.md`
via subagent-driven-development on branch `feat/ui-backend`. 28 commits
landed across 19 tasks.

**What landed:**

- 6 new modules under `src/plaudsync/ui/` (~580 LoC src + ~520 LoC tests):
  `__init__.py`, `config_io.py` (DEFAULT_YAML + read/save/seed), `state_reader.py`
  (snapshot + running queries), `sync_starter.py` (subprocess + 500ms wait),
  `app.py` (FastAPI + 6 endpoints + Pydantic models + CSP + StaticFiles),
  `runner.py` (uvicorn + PyWebView + browser fallback).
- `auth.mask_token()` helper (first_8 + 15 dots + last_4).
- `__main__.py` `ui` subcommand with `--dev` flag wiring.
- `pyproject.toml` deps: `fastapi>=0.115`, `uvicorn[standard]>=0.30`,
  `pywebview>=5.3`. Resolved to fastapi 0.136.1 / uvicorn 0.46.0 /
  pywebview 6.2.1.
- `.env.example` documents `PLAUDSYNC_UI_DEBUG` + `PLAUDSYNC_DEV_PORT`.
- `.gitignore` entry for `src/plaudsync/ui/static/` (Vite build output).

**Test results:** 128/128 pass (37 new UI tests across `test_ui_app.py`,
`test_ui_config_io.py`, `test_ui_state_reader.py`, `test_ui_sync_starter.py`,
`test_ui_runner.py`, `test_ui_auth_mask.py`, `test_main_ui_subcommand.py`;
+ 91 pre-existing). Bandit `-r src/plaudsync/ui/ -ll`: zero high/medium
issues, 2 expected low (subprocess.Popen with explicit list args, no shell=True).

**Smoke test (manual, in-process uvicorn):**

| Step | Result |
|---|---|
| `create_app(c:/tmp/plaudsync-smoke)` cold start | uvicorn ready in <500 ms on OS-assigned port |
| Lifespan auto-seed | `c:/tmp/plaudsync-smoke/config.yaml` written; `${STATE_ROOT}` substituted to actual path; YAML parses |
| `GET /api/healthz` | 200 + `{"status":"ok"}` + CSP header (`default-src 'self'`...) |
| `GET /api/state` | 200, `sync.status=idle`, `recordings=[]` |
| `GET /api/config` | 200, `parsed.projects` keys = `[ProjektAlfa, KlientBeta, Interní]`, `parse_error=null` |
| `PUT /api/config` (invalid path) | 422 with detail (JSON-shape errors visible in body) |
| Server shutdown via `should_exit=True` | clean exit, no zombie process |

**Implementation deviations (documented for review):**

- **CSP middleware mounted middle-of-handler-list, StaticFiles last.**
  Initially placed StaticFiles before /api/sync/start endpoint; moved
  to right before `return app` to avoid catch-all `/` mount intercepting
  /api/* routes.
- **`_open_ui_state` UI-local SQLite helper** added in `app.py` instead
  of reusing sync-core's `open_state` directly. Reason: FastAPI sync
  handlers run in a worker thread pool while lifespan runs in the
  asyncio thread; one connection has to be reusable across both, which
  requires `check_same_thread=False`. WAL mode + idempotent schema
  bootstrap preserved.
- **`block_network` marker** added at module level on `tests/test_ui_app.py`
  and `tests/test_ui_runner.py` (`allowed_hosts=["127.0.0.1", "localhost"]`)
  because TestClient and asyncio.run create localhost socketpairs that
  pytest-recording's `--block-network` gate otherwise intercepts. Marker
  syntax is `block_network(allowed_hosts=...)`, NOT `allow_hosts(...)`
  (corrected mid-implementation after first attempt failed).
- **`maybe_seed_default` is no-op even on empty file** (`target.exists()`
  is True for blank files). Test expectation matches: user content
  protection trumps re-seeding. Documented in module docstring.

**CD1-CD5 from plan all upheld:** auto-seed in lifespan only, no crash
on broken config (lazy validation), masked_token only on AuthVerifyResponse,
polling-only progress, single read-only conn in `app.state.db`.

**Open follow-ups (not blockers):**

- Sentry "2 pending events" stderr message after pytest run — likely
  `_configure_sentry()` capturing test artifacts. Not affecting tests;
  investigate during next observability sweep.
- `RecordingRow.plaud_folder` always `"_unknown"` in v0 (Dashboard spec
  Gap 2 acknowledged). v1 brainstorm to surface real folder names via
  separate `/folder/list/web` endpoint.
- `RecordingRow.classification_route` field for `_unmapped_<project>`
  badge variant (Dashboard spec Gap 1) — sync-core schema follow-up.

**Branch state:** `feat/ui-backend` ready for `/security-review` (new
HTTP surface + subprocess spawn + CSP middleware) before merge to main.
Frontend writing-plans cycle is the next blocker for full UI ship —
StaticFiles mount in `app.py` is conditional on `src/plaudsync/ui/static/index.html`
existence, which the frontend plan's Vite build pipeline produces.

---

## 2026-04-25 — UI frontend implementation plan written

`docs/superpowers/plans/2026-04-25-ui-frontend.md` published. 15 tasks
transcribing the validated Claude Design prototype (`frontend/PlaudSync UI.html`,
1222 LoC, 5 scenarios) into a Vite + React 19 + TS strict + Tailwind 4
project at `frontend/`. Production build copies dist to gitignored
`src/plaudsync/ui/static/` (umbrella E1/E3) for FastAPI StaticFiles mount.

### Key transcription decisions

- **No global store library** (umbrella D2): app-level toasts + banners
  via two minimal React Contexts (`ToastsProvider`, `BannersProvider`).
  Per-component dismiss state stays local with `useState`.
- **No test framework** in MVP (umbrella E6): verification = TS strict +
  manual smoke split into Phase 1 (mock-data, this branch) and Phase 2
  (live backend, after `feat/ui-backend` lands on master).
- **Dev mock layer gated by `import.meta.env.DEV`**: `dev/MockProvider`
  seeds TanStack Query cache with prototype `SCENARIOS` so the entire
  Dashboard + Settings flow is exercisable without a backend.
  `staleTime: Infinity` in dev keeps mock fresh; production tree-shakes
  the entire `dev/` directory via Vite dead-code elimination.
- **CSP-friendly bundle** (umbrella E5): `modulePreload.polyfill: false`
  in vite.config.ts removes the inline preload script; JetBrains Mono
  self-hosted via `@fontsource` so `connect-src 'self'` stays strict.
- **Bundle target ≤ 200 KB gzipped** (umbrella AC #4): `check-bundle-
  size.mjs` postbuild script warns over budget; W-U2 hard threshold 500
  KB. Realistic estimate: ~130 KB (React+ReactDOM 45 KB, query 14 KB,
  router 12 KB, app code ~50 KB).

### Settings spec v0.1 review fixes incorporated

- Gap 1 multi-error: `InlineConfigErrors.tsx` first-inline + `(+N
  dalších)` `<details>` expansion + click-to-promote.
- Gap 2 Option A: `AuthVerifyResponse.masked_token` (server-rendered
  first_8+15dots+last_4); ConnectionPanel implicit-verify on mount.
- Gap 3: `ConfigResponse.parse_error` surfaces inline + toast on mount.
- Gap 4: dirty-Reload triggers `window.confirm("Zahodit neuložené
  změny?")`.
- Gap 9: textarea `Tab → 2 spaces`, `Shift+Tab → dedent`, `Esc → blur`,
  hint footer "Tab pro odsazení • Esc pro opuštění editoru".

### Open follow-ups (post-merge, not blockers)

- Dashboard Gap 1 — `_unmapped_<project>` badge variant blocked on
  backend `RecordingRow.classification_route` field (sync-core spec
  follow-up; not added to current plan).
- Dashboard Gap 4 — log viewer modal: deferred to v1.1+. MVP behavior
  is a toast pointing user to `plaudsync.log` in project dir.
- Settings Gap 5 — YAML syntax highlight: deferred per spec.

Phase 2 smoke (live-backend ACs) gated on `feat/ui-backend` merge.

---

## 2026-04-25 — UI backend implementation plan written

`docs/superpowers/plans/2026-04-25-ui-backend.md` published. 19 TDD
tasks covering 6 new modules under `src/plaudsync/ui/` (`config_io.py`,
`state_reader.py`, `sync_starter.py`, `app.py`, `runner.py`, package
init) + `auth.mask_token()` helper + `__main__.py` `ui` subcommand with
`--dev` flag + 3 runtime deps (`fastapi`, `uvicorn`, `pywebview`).

### Key cross-spec decisions documented in plan

Plan resolves five overlaps/ambiguities between umbrella v0.2, Dashboard
v0, and Settings v0.1 specs (locked as CD1–CD5 in plan):

- **CD1:** DEFAULT_YAML auto-seed lives in UI lifespan (NOT sync-core
  CLI). Sync-core behavior unchanged (missing config = exit 7). UI
  substitutes `${STATE_ROOT}` literal to actual env-var path **at write
  time** so the seeded file passes sync-core absolute-path validation.
  This avoids needing to extend `config.load_config` with substitution
  logic — Settings spec D8 substitution rule is satisfied transparently
  for the seed path; future user-edited configs use real paths only.
- **CD2:** Lifespan does NOT crash on broken existing config — resolves
  overlap between umbrella spec ("fail-fast crash → ConnectionLostOverlay")
  and Settings spec Gap 3 ("GET /api/config returns broken YAML +
  parse_error so frontend shows inline error on mount"). Lifespan only
  validates STATE_ROOT presence + auto-seeds missing config. Validation
  is lazy in GET/PUT handlers; sync subprocess exit 7 surfaces as 500
  spawn_failed banner.
- **CD3:** `masked_token` lives only on `AuthVerifyResponse` (Settings
  spec Gap 2 Option A). `ConfigResponse` does NOT carry it. Backend
  computes mask via `auth.mask_token(token)` = first_8 + "•"×15 + last_4
  (≥ 12-char tokens) or "•"×20 fallback. `null` only on
  `PlaudTokenMissing`; populated even on `PlaudTokenExpired` since token
  shape is known.
- **CD4:** Polling-only progress (no SSE) — re-confirms umbrella B3.
- **CD5:** Single SQLite read-only conn lives in `app.state.db` over
  lifespan; WAL mode lets sync subprocess write concurrently.

### Frontend handoff

Frontend Vite project (React + TS + Tailwind + TanStack Query under
`frontend/`) is **out of scope** of this plan. Once UI backend lands on
master, separate writing-plans cycle produces frontend plan consuming
Dashboard + Settings screen specs. `StaticFiles` mount in `app.py`
(Task 15) is conditional on `src/plaudsync/ui/static/index.html`
existence — frontend plan owns the Vite build output drop into that
path. Pydantic models on `app.py` (`StateResponse`, `RecordingRow`,
`ConfigResponse`, `AuthVerifyResponse`, etc.) are the canonical wire
contract that frontend TS types must mirror.

### Branch + execution

Plan default execution: `superpowers:subagent-driven-development` (same
pattern that succeeded for sync-core plan). Branch: `feat/ui-backend`
from master. Each task = one fresh subagent + two-stage review.
Architecturally significant change (new HTTP surface + subprocess spawn
+ CSP) — `/security-review` mandatory before merge.

### Process notes

Independent self-review during plan writing surfaced one cross-spec
contradiction (CD2: umbrella "fail-fast crash" vs Settings "show inline
error"). Resolution favors the newer Settings spec because the umbrella
predates Settings v0.1 review fixes. This is the second consecutive
plan-writing session where independent review caught a real
contradiction (Settings spec v0 review caught Gap 2 C→A flip). Pattern
worth tracking: cross-spec ambiguities tend to surface only when a
third actor (plan, code, third spec) tries to consume both. Formalize
"cross-spec consistency check" as a writing-specs / writing-plans gate
when ≥ 2 specs share a contract surface.

---

## 2026-04-25 — Sync core smoke test PASS, branch merged + deleted

Manuální smoke proti reálné Plaud Cloud po merge `feat/sync-core` →
`master` (`9a6b6a5`):

| Krok | Výsledek |
|---|---|
| `python -m plaudsync verify` | exit 0, region probe + token OK (~3s) |
| 1. sync (~5 min) | exit 0, 92 nahrávek staženo |
| state.db | `sync_runs(1, exit=0, new=92, skipped=0, failed=0, manual)`; 92× status='downloaded' |
| 2. sync (idempotence) | exit 0, `new=0, skipped=0, failed=0` — since filter zastavil iterátor na page 1 |
| log audit | 4 INFO řádky, 0 výskytů `title`/`file_name`/`temp_url`/`Bearer` |

**Pozorování:**

- `plaud_folder` fallback fungoval — všech 92 nahrávek v `Unclassified/_unknown/`
  protože `from_raw` nedostal `filetag_id` ani `tag_ids[0]` z reálné API
  (DefaultBucketClassifier → unclassified branch). Future v1 brainstorm: rozhodnout
  jestli zůstat u `_unknown` nebo dotahovat tag display name přes endpoint
  `/folder/list/web`.
- České diakritiky v filename zachované (`_slugify` `[^\w\-]+` s `re.UNICODE`):
  `Schůzka_FHB_Příprava_…`, `Marek_Bartoš_Socio-etické_chování_LLM_…`.
- Pagination + since filter: druhý běh 0 API calls na listing po prvním page
  (since marker zastavil iterátor) — efektivní pro 1h Task Scheduler cadence.
- Throughput: 5 min / 92 nahrávek ≈ 3 sec/recording vč. temp-url + S3 stream.
  Single-threaded, bezpečné pro Task Scheduler interval ≥ 1h.

**State po smoke:** `feat/sync-core` lokální branch smazán (`git branch -d`).
Repo state: master HEAD `9a6b6a5` (merge commit), `C:/PlaudSync/` obsahuje
state.db + 92 .mp3 + plaudsync.log. Kill criteria L-1..L-18 nezapálené.

Další logický krok: Task Scheduler hookup — vytvořit periodic job pro
`python -m plaudsync` každou hodinu. Mimo sync-core scope.

---

## 2026-04-25 — Sync core code review: 3 hardening fixes + 2 deviation notes

Independent code-reviewer agent run proti `feat/sync-core` (HEAD `a8ab7d2`)
vrátil APPROVED_WITH_FIXES. Aplikováno v commitu `abf4a57`:

**Hardening (Important):**
- I-1: `_region_probe` allowlist `https://*.plaud.ai` — bez guardu by attacker
  schopný falšovat API odpověď přesměroval `_base_url` na vlastní host a token
  by tekl na další request.
- I-2: `download_audio` vynucuje `https://` na presigned URL + `allow_redirects=False`
  na S3 leg. Legitimní S3 presigned URL nikdy nepotřebují redirect.
- I-3: `_process_recording` unlinkuje partial file na jakoukoli mid-stream
  exception (předtím jen na size mismatch). Bránění UI/file watcheru zobrazit
  half-recording s real-looking name.

**Documented deviations (no fix):**
- I-9: `__main__.py:94-96` přidal `FileNotFoundError → exit 7` handler nad rámec
  spec. Důvod: `load_config` raisí FileNotFoundError když chybí config.yaml,
  ne ConfigValidationError. Beneficial deviation — uživatel dostane stejný
  exit 7 místo opaque exit 1. Ponechano.
- M-8: `sync.py:62-66` Sentry `recording_failed` capture vynechal
  `set_context("sync_run", {"run_id": ..., "trigger": ...})` per spec line 506-507.
  Trigger není v `run_sync` scope u failure pointu — vyžadovalo by threading.
  Defer do follow-up; má-li triage nedostatečnou kontext info, doplnit pak.

Cassette M-6: `test_sync_happy_path_*` body měl unscrubbed title
`"04-25 Test: meeting"` — přepsáno na `"<redacted-title>"`.

Branch po fixech: 79/79 testů zelených (5 nových testů pro hardening).

---

## 2026-04-25 — Sync core implementation plan written

`docs/superpowers/plans/2026-04-25-sync-core.md` published. 16 TDD
tasks covering 8 new modules + 4 modifications. Endpoint discovery
(5 community Plaud clients reverse-engineered) embedded as appendix
in spec.

Key decisions confirmed by discovery:
- `since` filter is **client-side** (Plaud has no server-side `since`);
  iterator stops early on first older record (desc by start_time).
- `plaud_folder` is a **UUID** (`filetag_id` / `tag_ids[0]`), not a
  display name. v0 ships UUIDs; v1 brainstorm resolves UUID → name.
- Audio download: temp-url JSON → S3 presigned URL (no auth header on
  S3). Two-step pattern.

Branch: `feat/sync-core` (created from master at start of Task 1).

---

## 2026-04-25 — Settings spec v0 → v0.1: review fixes applied

Independent code-reviewer agent run proti `2026-04-25-settings-screen-design.md` v0 (commit 340913a) vrátil 5 must-fix items + 8 minor nits. Vše opraveno v jednom revisi commitu.

**Must-fix:**

1. **Gap 2 flipped C → A.** v0 doporučovala "frontend constant 20 dots" (Option C), což je regression proti UI architecture umbrella line 841 (která depictuje real masked token `eyJ•••AbcD`). v0.1 specifies Option A: backend computes mask `first_8 + "•"×15 + last_4` server-side, returns v `AuthVerifyResponse.masked_token`. JWT header bytes nejsou PII, separation of concerns (config endpoint nesmí cross-couplovat auth state). Settings mount triggers implicit verify to populate.
2. **D8 DEFAULT_YAML seed paths rewritten** — v0 měl `D:\Recordings\...` placeholders co fail config validation na machine without `D:\`. v0.1 uses `${STATE_ROOT}\Recordings\...` per Gap 7 reasoning + dokumentuje literal `${STATE_ROOT}` substitution rule.
3. **Gap 1 promoted recommend → decided.** v0 mělo Gap 1 jako "recommend" ale AC #8 testovala jako decided spec. v0.1 spec decides definitive UX: first error inline + trailing button "(+N dalších chyb)" + click expands `<details>` list + click on item promotes to current (gutter highlight switches).
4. **Gap 9 added: textarea Tab key behavior.** Plain `<textarea>` Tab moves focus, breaking YAML indent edit. Decision: `onKeyDown` interceptor inserts 2 spaces (Shift+Tab dedents); Esc blurs textarea jako keyboard nav escape hatch. ~15 LoC.
5. **D11 added: privacy discipline note** per CLAUDE.md "never inline business labels in messages". Forbidden patterns + grep-able acceptance criterion (#19).

**Minor nits applied:**

- Gap 10 added: gutter perf with large configs (memoize line-number array; 500-line cap in Out of scope; aria-hidden on gutter).
- DEFAULT_YAML auto-seed promoted from Open question to **cross-spec impact item** — sync-core spec needs v0.3 revision (auto-seed in `config.load_config()` + `${STATE_ROOT}` substitution rule + parent mkdir for seed paths).
- LoC budget phrasing fixed ("90 % slack" → "~90 LoC headroom").
- AC expanded 16 → 20: auto-verify mount, multi-error promote-to-current, Tab indent, gutter perf, privacy grep.
- TS type fixed: `masked_token` removed from `ConfigResponse`, added to `AuthVerifyResponse`.

**Verdict:** review verdict was APPROVE WITH MINOR FIXES; v0.1 ships all must-fixes + relevant nits. No spec-blocking gaps remain.

**Process note:** code-reviewer agent surfaced exactly the kind of cross-spec contradictions writer's-eyes miss (v0 had `masked_token` v ConfigResponse TS type which contradicts both umbrella spec and the spec's own Gap 2 recommendation). Confirms value of independent review pass after spec writing — formalize jako step v writing-specs cycle pro umbrella+per-screen specs.

---

## 2026-04-25 — Settings screen spec: extracted from prototype + review delta

Companion k Dashboard specu (zápis níže). Stejný `frontend/PlaudSync UI.html` prototype obsahuje i Settings screen (ConnectionPanel + ConfigPanel + YamlEditor) — extracted contract proti UI architecture umbrella v0.2 + sync-core v0.2 (config.py + ConfigParseError) + auth design (PlaudTokenMissing/Expired).

Output: `docs/superpowers/specs/2026-04-25-settings-screen-design.md`. Sekce:

- **10 design decisions extracted** (D1–D10): layout (ConnectionPanel above ConfigPanel), token display contract (masked, "z .env" chip, hint blok), verify button state machine (idle/verifying/success/error 5 states), ConfigPanel header + Save/Reload + line counter, YamlEditor gutter+textarea+inline error footer (scroll-sync, 13/20px JetBrains Mono metrics, line highlight on error), Save button state machine, Reload behavior, DEFAULT_YAML seed template, banner derivation v Settings (token-expired surface), full localization string lock contract.
- **Component tree** s LoC budget odhadem (~300 LoC pro Settings subset; combined Dashboard + Settings ~910 — within 500–1000 budget, 90% slack).
- **TS types mirror Pydantic + auth** (ConfigResponse, ConfigSaveResponse union, ConfigSaveErrors, AuthVerifyResponse, ConfigParseError).
- **Public hooks** signatures (useConfig, useSaveConfig, useVerifyAuth) s TanStack Query 422-handling note (PUT /api/config 422 throws via fetch wrapper, vs auth verify 200+ok=false structural-result pattern).
- **8 gaps** (review delta) — 3 s decision, 5 deferred do implementation cyklu:
  - Gap 1: Multi-error 422 — prototype shows only first; recommend first inline + "(+N dalších)" hint with click-to-expand modal.
  - Gap 2: Token masking — frontend hardcoded vs backend-rendered? Recommend Option C (frontend constant 20 dots + "z .env" chip; no PII surfaced).
  - Gap 3: Inline parse error from GET /api/config (existing broken config on mount) — UI must immediately surface; mount effect.
  - Gap 4: Reload silently discards local edits (recommend native `confirm()` if dirty).
  - Gap 5: Plain textarea, no syntax highlight / auto-indent / bracket pair (skip for MVP, ~30–80 KB cost not worth).
  - Gap 6: Save always-enabled, no dirty detection (acceptable v0).
  - Gap 7: DEFAULT_YAML seed — sync-core auto-creates vs user manual? Cross-spec note for sync-core impl: auto-create v config.load_config + relax parent-must-exist for seed.
  - Gap 8: PUT /api/config 422 vs auth verify 200+ok=false convention split — document v client.ts wrapper.

**Open questions (for implementation cycle):** masked_token placement (verify response / config response / frontend constant — default C), multi-error display (first-only with hint vs all-listed), reload confirm dialog UX (native vs custom modal vs silent), DEFAULT_YAML seed location (sync-core vs UI backend — cross-spec impl decision), save dirty disable (always-enabled vs disabled-when-clean).

**Implementation gating:** Settings frontend writing-plans čeká na sync-core impl (Config + ConfigParseError) + UI backend impl (ConfigResponse shape) + Dashboard spec (companion, already shipped at 49c8e4e). Sequence unchanged: sync-core impl (in progress, 7cd5885 latest) → UI backend plan → UI backend impl → Frontend plan (Dashboard + Settings combined) → Frontend impl.

**Process note:** stejný extracted-from-prototype workflow jako Dashboard. User design je hotový v prototype; spec je contract + review findings + acceptance criteria, ne re-design. Brainstorming skill záměrně neinvokován (žádné design rozhodnutí k prozkoumání).

---

## 2026-04-25 — Dashboard screen spec: extracted from prototype + review delta

User měl Dashboard design hotový v Claude Design prototype (`frontend/PlaudSync UI.html`, commit 1ea6bd3 — 1222 LoC HTML+React+Tailwind, 5 plně funkčních scenarios + ConnectionLostOverlay + 12 sample recordings). Místo brainstormu od nuly proběhl **review** prototype proti UI architecture umbrella v0.2 + sync-core v0.2 specs.

Output: `docs/superpowers/specs/2026-04-25-dashboard-screen-design.md`. Sekce:

- **10 design decisions extracted** (D1–D10): layout, SyncNowPanel 6 states, RecordingsList row format, ProjectBadge color taxonomy, SyncStatusBadge 5 states, BannerStack derivation rules, Toast triggers, ConnectionLostOverlay terminal error UX, live recordings list during sync, polling cadence (5s idle / 1.5s running).
- **Component tree** s LoC budget odhadem (~610 LoC pro Dashboard subset, total frontend ~810 — within UI umbrella 500-1000 budget).
- **TS types mirror Pydantic** (StateResponse, RecordingRow, SyncState, SyncProgress, ClassificationStatus, RecordingStatus).
- **Public hooks** signatures (useStateQuery, useStartSync) s TanStack Query polling pattern.
- **7 gaps** (review delta) — 3 s decision, 4 deferred do implementation cyklu:
  - Gap 1: `_unmapped_<project>` not visually distinct → add 3rd badge variant nebo `classification_route` field (open).
  - Gap 2: `plaud_folder` is UUID v0 (sync-core spec confirms), prototype mock shows readable strings (real production data won't match).
  - Gap 3: `target_dir` not displayed (acceptable v0; tooltip on ProjectBadge as Phase 2).
  - Gap 4: "Zobrazit log" action behavior undefined (4 options A/B/C/D, default C = toast pointing to file).
  - Gap 5: Loading state during cold start (skeleton vs spinner — pick during impl).
  - Gap 6: Live recordings no animation (acceptable v0).
  - Gap 7: Banner dismissal across sessions (acceptable v0; localStorage-backed if feedback needs).

**Open questions (for implementation cycle):** classification_route field design, log action behavior, loading skeleton vs spinner, UUID truncation in plaud_folder display.

**Implementation gating:** Dashboard frontend writing-plans čeká na sync-core impl (Pydantic shapes) + Settings spec + UI backend writing-plans + impl. Sequence: sync-core impl → Settings review → UI backend plan → UI backend impl → Frontend plan (Dashboard + Settings combined) → Frontend impl.

---

## 2026-04-25 — Categorization implementation: regex-only classifier shipped

Implementation execution of `docs/superpowers/plans/2026-04-25-categorization.md` via subagent-driven-development. 9 commits on master (Tasks 1–9).

### What landed

- **New module:** `src/plaudsync/categorization.py` (~75 LoC) — frozen `ClassificationResult` dataclass (`status`, `project`, `matched_date`) + `classify(title, created_at)` function. Handles `(YYYY-)?MM-DD <Project>: <rest>` title format. Emits structured log warnings for year-mismatch and invalid-date cases (never inline business labels in message text).
- **Tests:** 14 unit tests in `tests/test_categorization.py` + 1 scrubber test in `tests/test_smoke.py` (plaud_folder redaction).
- **Observability:** `observability._REDACTED_KEYS` extended with `plaud_folder` key (defense in depth, kill #18 — ensures plaud_folder UUID never surfaces in Sentry even if sync engine logs it).
- **Repo cleanup:** `anthropic`, `msal`, `deepeval` removed from deps; `tests/evals/` directory removed; DeepEval / golden-set references purged from CLAUDE.md + settings.json.
- **Kill criterion swap:** #5 updated from "LLM accuracy ≥ 70 %" to "regex coverage rate ≥ 90 % over sliding 30-day window" (SPEC.md already at v0.2, sync-debug + cassette-refresh skills updated).
- **Doc cascade (Task 9):** SPEC.md confirmed v0.2 (no edits needed). CLAUDE.md, DEV_LOG.md, pyproject.toml, settings.json, sync-debug SKILL.md, cassette-refresh SKILL.md, memory/project_plaud_categorization.md all updated.

### Reference plan

`docs/superpowers/plans/2026-04-25-categorization.md`

---

## 2026-04-25 — Categorization + sync-core implementation plans written

Two writing-plans outputs published:

- `docs/superpowers/plans/2026-04-25-categorization.md` — 9 TDD tasks for single-layer regex classifier (~50–70 LoC src + ~150 LoC tests). Includes repo-wide cleanup (drop `anthropic`/`msal`/`deepeval`, remove `tests/evals/`, swap kill criterion #5 from LLM accuracy to regex coverage rate).
- `docs/superpowers/plans/2026-04-25-sync-core.md` — 16 TDD tasks for sync core (8 new modules + 4 modifications). Pre-baked endpoint discovery appendix in sync-core spec (5 community Plaud clients reverse-engineered by Explore subagent).

### Endpoint discovery (sync-core spec appendix)

Reverse-engineered from `sergivalverde/plaud-toolkit`, `leonardsellem/plaud-sync-for-obsidian`, `iiAtlas/plaud-recording-downloader`, `arbuzmell/plaud-api`, `openplaud/openplaud`. Cross-validated High-confidence endpoints:

- `GET /file/simple/web?skip=N&limit=50&is_trash=0` — listing + region probe (offset pagination).
- `GET /file/temp-url/{id}` → JSON with `temp_url` (S3 presigned, no auth header on S3).

Two material spec corrections from discovery:

1. **`since` is client-side only** — Plaud listing has no server-side `since` param. Iterator stops early on first older record (Plaud returns desc by `start_time`).
2. **`plaud_folder` is a UUID** (`filetag_id` / `tag_ids[0]`), not a display name. v0 ships UUIDs through path_resolver sanitization; v1 brainstorm resolves UUID → name via separate (un-discovered) `/tag/list` endpoint.

### Plan execution order recommendation

1. **Categorization plan** first (smaller, no external dependencies, repo cleanup unblocks subsequent work).
2. **Sync-core plan** second (depends on categorization `ClassificationResult` + auth layer + portalocker).
3. **UI plan** third (after Claude Design prototype + per-screen brainstorm cycles).

Both plans use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` for execution.

---

## 2026-04-25 — Cascade: per-project absolute paths

User požadavek: každý projekt má vlastní lokální cílovou cestu, žádný společný kořen (např. ProjektAlfa na `C:\`, ProjektBeta na `D:\`). Tento požadavek vyšel najevo po obdržení Claude Design ZIP prototypu — Settings YAML editor potřeboval konkrétní schema.

### Q&A z brainstorm session

| # | Otázka | Volba | Důvod |
|---|---|---|---|
| 1 | Kde žije `state.db` + lock file (když není společný recordings root)? | **A** Nový env var `PLAUDSYNC_STATE_ROOT` (state-only umístění, žádné recordings) | Vyhne se duplicitě YAML+env. Bootstrap location musí být env var, behavioral routing je YAML. |
| 2 | Jak řešit "title matchne projekt, config ho nezná"? | **A** Soft fallback do `${unclassified_dir}/_unmapped_<project>/` | Symetrie s "title nematchne". Sync pokračuje, log warning + sentry tag. User vidí přesný project label v Exploreru. |
| 3 | Per-Plaud-folder subdivize unclassified bucketu? | **A** Zachovat | Beze změny chování v původním v0.1. Kontext z Plaud workflow se neztrácí. |

### YAML schema

```yaml
unclassified_dir: D:\Recordings\Unclassified
projects:
  ProjektAlfa: C:\Projects\Alpha\Recordings
  ProjektBeta: D:\Clients\Beta\Audio
```

Validace v `config.py.load_config()`: `unclassified_dir` + všechny project paths absolutní, parent existuje, žádné `..` (path traversal guard).

### Cascade dopady (4 commits)

1. **categorization v0.2** (025e609) — `ClassificationResult.target_subdir` dropped, `classify()` ztrácí `plaud_folder` parametr, `_sanitize_folder_name` přesunut. Test count 12 → 10.
2. **sync-core v0.2** (a1eac75) — nové moduly `config.py` + `path_resolver.py`. Env var rename. `recordings.local_path` absolutní. Nový exit code 7 (ConfigValidationError). Test count 24 → 37.
3. **ui-architecture v0.2** (aa0238e) — env var rename, lifespan handler načítá config.yaml + state.db z STATE_ROOT, `RecordingRow.target_subdir` → `target_dir` (absolutní). Settings empty-config template ukazuje konkrétní YAML schema.
4. **SPEC.md v0.2 + .env.example** (this commit) — single-layer regex deklarace, M365+Anthropic z paid deps pryč, success criterion #2 změněno z "LLM accuracy" na "regex coverage".

### Architectural insight

YAML config = **per-project routing** (kde co skončí). Env var = **bootstrap** (kde najít YAML). Po cascade je separation čistá, žádná chicken-and-egg.

### Process notes

- Brainstorming skill aplikován (continued v stejné conversation jako UI architecture brainstorm). 3 clarifying questions (Q1/Q2/Q3) s explicit recommendations a counterarguments. User schválil `OK` → proceeded with cascade in 4 separate commits per spec (jeden commit per spec = lepší git log než mega-commit).
- Counterargument bias watch (z 2026-04-24 SPEC pivot): user opět zvolil 3× recommendation. Watch item formalizace stále `#1` z workflow memory (> 2 korekce per task = trigger; opak = under-watch).
- Discovered v0.2 trigger: user feedback z prototypu odhalil missing config schema detail. **Lekce:** spec brainstorm bez mockupu může minout konkrétní data shapes, které prototyp explicitně potřebuje. Pro budoucí umbrella specy zvážit "data shape draft" pass před writing.

---

## 2026-04-24 — Auth layer implemented (plan 2026-04-24)

Plán `docs/superpowers/plans/2026-04-24-plaud-auth.md` dokončen. 12 testů zelených (`pytest tests/`), bandit clean (61 LoC auth modulů), log a Sentry scrub hygiene gates prošly (smoke token `unique-smoke-token-xyzzy-9876` neunikl).

### Odchylky od plánu (zaznamenané rozhodnutí během implementace)

- **Task 1 přeskočen.** Plán počítal s hand-crafted VCR cassettami. User v novém zadání vyžádal `@pytest.mark.vcr` **s reálnou Plaud API call** — cassetty jsou nyní recorded proti skutečnému API (scrubnuté authorization + Set-Cookie).
- **Verify endpoint změněn z `/me` na `/file/simple/web`.** Plaud nemá dedikovaný auth-check endpoint (ověřeno v `arbuzmell/plaud-api` zdroji: `session.py` jen reactive-auth, žádný verify call). `/me` vrátil 404. Použili jsme `FILE_SIMPLE = "https://api.plaud.ai/file/simple/web"` — nejlehčí file-listing endpoint, který je authenticated.
- **VCR conftest upgrade.** Přidán `VCR_RECORD_MODE` env var pro one-off re-recording bez trvalého loosening `conftest.py` (default zůstává `"none"` = replay-only).
- **Sentry SDK 2.x API.** Původní plán používal `sentry_sdk.Hub.current.client` a `push_scope()` — oba deprecated. Implementace používá `is_initialized()` a `new_scope()`.
- **Test exit-code regressions.** Testy volající `main()` musí monkeypatchnout `sys.argv` (kvůli argparse) i `load_dotenv` (kvůli vyplněnému `.env`).

### Region mismatch — tech debt pro sync-engine

Plaud API na `api.plaud.ai/file/simple/web` vrátil HTTP 200 **s body** `{"status":-302,"msg":"user region mismatch","data":{"domains":{"api":"https://api-euc1.plaud.ai"}}}`. Účet je EU region → měl by používat `api-euc1.plaud.ai`. Auth verify stačí HTTP 200 (token valid), ale **sync-engine feature MUSÍ parsovat region redirect** a používat regional endpoint pro listing/download recordings. Zaznamenáno jako sync-engine prerequisite.

### Co je hotové

- `src/plaudsync/auth.py` — `load_token()` + `PlaudTokenMissing` + `PlaudTokenExpired`
- `src/plaudsync/plaud_client.py` — `PlaudClient(token)` + `verify()` + context manager
- `src/plaudsync/__main__.py` — argparse s `verify` subcommand, exit codes 2/3, `_capture_sentry()` helper s fingerprint+tag
- `src/plaudsync/observability.py` — extended `_scrub_string` s Bearer + PLAUD_API_TOKEN value redaction
- 10 auth testů (4 `test_auth.py`, 2 `test_plaud_client.py` vč. scrubbed cassetty, 4 `test_main_exit_codes.py`)
- `tests/conftest.py` — VCR_RECORD_MODE env var support

### Další krok

Viz user rozhodnutí — Claude Design UI prototyp → per-screen brainstorm, nebo sync-engine brainstorm (musí zahrnout region redirect handling).

### Process notes

- TDD cyklus držel disciplínu: failing-test commit **samostatně** od impl commitu, každý TDD cycle jeden red → green pár.
- Subagent dispatch (Task 1 scaffolding) byl zrušen userem a implementováno přímo — odlišný dynamikou proti skill flow, ale výsledek funguje.
- Branch `feat/plaud-auth` obsahuje ~14 commitů (plán adjust, 2 commity per task ~ 8 tasks, post-flight TBD). Před mergem do master: `/security-review` + manual review diff.

---

## 2026-04-24 — SPEC pivot: UI z out-of-scope do core scope

Paralelně s auth brainstormem vyšlo najevo, že user má širší představu o produktu, než zachycoval v0 draft. SPEC.md explicitně říkal "UI / web dashboard = out of scope". Pivot tento řádek smazal a přidal UI vrstvu do core v0.

### Brainstorm session — kontext metodiky

Brainstorm byl veden podle [Superpowers `brainstorming` skill SKILL.md](../../Users/ai_martint/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/brainstorming/SKILL.md). V té konkrétní session, kde pivot proběhl, byl Skill tool call `superpowers:brainstorming` ještě odmítnutý s "Unknown skill" (session začala před `Developer: Reload Window`, viz samostatný záznam o verifikaci níže). **Fallback:** SKILL.md byl přečten přes `Read` tool a postupováno ručně podle něj (explore → clarifying → options → present → write spec → self-review). Po Reload Window by měl skill fungovat normálně — budoucí session už může volat `Skill("superpowers:brainstorming", ...)` přímo.

### Rozhodnutí z pivotu

| # | Otázka | Volba | Důvod |
|---|---|---|---|
| 1 | MVP scope | **A** Minimalistic (Dashboard + Sync Now + Settings, bez heat mapy) | Rychlejší feedback loop, UI reálně použitelné dřív než guess work pro advanced features. Heat mapa → v1.1 po 2 týdnech reálných dat. |
| 2 | Architektura | **C** GUI + CLI (SQLite + YAML = shared state) | Zachovává existing CLI invest, žádný daemon, žádný single point of failure, kill-criterion-friendly. |
| 3 | UI stack | **B** FastAPI + React + PyWebView | Claude Design prototyp (= React) přímo použitelný, desktop UX vs browser UX, Win11 WebView2 native. |
| 4 | UI lifecycle | **A** On-demand only | Menší scope pro MVP, žádný tray icon / autostart komplikace, clean separation (Task Scheduler = time-based, UI = user-triggered). |

### Dopady

- **`SPEC.md` updated** (v0 → v0.1): nová UI scope sekce, constraints (Node 20+, WebView2, sync idempotence), success criteria (UI cold start ≤ 3 s, Sync Now latence ≤ 2 s), architectural decisions (UI architektura rozepsaná), kill criteria (preambule k UI watch).
- **Auth spec zapsán** do `docs/superpowers/specs/2026-04-24-plaud-auth-design.md` — kompletní design vč. UI API consumer use case (FastAPI endpoint `POST /api/auth/verify`).
- **Následné brainstorm cykly:** každý UI subsystém dostane vlastní spec (Settings screen, Dashboard screen, Sync Now orchestrace, backend endpoints). SPEC.md je jen rámec.
- **LoC budget upgrade:** Python 1500–3000 (beze změny) + React/TS 500–1000 (nově).

### UI layer watch (kandidáti na budoucí kill criteria)

Tyto "watch items" nejsou formální kill criteria (zatím). Pokud některý začne triggerovat opakovaně, formalizujeme ho a přidáme do trackeru níže:

- **W-U1: WebView2 kompatibilita** — PyWebView na Win11 out-of-box spolehlivě? Pokud dev stanice ukáže crash rate > 1× týdně, re-evaluate (browser fallback).
- **W-U2: React bundle size** — MVP A (2 screens) by měl vejít pod 500 KB gzipped. Nad 1 MB = signal scope creep nebo špatně rozdělený import.
- **W-U3: Vite/Node dep churn** — npm ecosystem známý velkým dependency fan-outem. Pokud `npm audit` > 5 high-severity nevyřešitelných v průběhu 2 týdnů = re-evaluate frontend stack.
- **W-U4: Frontend build čas** — cold Vite build > 30 s = investigate / kill criterion kandidát (spolu s existing T-8 CI slowdown).
- **W-U5: Sync Now subprocess protocol** — progress streaming přes subprocess stdout je křehké na encoding / flushing. Pokud víc než 2 bugy v 1 měsíci, zvážit SQLite-based progress table místo stdout.

### User actions z brainstormu

- Připravit **prototyp v Claude Design** (2 screens: Settings, Dashboard) — předá jako podklad pro per-screen brainstorm.
- Až bude prototyp, otevřít per-feature brainstorm cykly (postupně, ne naráz).
- Ideation session pro "další užitečné nápady" — parkoviště nápadů po tom, co uvidíme prototyp.

### Process note (counterarguments bias watch)

Brainstorm šel striktně dle skill checklistu. User volil ze 4 options 4× recommendation — žádný pushback na zvolenou variantu. Co to může znamenat:
- (a) recommendations byly solidní a user je skutečně přijal;
- (b) formulace recommendations byla příliš persuasive a user neměl reálnou volbu;
- (c) user vím, kam chce, takže se jen ujistil, že můj návrh tam vede.

**Akce pro příští brainstorm sessions:** zvýšit důraz na **counterarguments** u vlastní recommendation (explicitně pojmenovat, kdy by uživatel měl zvolit jinou variantu). Watch: pokud i další brainstorm session skončí 100% alignment, formalizovat jako workflow bias (kill criterion #1 z memory: > 2 korekce per task = trigger; opak problému — žádná korekce = je to dobře nebo je to špatně?).

---

## 2026-04-24 — Hook smoke test: H-10 baseline measured

`.claude/hooks/pytest_on_edit.py` ověřen empiricky:

- **Manuální pytest baseline:** `pytest tests/ -x --lf -q` = 0.02 s test runtime, 3.9 s total wall clock (Python interpreter cold start + venv + pytest collection).
- **Hook simulation** (`echo '{"tool_input":{"file_path":"tests/test_smoke.py"}}' | python .claude/hooks/pytest_on_edit.py`) → exit 0, pytest 2 passed.
- **Hook automatický trigger po Claude Edit/Write**: empiricky neověřeno (Claude Code suppresí hook stdout/stderr v conversational view). Hook script sám funguje, takže pokud Claude Code hooks nefungují, je to platform issue, ne náš bug.

Kill criterion **H-10** (hook > 10 s @ 2 týdny → disable hook): aktuální 3.9 s wall = **39 % budgetu**. Pohoda. Threshold se může zhoršit, až přibude víc testů (zvlášť VCR cassette replay nebo DeepEval), monitorovat.

**Vytvořeno:** `tests/test_smoke.py` (2 trivial testy, jen aby pytest měl co collectovat — bez nich `pytest --lf` failuje s "no last failed" warningem v některých edge cases).

## 2026-04-24 — Sentry smoke test: L-18 partial leak + fix

První běh `scripts/sentry_smoke.py` proti Sentry produkčnímu DSN (free tier). PLAUDSYNC-1 event přišel, scrubbing částečně leakoval. Opraveno hned, druhý běh pending verifikace v UI.

### Findings (první běh)

| Co testováno | Status | Detail |
|---|---|---|
| `<path>` substituce v message | ✅ | `C:\PlaudRecordings\...mp3` → `<path>` |
| Tag `category` | ✅ | `<redacted-label>` |
| Tag `project_name` | ✅ | `<redacted-label>` |
| Context "recording" header | ✅ | `<redacted-label>` |
| **Inline `key=value` v message** | ❌ | `project=AcmeCorp-Internal`, `category=ProjectAlpha` prosvistly |
| **Tag `server_name`** | ❌ | `TOMISM` (hostname) prosvistlo |
| User Geography (IP-derived) | ⚠️ | `Ostrava, Czechia` — vyžaduje server-side "Prevent Storing of IP Addresses" v Sentry settings |

### Fixes (commit pending)

1. **observability.py** — přidán `_INLINE_LABEL_RE` pattern, který scrubuje `(category|project_name|...)\s*[=:]\s*<value>` v plain text stringech (exception messages, log lines).
2. **__main__.py** — `sentry_sdk.init(server_name="<redacted>", ...)` natvrdo přepíše hostname.
3. **CLAUDE.md** — nová sekce "Privacy / observability rules": **"Never inline business labels in exception messages or log strings."** Vždy přes `set_tag` / `set_context` / `logger.bind`. Důvod: scrubber regex je best-effort pro free-form text, easy miss.

### Architectural insight

Smoke test ukázal jemnou architekturní propast: **scrubber je defense-in-depth, ne primární obrana**. Primární obrana je **convention** — ne dávat business labels do free-form messages vůbec. Convention je v CLAUDE.md, scrubber je safety net pro slip-ups. Server-side Sentry rules (Sensitive Fields, IP scrubbing) jsou třetí vrstva.

### User action — completed

- ✅ Ověřeno v Sentry UI 23:25: druhý event (timestamp 23:23:45) má `project=<redacted-label>`, `category=<redacted-label>`, `server_name=<redacted>`. Message, tags i contexts všechny scrubnuté.
- ✅ Sentry Settings → "Prevent Storing of IP Addresses" zapnuto. Geography leak skončí u příštích eventů.
- ⏳ Resolve PLAUDSYNC-2 v Sentry UI (UnicodeEncodeError, můj bug v print, opraveno) — kosmetické, ne blokující.

**L-18 verified clean.** Privacy posture pro recording-processing tool ready pro produkční nasazení.

## 2026-04-24 — Superpowers verified (post Reload Window)

Po `Developer: Reload Window` ve VSCode a fresh chat session jsou Superpowers skills správně exponovány přes Skill tool. `/context` ukazuje:

**Skills přidané pluginem (17):** `using-superpowers` (meta), `brainstorming`, `test-driven-development`, `systematic-debugging`, `subagent-driven-development`, `verification-before-completion`, `requesting-code-review`, `receiving-code-review`, `dispatching-parallel-agents`, `executing-plans`, `writing-plans`, `writing-skills`, `using-git-worktrees`, `finishing-a-development-branch`, `superpowers:brainstorm`, `superpowers:write-plan`, `superpowers:execute-plan`.

**Custom agent přidaný pluginem:** `superpowers:code-reviewer` (353 tokens) — explicit subagent pro code review.

### Final baseline numbers

| Kategorie | Tokens | Změna proti pre-Superpowers |
|-----------|-------|------------------------------|
| Skills | 1.8k | +700 (z 1.1k) |
| Custom Agents | 353 | +353 (nová sekce) |
| System prompt | 9.4k | beze změny |
| **Project + plugin overhead celkem** | **~3.0k** | **+1.1k** |

**Superpowers footprint je extrémně levný — ~1.1k tokens nad pre-install baseline.** Hluboko pod jakýmkoli rozumným kill criterion threshold. Hard enforcement TDD (auto-delete code-before-test) by mělo být aktivní.

### Sekundární observace (od user)

User upozornil na potenciální dual-user issue: directory `c:/GitHub/PlaudSync` je vlastněna Windows uživatelem `martint`, zatímco Claude Code proces běží pod `ai_martint`. Vyřešeno přes `git config --global --add safe.directory C:/GitHub/PlaudSync`. Zatím **žádné funkční selhání**, ale risk indicator pro budoucí permission edge cases (antivirus, Windows Defender, file lock kdyby martint user otevřel stejný file současně).

**Aktualizace ze Sentry smoke testu (2026-04-24 ~23:13):** Při běhu `scripts/sentry_smoke.py` traceback ukázal cestu `C:\Users\martint\AppData\Local\Programs\Python\Python312\Lib\encodings\cp1250.py`. To znamená, že **Python 3.12 interpreter v `.venv/` (a ten, ze kterého byl venv vytvořen) je instalován pod uživatelem `martint`, ne `ai_martint`**. Důsledky:

- Per-user Python instalace (`%LOCALAPPDATA%\Programs\Python`) jiného uživatele je *čitelná* z `ai_martint` procesu (proto venv funguje), ale není *vlastněná* — Windows Defender / antivirus může intermittently blokovat.
- Kdyby `martint` reinstaloval / odinstaloval Python 3.12, venv v PlaudSync by se rozbil.
- Pokud bude potřeba upgrade Python (3.13+), instalace musí proběhnout pod správným uživatelem (ideálně `ai_martint` for full ownership, nebo system-wide install).

**Mitigace pro teď:** žádná akce, jen poznamenat. Pokud se objeví venv permission errors při příští `pip install`, tohle je primární podezřelý.

## 2026-04-24 — Baseline /context measurement (post Superpowers install) [SUPERSEDED]

> **Tento záznam byl nahrazen verifikací výše po Reload Window. Ponecháno pro historii rozhodnutí.**



`/context` po (údajné) instalaci Superpowers. Celkový context 279.3k / 1M (28 %), z toho 245.7k jsou aktuální messages (nezapočítávají se do harness baseline).

**Harness-only baseline** (vše kromě Messages + Autocompact buffer):

| Kategorie | Tokens |
|-----------|--------|
| System prompt (Claude Code + CLAUDE.md + auto-memory) | 9.4k |
| System tools (Read/Write/Edit/Bash/…) | 20.8k |
| System tools (deferred) | 15.1k |
| MCP tools (deferred) | 5.0k |
| Memory files (MEMORY.md + CLAUDE.md) | 2.3k |
| Skills (všechny Claude Code + User + Project) | 1.1k |
| **CELKEM** | **~53.7k** |

**Project-specific přírůstek** (to, co přidává PlaudSync harness):
- `CLAUDE.md` v project root: 1.8k
- `cassette-refresh` skill: 58 tokens
- `sync-debug` skill: 54 tokens
- **Celkem cca 1.9k tokens** — velmi štíhlé.

### ⚠️ Pozorování: Superpowers skills nevidím v context outputu

V `Skills` sekci výstupu jsou: `update-config`, `keybindings-help`, `simplify`, `fewer-permission-prompts`, `loop`, `schedule`, `claude-api`, `cassette-refresh`, `sync-debug`, `pruzkum`, `therapy`, `init`, `review`, `security-review`. **Žádná z typických Superpowers skills** (`brainstorming`, `test-driven-development`, `debugging-methodology`, `subagent-driven-development`, `creating-skills`) v listu není.

Možná vysvětlení:
1. Superpowers injektuje do **system promptu** (~9.4k) přes SessionStart hook, ne přes skills registry. Pak by footprint byl v system prompt číslu a my bychom to nepoznali z rozkladu. (Dle kola 2 průzkumu: *"The hook reads the using-superpowers meta-skill and injects it into Claude's system prompt wrapped in EXTREMELY_IMPORTANT tags."*)
2. Instalace proběhla, ale v této session se neprojevuje (potřeba restart / fresh session).
3. Plugin je instalovaný, ale skills se rozbalují on-demand a /context je ukazuje až po prvním použití.

**Akce k ověření:** v následující session napsat "použij Superpowers brainstorming skill pro nějaký malý brainstorm" — pokud skill odpoví, je aktivní. Pokud ne, přeinstalovat / zkontrolovat `/plugins` UI.

### Kill criterion H-9 — recalibrace

Original threshold ("context baseline > 15k tokens na session start") **byl špatně kalibrovaný** — neuvažoval s base Claude Code infrastrukturou (~55k tokens i bez jakéhokoli pluginu). Rekalibrace:

- **Claude Code infrastructure baseline** (bez projectu): ~50–55k — mimo kontrolu.
- **Project overhead budget** (to, co přidává PlaudSync harness + Superpowers inject do system promptu): **budget < 10k**, trigger > 15k.
- **Aktuální stav bez Superpowers**: project overhead ~1.9k (CLAUDE.md + 2 skills). Pokud Superpowers přidá do system prompt +5k, dostaneme se k ~7k — stále pod budget.

Revised kill criterion: **project overhead (nad Claude Code baseline 55k) > 15k** @ 1 měsíc → redukovat.

### 2026-04-24 — Harness bootstrap

Založena struktura projektu po průzkumech kol 1–4. Soubory vytvořeny: `SPEC.md`, `CLAUDE.md`, `DEV_LOG.md`, `.gitignore`, `.env.example`, `pyproject.toml`, `.claude/settings.json` + `.claude/hooks/pytest_on_edit.py`, `.claude/skills/{cassette-refresh,sync-debug}/SKILL.md`, `src/plaudsync/{__init__,__main__,observability}.py`, `tests/{__init__,conftest}.py` + `tests/evals/golden_set.yaml` skeleton.

Čeká na user actions: `pip install -e .[dev]`, Sentry account signup, `/plugin install superpowers`, baseline `/context` measurement, Windows Task Scheduler dry-run.

---

## Kill criteria tracker

18 pre-registered kill criteria z kol 1–4. Sleduj trigger risk měsíčně; při triggeru doplň záznam a rozhodnutí (follow/redesign/defer).

### Kolo 1 (workflow metodika)

| # | Criterion | Last check | Status |
|---|-----------|-----------|--------|
| 1 | > 2 korekce per task na 3+ tascích @ 2 týdny | — | not started |
| 2 | > 30 % false-pass v TDD (mock pass, real fail) @ 1 měsíc | — | not started |
| 3 | SPEC.md bez git update @ 4 týdny | 2026-04-24 (created) | active |
| 4 | Plan Mode overhead > 30 % @ 1 měsíc | — | not started |
| 5 | Regex match coverage < 90 % na sliding 30-day window | — | not started (swapped 2026-04-25 from LLM accuracy → regex coverage per categorization v0.2) |

### Kolo 2 (tooling)

| # | Criterion | Last check | Status |
|---|-----------|-----------|--------|
| T-5 | Cassette re-record > 1×/měsíc kvůli nestabilitě | — | not started |
| T-6 | DeepEval dependency conflict s Anthropic/OpenAI SDK | — | superseded 2026-04-25 (DeepEval dropped with regex-only categorization) |
| T-7 | Superpowers context pollution > 30 % nevyužíván @ 3 týdny | — | not started (pending install) |
| T-8 | CI slowdown > 30 s vs baseline @ 1 měsíc | — | not started |

### Kolo 3 (harness)

| # | Criterion | Last check | Status |
|---|-----------|-----------|--------|
| H-9 | **Project overhead > 15k tokens** nad Claude Code ~55k baseline @ 1 měsíc (recalibrated 2026-04-24) | 2026-04-24 | OK (~3.0k project+Superpowers overhead, 20% budgetu) |
| H-10 | PostToolUse hook > 10 s průměrně @ 2 týdny | 2026-04-24 | OK (baseline 3.9 s = 39 % budgetu, hook script funguje) |
| H-11 | Superpowers TDD enforcement selhává (> 20 % commitů má testy po source) | — | not started |
| H-12 | Harness blokuje cross-platform práci | — | not started |
| H-13 | Task Scheduler miss rate > 5 %/měsíc OR sync potřeba mimo laptop uptime | — | not started |

### Kolo 4 (lifecycle)

| # | Criterion | Last check | Status |
|---|-----------|-----------|--------|
| L-14 | Sentry free tier překročen > 2× @ 3 měsíce | — | not started |
| L-15 | /review > 80 % false positives @ 2 týdny | — | not started |
| L-16 | Architecture drift — za 3 měsíce nerozumím SPEC.md | — | not started |
| L-17 | Writer/Reviewer > 2× čas vs plain Plan Mode @ 1 měsíc | — | not started |
| L-18 | **Sentry scrubbing selhává** (unscrubbed paths/labels v UI) @ 2 týdny | 2026-04-24 23:25 | OK (verified po fix: message, tags, contexts všechny scrubnuté; geography fix přes "Prevent Storing of IP Addresses" zapnut user-side) |

**Most likely first triggers** (dle retrospektivy):

1. L-18 (Sentry scrubbing — file-heavy app privacy)
2. #3 (SPEC.md anchor dies pattern)
3. H-13 (Task Scheduler miss rate — Win stanice uptime issues)

---

## Token/context baseline

- **2026-04-24 pre-Superpowers-active (toggle off, skills nevidím):**
  - Total harness baseline: ~53.7k (z toho project overhead ~1.9k)
- **2026-04-24 post-Superpowers-active (Reload Window, skills exponovány):**
  - Total harness baseline: ~54.8k (z toho project + Superpowers overhead ~3.0k)
  - Superpowers contribution: **+1.1k tokens** (700 skills + 353 custom agent)
- **Target (rekalibrovaný):** project overhead < 15k nad Claude Code ~55k base. **Aktuální využití: 3.0k / 15k = 20% budgetu** — pohoda.

---

## Correction counter (kolo 1 kill criterion #1)

Po každé task v Claude Code poznamenej: task id, počet mých "no/přepiš/to není to co chci" korekcí.

| Date | Task | Corrections | Notes |
|------|------|-------------|-------|
| — | — | — | — |
