# PlaudSync — Specification

> **Status:** draft v0.3 (2026-04-26, post tray pivot). One-page anchor artifact per průzkum kolo 1.
> Actualizuj při každém scope pivotu. `git log SPEC.md` nepohnutý > 4 týdny = kill criterion trigger (viz memory `project_plaud_dev_workflow.md` #3).

## Problem

Plaud AI nahrávky se nesynchronizují automaticky s lokální stanicí ani s projektovou strukturou na disku. Manuální stahování a třídění je časově náročné a nespolehlivé — nahrávky mizí nebo končí na špatném místě. Potřebujeme periodický proces, který: (a) stáhne nové recordings z Plaud cloudu, (b) klasifikuje je do projektů podle title regex (single-layer), (c) uloží je do per-project složek na disku (každý projekt má vlastní absolutní cestu).

## Scope (v0)

### Sync engine

- Pull new recordings from Plaud API od posledního úspěšného sync (incremental).
- Uložit originální audio na lokální disk (transcript out of scope v0 — viz Out of scope).
- **Single-layer regex klasifikace** title → project name. Detail v [docs/superpowers/specs/2026-04-25-categorization-design.md](docs/superpowers/specs/2026-04-25-categorization-design.md).
- **Per-project absolutní cílové cesty** z YAML configu — `${config.projects[name]}/{YYYY-MM-DD}_{title_slug}.{ext}` pro matched. Žádný společný kořen (každý projekt může být na jiném drive). Soft fallback do `${config.unclassified_dir}/...` pro title-no-match nebo project-not-in-config. Detail v [docs/superpowers/specs/2026-04-25-sync-core-design.md](docs/superpowers/specs/2026-04-25-sync-core-design.md).
- CLI entry point (`python -m plaudsync`) pro Task Scheduler headless běh.
- Provoz: periodic hourly run via Windows Task Scheduler.
- Observability: Loguru rotating file log + Sentry error alerting (scrubbed).
- **Tray runtime (v0.3 pivot):** primární execution model je tray-resident proces (`pythonw -m plaudsync tray`) spuštěný Task Schedulerem při loginu. Sync engine + UI launcher v jednom procesu. Periodic tick replaced in-process SchedulerThread.

### UI vrstva (přidáno 2026-04-24 pivot)

- GUI entry point (`python -m plaudsync ui`), on-demand launch, lifecycle: open → interact → exit při zavření okna (žádný tray, žádný auto-start v v0).
- Stack: FastAPI (localhost, random free port) + React/TypeScript/Tailwind (bundled static build z Vite) + PyWebView wrapper (Win11 WebView2).
- **Screen 1 — Settings:** edit `${PLAUDSYNC_STATE_ROOT}/config.yaml` — `unclassified_dir` (absolutní cesta) + `projects` mapping (`name → absolutní cesta`). PUT validate per-line s 422 errors. Plus "Test Plaud connection" tlačítko.
- **Screen 2 — Dashboard:** seznam posledních N synchronizovaných recordings (čte SQLite delta state read-only) + tlačítko "Sync Now".
- **Sync Now:** spouští CLI jako subprocess (`python -m plaudsync`); UI zobrazí progress + exit status. Concurrent launch ochráněn file lockem.
- **Auth verify endpoint:** `POST /api/auth/verify` volá `PlaudClient.verify()` a vrátí JSON status (pro "Test Plaud connection" button v Settings).

## Out of scope (v0)

- Re-processing existing recordings (jen forward-sync od install).
- Heat mapa aktivity, advanced filtry, vyhledávání v historii (v1.1+).
- Daemon / Windows Service architecture, REST API pro external integrations, remote UI.
- Multi-user nebo team sharing.
- Real-time streaming — periodic pull stačí.
- Transcript summarization or generation (pouze storage, pokud Plaud dodá).
- Mobile nebo non-Windows platforms.

## Constraints

- **Platforma:** Windows 11 Pro dev stanice. Hookování přes Git Bash; PowerShell tool je preview, ne primary dependency.
- **Python:** 3.11+.
- **Node.js:** 20+ (dev dep only — pro Vite build frontend artefaktů; build výstup bundled v Python package, runtime Node nepotřebuje).
- **WebView2 runtime:** pre-installed na Win11 out-of-box; Win10 by vyžadoval manuální install (mimo scope — Win10 není target).
- **Licence:** zero license cost — Plaud subscription je jediná paid dep. (M365 a Anthropic byly z scope vyřazeny v categorization v0.1: žádný kalendář, žádný LLM.)
- **Privacy:** Meeting recordings obsahují business content. Sentry `send_default_pii=False` + `before_send` scrubbing MUSÍ být aktivní před production provozem.
- **Solo dev:** single maintainer. Overhead metodiky musí být proporční scope.
- **Sync idempotence:** CLI sync proces musí být idempotentní proti concurrent launch (Task Scheduler ↔ manual Sync Now race). File lock + SQLite WAL mode.
- **LoC budget:**
  - Python backend 1500–3000 LoC (Plaud client, classifier, sync engine, FastAPI endpoints).
  - React/TypeScript frontend 500–1000 LoC (2 screens, MVP scope).
  - Spec Kit pivot trigger = Python > 3000 LoC (frontend se do limitu nepočítá — má vlastní sizing dynamiku).

## Success criteria

1. **Sync reliability:** hourly Task Scheduler miss rate ≤ 5 % / měsíc (jinak kill #5, přechod na Routines).
2. **Classification coverage:** regex match coverage ≥ 90 % stažených recordings za sliding 30-day window (jinak kill #5 — revize title formátu nebo přidání druhé vrstvy).
3. **Latency:** jeden sync cyklus dokončí < 5 min pro typický batch (1–5 new recordings).
4. **Privacy:** v prvních 2 týdnech produkčního provozu neúnik Plaud filename nebo project category label do Sentry UI (jinak kill #18 z lifecycle memory, self-hosted Sentry nebo log-only).
5. **Observability:** každý neúspěšný sync triggeruje alert do < 5 min (email nebo push).
6. **UI cold start:** `python -m plaudsync ui` po viditelné okno PyWebView ≤ 3 s. Jinak UX degradace → vyšetřit bundle size / startup.
7. **Sync Now latence:** klik na tlačítko → CLI subprocess spuštěný ≤ 2 s (cold Python start je cca 200 ms; 2 s je strop s marginou).
8. **Tray crash recovery:** po Task Scheduler restartu < 90 s od failure (ověřitelné `Get-WinEvent -LogName Microsoft-Windows-TaskScheduler/Operational`).
9. **Notification debounce:** stejný error_kind v 30 min okně jen 1× toast.

## Architectural decisions

Rozhodnuty v kolech 1–4 průzkumu, detaily v memory:

- **Methodology:** Plan-and-Execute + TDD integration-first. Viz `project_plaud_dev_workflow.md`. (EDD vrstva pro classifier eliminována v categorization v0.1 — single-layer regex nepotřebuje LLM evals.)
- **Tooling:** VCR.py+pytest-recording pro integration testy, Superpowers plugin pro TDD enforcement. (DeepEval odstraněn s LLM classifier scope cutem.) Viz `project_plaud_tooling.md`.
- **Harness:** BALANCED profile — CLAUDE.md + settings.json (permissions+PostToolUse hook) + 2 skills. Runtime plain Python + Task Scheduler. Viz `project_plaud_harness.md`.
- **Lifecycle coverage:** `/review` + `/security-review` + bandit před commitem/mergem; Loguru + Sentry (scrubbed) pro observability. Viz `project_plaud_lifecycle.md`.
- **UI architektura (2026-04-24 pivot, detailed 2026-04-25):** CLI + GUI pattern. CLI (`python -m plaudsync`) zůstává Task Scheduler entry point a headless executor. GUI (`python -m plaudsync ui`) = on-demand FastAPI server (localhost) + React SPA (Vite build bundled) + PyWebView wrapper. GUI čte SQLite delta state read-only pro historii, edituje YAML config pro Settings, spouští CLI jako subprocess pro Sync Now. **Žádný daemon, žádný REST pro external.** Detaily: [docs/superpowers/specs/2026-04-25-ui-architecture-design.md](docs/superpowers/specs/2026-04-25-ui-architecture-design.md).
- **Auth vrstva (2026-04-24):** manual token paste do `.env` + pre-flight + reactive 401 handling. Detaily: [docs/superpowers/specs/2026-04-24-plaud-auth-design.md](docs/superpowers/specs/2026-04-24-plaud-auth-design.md).
- **Categorization (2026-04-25 v0.2):** single-layer regex, ne waterfall. Detaily: [docs/superpowers/specs/2026-04-25-categorization-design.md](docs/superpowers/specs/2026-04-25-categorization-design.md).
- **Sync core (2026-04-25 v0.2):** per-project absolutní cesty, žádný společný kořen. YAML config v `${PLAUDSYNC_STATE_ROOT}/config.yaml`. Detaily: [docs/superpowers/specs/2026-04-25-sync-core-design.md](docs/superpowers/specs/2026-04-25-sync-core-design.md).
- **Tray runtime (2026-04-26 pivot):** pystray + threading.Thread scheduler, in-process sync engine, Task Scheduler degradován na At-log-on launcher s restart-on-failure. Detaily: [docs/superpowers/specs/2026-04-26-tray-design.md](docs/superpowers/specs/2026-04-26-tray-design.md).

## Kill criteria (summary — fully detailed v memory files)

18 pre-registered kill criteria napříč vrstvami. **Nejpravděpodobnější first triggers:**

- `#18` Sentry scrubbing selhává (file paths/labels unscrubbed) — recording-processing tool má privacy risk.
- `#3` SPEC.md bez updatu > 4 týdny — lightweight anchor dies pattern.
- `#5` Regex coverage rate < 90 % na sliding 30-day window — revize title formátu / druhá vrstva (kalendář / LLM, dle preference v té době).
- `H-13` Task Scheduler miss rate > 5 % nebo laptop-off sync need — migrace na Routines.

**Poznámka k UI pivotu (2026-04-24):** nová UI vrstva (FastAPI + React + PyWebView) zavádí nové failure modes (WebView2 kompatibilita, React bundle size, PyWebView lifecycle bugs, frontend build pipeline stability). UI-specific kill criteria jsou zatím ve fázi **watch items W-U1 až W-U5** v [DEV_LOG.md](DEV_LOG.md) sekci "UI layer watch". Formalizace do tohoto 18-item seznamu proběhne při prvním triggeru watch itemu nebo před zahájením UI implementace po per-feature brainstormu (podle toho, co nastane dřív).

## Revision history

- **2026-04-26 (v0.3):** tray pivot — tray + auto-start z `Out of scope` do core scope. `pythonw -m plaudsync tray` jako primary execution model. Task Scheduler trigger z 15-min repetition na At-log-on. Nové deps pystray + Pillow. Detaily: [docs/superpowers/specs/2026-04-26-tray-design.md](docs/superpowers/specs/2026-04-26-tray-design.md).
- **2026-04-25 (v0.2):** per-project absolutní cesty (žádný společný kořen). Env var `PLAUDSYNC_LOCAL_ROOT` → `PLAUDSYNC_STATE_ROOT` (jen state, ne recordings). Cílová struktura per-project z `${PLAUDSYNC_STATE_ROOT}/config.yaml`. Single-layer regex klasifikace (M365/LLM waterfall vyřazen). Success criterion #2 z "LLM accuracy" na "regex coverage rate". Anthropic + M365 odstraněny z paid deps. Cascade z categorization v0.2 + sync-core v0.2 + ui-architecture v0.2 + .env.example update.
- **2026-04-24 (v0.1):** SPEC pivot — UI přesunuto z out-of-scope do core scope. MVP A (Dashboard + Sync Now + Settings). Stack FastAPI + React + PyWebView, on-demand lifecycle. Detaily brainstorm procesu v `DEV_LOG.md` záznam "SPEC pivot". Auth vrstva spec zapsán do `docs/superpowers/specs/2026-04-24-plaud-auth-design.md`.
- **2026-04-24 (v0):** v0 draft, založeno po průzkumech kol 1–4.
