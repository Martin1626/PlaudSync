# PlaudSync — Specification

> **Status:** draft v0.1 (2026-04-24, post UI scope pivot). One-page anchor artifact per průzkum kolo 1.
> Actualizuj při každém scope pivotu. `git log SPEC.md` nepohnutý > 4 týdny = kill criterion trigger (viz memory `project_plaud_dev_workflow.md` #3).

## Problem

Plaud AI nahrávky se nesynchronizují automaticky s lokální stanicí ani s projektovou strukturou v M365. Manuální stahování a třídění je časově náročné a nespolehlivé — nahrávky mizí nebo končí na špatném místě. Potřebujeme periodický proces, který: (a) stáhne nové recordings z Plaud cloudu, (b) klasifikuje je do projektů podle waterfallu M365 membership → regex → LLM fallback, (c) uloží je do deterministické struktury na disku.

## Scope (v0)

### Sync engine (beze změny od v0 draftu)

- Pull new recordings from Plaud API od posledního úspěšného sync (incremental).
- Uložit originální audio + transcript (pokud Plaud poskytuje) na lokální disk.
- Kategorizace každé nahrávky do jednoho projektu (single-label classification):
  - **1. vrstva:** mapování podle M365 Graph membership (účastníci meeting → projektová skupina).
  - **2. vrstva:** regex na title / transcript excerpt (keyword → project).
  - **3. vrstva (fallback):** LLM classifier (Anthropic API) s golden-set-evaluated promptem.
- Cílová struktura: `{LOCAL_ROOT}/{project_name}/{YYYY-MM-DD}_{title_slug}.{ext}`.
- CLI entry point (`python -m plaudsync`) pro Task Scheduler headless běh.
- Provoz: periodic hourly run via Windows Task Scheduler.
- Observability: Loguru rotating file log + Sentry error alerting (scrubbed).

### UI vrstva (přidáno 2026-04-24 pivot)

- GUI entry point (`python -m plaudsync ui`), on-demand launch, lifecycle: open → interact → exit při zavření okna (žádný tray, žádný auto-start v v0).
- Stack: FastAPI (localhost, random free port) + React/TypeScript/Tailwind (bundled static build z Vite) + PyWebView wrapper (Win11 WebView2).
- **Screen 1 — Settings:** konfigurace per-project routing (cílové cesty na disku, regex pravidla, artifacts whitelist). Edit YAML config souboru.
- **Screen 2 — Dashboard:** seznam posledních N synchronizovaných recordings (čte SQLite delta state read-only) + tlačítko "Sync Now".
- **Sync Now:** spouští CLI jako subprocess (`python -m plaudsync`); UI zobrazí progress + exit status. Concurrent launch ochráněn file lockem.
- **Auth verify endpoint:** `POST /api/auth/verify` volá `PlaudClient.verify()` a vrátí JSON status (pro "Test Plaud connection" button v Settings).

## Out of scope (v0)

- Re-processing existing recordings (jen forward-sync od install).
- Tray icon, auto-start with Windows, live bubble notifications (plánováno v1.1+).
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
- **Licence:** zero license cost — Plaud subscription + Anthropic API + M365 subscription jsou jediné paid deps.
- **Privacy:** Meeting recordings obsahují business content. Sentry `send_default_pii=False` + `before_send` scrubbing MUSÍ být aktivní před production provozem.
- **Solo dev:** single maintainer. Overhead metodiky musí být proporční scope.
- **Sync idempotence:** CLI sync proces musí být idempotentní proti concurrent launch (Task Scheduler ↔ manual Sync Now race). File lock + SQLite WAL mode.
- **LoC budget:**
  - Python backend 1500–3000 LoC (Plaud client, classifier, sync engine, FastAPI endpoints).
  - React/TypeScript frontend 500–1000 LoC (2 screens, MVP scope).
  - Spec Kit pivot trigger = Python > 3000 LoC (frontend se do limitu nepočítá — má vlastní sizing dynamiku).

## Success criteria

1. **Sync reliability:** hourly Task Scheduler miss rate ≤ 5 % / měsíc (jinak kill #5, přechod na Routines).
2. **Classification accuracy:** LLM classifier ≥ 70 % accuracy na golden setu (jinak kill #5 z tooling memory, redesign classifier).
3. **Latency:** jeden sync cyklus dokončí < 5 min pro typický batch (1–5 new recordings).
4. **Privacy:** v prvních 2 týdnech produkčního provozu neúnik Plaud filename nebo project category label do Sentry UI (jinak kill #18 z lifecycle memory, self-hosted Sentry nebo log-only).
5. **Observability:** každý neúspěšný sync triggeruje alert do < 5 min (email nebo push).
6. **UI cold start:** `python -m plaudsync ui` po viditelné okno PyWebView ≤ 3 s. Jinak UX degradace → vyšetřit bundle size / startup.
7. **Sync Now latence:** klik na tlačítko → CLI subprocess spuštěný ≤ 2 s (cold Python start je cca 200 ms; 2 s je strop s marginou).

## Architectural decisions

Rozhodnuty v kolech 1–4 průzkumu, detaily v memory:

- **Methodology:** Plan-and-Execute + TDD integration-first + EDD (classifier layer). Viz `project_plaud_dev_workflow.md`.
- **Tooling:** VCR.py+pytest-recording pro integration testy, DeepEval (lightweight) pro classifier evals, Superpowers plugin pro TDD enforcement. Viz `project_plaud_tooling.md`.
- **Harness:** BALANCED profile — CLAUDE.md + settings.json (permissions+PostToolUse hook) + 2 skills. Runtime plain Python + Task Scheduler. Viz `project_plaud_harness.md`.
- **Lifecycle coverage:** `/review` + `/security-review` + bandit před commitem/mergem; Loguru + Sentry (scrubbed) pro observability. Viz `project_plaud_lifecycle.md`.
- **UI architektura (2026-04-24 pivot):** CLI + GUI pattern. CLI (`python -m plaudsync`) zůstává Task Scheduler entry point a headless executor. GUI (`python -m plaudsync ui`) = on-demand FastAPI server (localhost) + React SPA (Vite build bundled) + PyWebView wrapper. GUI čte SQLite delta state read-only pro historii, edituje YAML config pro Settings, spouští CLI jako subprocess pro Sync Now. **Žádný daemon, žádný REST pro external.** Detaily per UI screen / per backend endpoint přijdou v dalších brainstorm cyklech — každý subsystém = vlastní spec dokument v `docs/superpowers/specs/`.
- **Auth vrstva (2026-04-24):** manual token paste do `.env` + pre-flight + reactive 401 handling. Detaily: [docs/superpowers/specs/2026-04-24-plaud-auth-design.md](docs/superpowers/specs/2026-04-24-plaud-auth-design.md).

## Kill criteria (summary — fully detailed v memory files)

18 pre-registered kill criteria napříč vrstvami. **Nejpravděpodobnější first triggers:**

- `#18` Sentry scrubbing selhává (file paths/labels unscrubbed) — recording-processing tool má privacy risk.
- `#3` SPEC.md bez updatu > 4 týdny — lightweight anchor dies pattern.
- `#5` Task Scheduler miss rate > 5 % nebo laptop-off sync need — migrace na Routines.

**Poznámka k UI pivotu (2026-04-24):** nová UI vrstva (FastAPI + React + PyWebView) zavádí nové failure modes (WebView2 kompatibilita, React bundle size, PyWebView lifecycle bugs, frontend build pipeline stability). UI-specific kill criteria jsou zatím ve fázi **watch items W-U1 až W-U5** v [DEV_LOG.md](DEV_LOG.md) sekci "UI layer watch". Formalizace do tohoto 18-item seznamu proběhne při prvním triggeru watch itemu nebo před zahájením UI implementace po per-feature brainstormu (podle toho, co nastane dřív).

## Revision history

- **2026-04-24 (v0.1):** SPEC pivot — UI přesunuto z out-of-scope do core scope. MVP A (Dashboard + Sync Now + Settings). Stack FastAPI + React + PyWebView, on-demand lifecycle. Detaily brainstorm procesu v `DEV_LOG.md` záznam "SPEC pivot". Auth vrstva spec zapsán do `docs/superpowers/specs/2026-04-24-plaud-auth-design.md`.
- **2026-04-24 (v0):** v0 draft, založeno po průzkumech kol 1–4.
