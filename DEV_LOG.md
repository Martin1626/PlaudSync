# PlaudSync — Dev Log

Ruční journal pro tracking kill criteria a non-obvious rozhodnutí. Přidávej odshora (nejnovější nahoru). Formát: `## YYYY-MM-DD — short title` + body.

---

## 2026-04-24 — Harness bootstrap

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
| 5 | LLM classifier accuracy < 70 % na golden setu @ > 2 týdny iterací | — | not started |

### Kolo 2 (tooling)

| # | Criterion | Last check | Status |
|---|-----------|-----------|--------|
| T-5 | Cassette re-record > 1×/měsíc kvůli nestabilitě | — | not started |
| T-6 | DeepEval dependency conflict s Anthropic/OpenAI SDK | — | not started |
| T-7 | Superpowers context pollution > 30 % nevyužíván @ 3 týdny | — | not started (pending install) |
| T-8 | CI slowdown > 30 s vs baseline @ 1 měsíc | — | not started |

### Kolo 3 (harness)

| # | Criterion | Last check | Status |
|---|-----------|-----------|--------|
| H-9 | Context baseline > 15k tokens na session start @ 1 měsíc | — | not started (pending install) |
| H-10 | PostToolUse hook > 10 s průměrně @ 2 týdny | — | not started |
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
| L-18 | **Sentry scrubbing selhává** (unscrubbed paths/labels v UI) @ 2 týdny | — | not started (pending install) |

**Most likely first triggers** (dle retrospektivy):

1. L-18 (Sentry scrubbing — file-heavy app privacy)
2. #3 (SPEC.md anchor dies pattern)
3. H-13 (Task Scheduler miss rate — Win stanice uptime issues)

---

## Token/context baseline

Zaznamenat po `/plugin install superpowers` + session restart:

- **Před Superpowers:** — TBD
- **Po Superpowers + CLAUDE.md + skills:** — TBD
- **Target:** < 15k tokens (harness kill criterion #H-9)

---

## Correction counter (kolo 1 kill criterion #1)

Po každé task v Claude Code poznamenej: task id, počet mých "no/přepiš/to není to co chci" korekcí.

| Date | Task | Corrections | Notes |
|------|------|-------------|-------|
| — | — | — | — |
