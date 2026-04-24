# PlaudSync — Specification

> **Status:** draft v0 (2026-04-24). One-page anchor artifact per průzkum kolo 1.
> Actualizuj při každém scope pivotu. `git log SPEC.md` nepohnutý > 4 týdny = kill criterion trigger (viz memory `project_plaud_dev_workflow.md` #3).

## Problem

Plaud AI nahrávky se nesynchronizují automaticky s lokální stanicí ani s projektovou strukturou v M365. Manuální stahování a třídění je časově náročné a nespolehlivé — nahrávky mizí nebo končí na špatném místě. Potřebujeme periodický proces, který: (a) stáhne nové recordings z Plaud cloudu, (b) klasifikuje je do projektů podle waterfallu M365 membership → regex → LLM fallback, (c) uloží je do deterministické struktury na disku.

## Scope (v0)

- Pull new recordings from Plaud API od posledního úspěšného sync (incremental).
- Uložit originální audio + transcript (pokud Plaud poskytuje) na lokální disk.
- Kategorizace každé nahrávky do jednoho projektu (single-label classification):
  - **1. vrstva:** mapování podle M365 Graph membership (účastníci meeting → projektová skupina).
  - **2. vrstva:** regex na title / transcript excerpt (keyword → project).
  - **3. vrstva (fallback):** LLM classifier (Anthropic API) s golden-set-evaluated promptem.
- Cílová struktura: `{LOCAL_ROOT}/{project_name}/{YYYY-MM-DD}_{title_slug}.{ext}`.
- Provoz: periodic hourly run via Windows Task Scheduler.
- Observability: Loguru rotating file log + Sentry error alerting (scrubbed).

## Out of scope (v0)

- Re-processing existing recordings (jen forward-sync od install).
- UI / web dashboard.
- Multi-user nebo team sharing.
- Real-time streaming — periodic pull stačí.
- Transcript summarization or generation (pouze storage, pokud Plaud dodá).
- Mobile nebo non-Windows platforms.

## Constraints

- **Platforma:** Windows 11 Pro dev stanice. Hookování přes Git Bash; PowerShell tool je preview, ne primary dependency.
- **Python:** 3.11+.
- **Licence:** zero license cost — Plaud subscription + Anthropic API + M365 subscription jsou jediné paid deps.
- **Privacy:** Meeting recordings obsahují business content. Sentry `send_default_pii=False` + `before_send` scrubbing MUSÍ být aktivní před production provozem.
- **Solo dev:** single maintainer. Overhead metodiky musí být proporční scope.
- **Skop growth:** odhadnutý na 1500–3000 LoC finální; pokud roste nad 3000 LoC, přehodnoť Spec Kit upgrade (viz workflow memory).

## Success criteria

1. **Sync reliability:** hourly Task Scheduler miss rate ≤ 5 % / měsíc (jinak kill #5, přechod na Routines).
2. **Classification accuracy:** LLM classifier ≥ 70 % accuracy na golden setu (jinak kill #5 z tooling memory, redesign classifier).
3. **Latency:** jeden sync cyklus dokončí < 5 min pro typický batch (1–5 new recordings).
4. **Privacy:** v prvních 2 týdnech produkčního provozu neúnik Plaud filename nebo project category label do Sentry UI (jinak kill #18 z lifecycle memory, self-hosted Sentry nebo log-only).
5. **Observability:** každý neúspěšný sync triggeruje alert do < 5 min (email nebo push).

## Architectural decisions

Rozhodnuty v kolech 1–4 průzkumu, detaily v memory:

- **Methodology:** Plan-and-Execute + TDD integration-first + EDD (classifier layer). Viz `project_plaud_dev_workflow.md`.
- **Tooling:** VCR.py+pytest-recording pro integration testy, DeepEval (lightweight) pro classifier evals, Superpowers plugin pro TDD enforcement. Viz `project_plaud_tooling.md`.
- **Harness:** BALANCED profile — CLAUDE.md + settings.json (permissions+PostToolUse hook) + 2 skills. Runtime plain Python + Task Scheduler. Viz `project_plaud_harness.md`.
- **Lifecycle coverage:** `/review` + `/security-review` + bandit před commitem/mergem; Loguru + Sentry (scrubbed) pro observability. Viz `project_plaud_lifecycle.md`.

## Kill criteria (summary — fully detailed v memory files)

18 pre-registered kill criteria napříč vrstvami. **Nejpravděpodobnější first triggers:**

- `#18` Sentry scrubbing selhává (file paths/labels unscrubbed) — recording-processing tool má privacy risk.
- `#3` SPEC.md bez updatu > 4 týdny — lightweight anchor dies pattern.
- `#5` Task Scheduler miss rate > 5 % nebo laptop-off sync need — migrace na Routines.

## Revision history

- **2026-04-24:** v0 draft, založeno po průzkumech kol 1–4.
