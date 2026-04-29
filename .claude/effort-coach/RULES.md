# Effort Coach — Rules

Pravidla pro volbu modelu × effort × kontext v Claude Code (Opus 4.7, Max plán).
Tato pravidla **doporučí** Effort Coach hook při klasifikaci promptu.
Ty (Claude i uživatel) je můžeš ignorovat, pokud kontext řekne jinak.

## Decision tree

```
PROMPT příchází
    │
    ├── Explicit /effort nebo /model už v promptu?
    │      → respect user choice, nedávej hint
    │
    ├── Obsahuje signály "performance / security / migration / race / deadlock"?
    │      → keep default xhigh, nedávej hint (problem může být subtle)
    │
    ├── Obsahuje "architect / design alternatives / deep dive / ADR"?
    │      → suggest /effort max (frontier reasoning)
    │
    ├── Obsahuje "typo / rename / one-line / drobnost / fix typo / remove unused"?
    │      → suggest /effort medium (~33-50% úspora)
    │
    ├── Krátký prompt (< 80 znaků), bez code fence, žádný file extension?
    │      → suggest /effort medium (heuristika single-sentence trivia)
    │
    └── Žádný match → default xhigh, žádný hint
```

## Cheat sheet (z round 2 ADR)

| Situace | Model + effort | Důvod |
|---------|----------------|-------|
| **Default** | Opus 4.7 + `xhigh` | CC default, baseline |
| **Typický kód** (refaktor, feature s jasnou spec) | Opus 4.7 + `high` | 33% úspora vs xhigh, -5-6% perf |
| **Trivial** (typo, rename, 1-line, sumarizace) | Opus 4.7 + `medium` | Velká úspora; rychlost nad kvalitu |
| **Bulk / template / latency-sensitive** | Sonnet 4.6 + `medium` | Separate ~480h Sonnet bucket na Max plánu |
| **Frontier** (architektura, deep debug, neznámá root cause) | Opus 4.7 + `max` | ~10× cost vs low; **jen po prokázaném selhání xhigh** |

## Vedlejší pravidla

1. **Subagent off-load** — pro grep, test runs, log čtení, multi-topic research použij `Explore` / `general-purpose` subagenta. Šetří **kontext hlavního vlákna** (ne weekly cap — subagenti drainují cap stejně).
2. **Hygiena** — `/clear` před každou novou logickou úlohou. Jedna úloha = jedna conversation.
3. **Peak hours** (13-19 GMT / 14-20 CET) — heavy task defer mimo peak, pokud možno.
4. **1M context** — jen pro full-repo audit / mass-grep / 50+ file refactor. Pro single feature stačí 200k.
5. **Cache TTL** — aktuálně 5 min (silent regrese, viz [GH #46829](https://github.com/anthropics/claude-code/issues/46829)). Pauzy > 5 min = ztráta cache, drahý další turn.

## Co coach NEdělá

- Nevolá Haiku ani jiný API (Max plán nemá API key dimensi).
- Nemění model/effort programmaticky — jen **doporučuje** přes additionalContext.
- Neblokuje user prompt (vždy exit 0).
- Nezná kontext repa nebo file struktury — jen text user promptu.

## Falsifikace pravidel

Po 4 týdnech používání:

1. **Hint compliance rate** — kolik suggested medium/max bylo aktivně aplikováno (lze odvodit z `turns.jsonl` per-turn model+effort vs hint v same conversation).
2. **Retry rate** — % turns, kde po medium/max hint následoval retry s vyšším effort (signal že hint byl příliš agresivní).
3. **Token saving delta** — porovnat avg input+output tokens na "hint=medium" turns vs "hint=none" turns.

Konkrétní prahy (z round 3):
- Pravidla validovaná pokud cap saving ≥ 20% AND retry rate ≤ 15%.
- Pravidla revidovat pokud retry > 25% (heuristic je net-negative).

Viz `README_EFFORT_COACH.md` pro analytické skripty.
