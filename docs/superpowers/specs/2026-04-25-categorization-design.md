# PlaudSync categorization — design spec

> **Status:** v0.2 (2026-04-25). v0.1 → v0.2 změna: per-project absolutní cesty (žádný společný kořen). Path resolution opouští categorization vrstvu a stěhuje se do `path_resolver.py` v sync-core specu. `ClassificationResult` zúžen, `classify()` ztrácí `plaud_folder` parametr.
> **Scope:** auto-kategorizace Plaud nahrávek do projektových labelů (čistá title→project funkce). **Resolve absolutní cílové cesty je v sync-core spec, modul `path_resolver.py`.**
> **Preceded by:** [SPEC.md](../../../SPEC.md), [DEV_LOG.md](../../../DEV_LOG.md), memory `project_plaud_categorization.md` (post-průzkum 2026-04-24, **superseded touto feature**), [2026-04-25-sync-core-design.md](2026-04-25-sync-core-design.md) (path_resolver + config schema).
> **Next step:** `writing-plans` skill → implementation plan → TDD unit-first implementace.

## Problem

PlaudSync potřebuje rozhodnout, do **kterého projektu** patří každá stažená nahrávka — pure title→project klasifikace. Memory záznam z 2026-04-24 navrhoval tří-vrstvý waterfall (M365 kalendář → regex override → LLM fallback). Tento spec **nahrazuje** ten návrh **single-layer regex** strategií:

1. **Bez M365 kalendáře** — žádný OAuth, žádný msal, žádný Azure App Registration.
2. **Bez LLM** — uživatel nechce platit tokeny pro per-recording klasifikaci.
3. **Pure regex na titulek** — Plaud titulek má dohodnutý formát `(YYYY-)?MM-DD <oddělovač> <Projekt>: <zbytek>`.
4. **Pre-filter na Plaud složky** — sync engine stahuje **jen** nahrávky, které uživatel ručně zařadil do nějaké Plaud složky (Inbox = ignorováno). Plaud složky **neodpovídají 1:1 projektovým složkám** — slouží jen jako sync whitelist.
5. **Soft fallback** — když title nematchne pattern, nebo se title-matched project name nenajde v YAML configu, nahrávka pokračuje do unclassified bucketu (per-Plaud-folder subdivize) bez hard-failu. Path resolution (převod project labelu na absolutní cestu na disku) **není zodpovědnost této vrstvy** — sync-core spec, `path_resolver.py`.

## Scope (v této feature)

- `categorization.py` modul: `classify()` + `ClassificationResult` dataclass + `_TITLE_RE`.
- `observability.py` minor extend: přidat `plaud_folder` do `_REDACTED_KEYS`.
- Repository-wide cleanup mrtvých závislostí: `anthropic`, `msal` z hlavních deps, `deepeval` z dev deps, marker `eval`, adresář `tests/evals/`.
- SPEC.md / CLAUDE.md / DEV_LOG.md / memory aktualizace.
- Unit testy (pure logic, žádné VCR cassetty).

**Path resolution (`_sanitize_folder_name`, `resolve_target_path`, _unmapped fallback) — sync-core spec, `path_resolver.py`.**

## Out of scope

- Plaud client API pro listování nahrávek + folder mapping (sync engine spec, navazující brainstorm).
- SQLite state DB pro update detection a sync diff (sync engine spec).
- Filesystem operations — move / rename / overwrite (sync engine spec).
- Concurrent sync file lock (sync engine spec).
- Plaud folder whitelist UI / config (sync engine spec — buď "any non-Inbox folder", nebo per-folder whitelist v `.env` či YAML).
- Region-specific Plaud endpoint (api-euc1.plaud.ai) — sync engine prerequisite zaznamenaný v DEV_LOG.md po auth feature.
- M365 kalendář integrace (zrušeno — žádný msal, žádné Calendars.Read scope).
- LLM klasifikace, Anthropic/OpenAI SDK, DeepEval evals, golden set.

## Decisions & rationale

Pět klíčových rozhodnutí z brainstorm session 2026-04-25:

### 1. Strategie: **Pure regex na Plaud titulek**

Žádný kalendář, žádný LLM. Uživatel udržuje disciplínu pojmenování v Plaud aplikaci ve formátu `(YYYY-)?MM-DD <Projekt>: <zbytek>` (např. `04-25 ProjektAlfa: Kickoff meeting`). Když title formát dodržuje a `<Projekt>` je definován v YAML configu (mapping `name → absolutní cesta`), nahrávka jde do té cesty. Když ne, fallback do `${unclassified_dir}/...` (path resolver detail, sync-core spec).

**Proč ne kalendář:** Azure App Registration + Calendars.Read v tenantu kvados.cz je risk (kill criterion #3 z původního memory). User také nechce token cost ani extra OAuth complexitu.

**Proč ne LLM:** explicitní user volba — nechce platit za tokeny a nechce LLM jako critical path. Single-layer deterministic regex je předvídatelný, free, fast, debuggable.

**Trade-off:** strategie závisí na uživatelské disciplíně při pojmenování. Categorization kill criterion (sekce níže) měří coverage rate; pokud klesne pod 90 %, je signál revize formátu nebo doplnění další vrstvy.

### 2. Plaud folder filter žije v sync engine, ne v categorization

Categorization vrstva **dostane už předfiltrované** nahrávky — sync engine stahuje pouze ty, které uživatel zařadil do Plaud složky. Categorization je tedy čistá funkce title → project bez business logiky kolem "syncovat či ne".

**Proč:** separace concernů. Sync engine ví o Plaud API a stavech (nová / aktualizovaná / smazaná nahrávka). Categorization ví o titulcích. Smíchat je by vytvořilo coupling, který by ztížil testy obou.

### 3. `classify()` je **deterministický a stateless**

Žádný cache, žádný I/O, žádné HTTP, žádný file lock. Stejný vstup → stejný výstup, vždy.

**Důsledek pro update flow:** když uživatel přejmenuje nahrávku v Plaud (rename `Random memo` → `04-25 ProjektAlfa: Kickoff`), sync engine při dalším běhu zavolá `classify()` znovu, dostane jiný výsledek, porovná s SQLite stavem a fyzicky přesune soubor. Categorization vrstva o tom neví — sync engine řeší state diff.

**Proč:** idempotence je jediná vlastnost, která dělá sync update flow trivializovatelný. Když by classify() měl vnitřní stav, update detekce by byla křehká.

### 4. Sentry audit přes tag, ne přes message

Sync engine, který volá classify(), je povinen po každém volání nastavit `sentry_sdk.set_tag("classification_status", result.status)` — hodnoty jen `"matched"` nebo `"unclassified"`. **Categorization vrstva sama Sentry nevolá** — jen vrací data.

**Proč:** dodržuje CLAUDE.md "Privacy / observability rules" — žádný business label (project name, plaud_folder) se nesmí dostat do free-text exception messages ani log strings, jen do strukturovaných tagů, které scrubber zachytí. `_REDACTED_KEYS` v `observability.py` musíme rozšířit o `plaud_folder`.

### 5. Soft fallback do unclassified bucketu (per-Plaud-folder subdivize)

Categorization vrstva vrací `ClassificationResult` se status="matched" + project (pokud title parsoval) nebo status="unclassified" + project=None. **Path resolution + fallback logiku** (kam to fyzicky uložit) řeší sync-core `path_resolver.py`. Pro úplnost zde popsaná logika sync-core path resolveru:

- **Title nematchne** (status="unclassified") → `${config.unclassified_dir}/<sanitized_plaud_folder>/<filename>`.
- **Title matchne, project je v `config.projects`** → `${config.projects[name]}/<filename>`.
- **Title matchne, project NENÍ v `config.projects`** (typo / chybějící config entry) → soft fallback `${config.unclassified_dir}/_unmapped_${project}/<filename>`. Loguru warning, sentry tag `error_kind=project_unmapped`.

**Proč ne flat `unclassified/`:** uživatel chce udržet kontext, ze které Plaud složky nahrávka pochází (pro title-no-match) nebo který project label chybí v configu (pro project-not-mapped). Když pak prochází review queue, vidí seskupení podle Plaud workflow nebo podle missing config entries.

**Proč ne hard-fail bez ukládání:** preference fail-soft — je lepší stáhnout do "neřazeno" a logovat, než neřazené nahrávky úplně propást nebo blokovat sync run kvůli typo v configu.

## Components

```
src/plaudsync/
├── categorization.py    [NEW, ~50–70 LoC]
│   ├── _TITLE_RE: re.Pattern                          # zkompilovaný regex
│   ├── @dataclass(frozen=True) ClassificationResult
│   │     ├── status: Literal["matched", "unclassified"]
│   │     ├── project: str | None
│   │     └── matched_date: date | None
│   └── classify(title, created_at) -> ClassificationResult
└── observability.py     [TINY MODIFY, ~1 LoC]
    └── _REDACTED_KEYS: přidat "plaud_folder"
```

`_sanitize_folder_name` + `resolve_target_path` — sync-core, `path_resolver.py`.

### Public API

```python
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

@dataclass(frozen=True)
class ClassificationResult:
    """Výstup categorization vrstvy. Immutable — sync engine porovnává hodnoty."""
    status: Literal["matched", "unclassified"]
    project: str | None          # set iff status=="matched"; klíč do config.projects
    matched_date: date | None    # date sestavený z (year_z_titulku_nebo_metadata, month, day)


def classify(title: str, created_at: datetime) -> ClassificationResult:
    """Klasifikuje nahrávku do projektu podle regex match na title.

    Returns:
        ClassificationResult.status == "matched":
            project = capture group "project" z titulku (raw, bez slug transformace)
            matched_date = date(year, month, day)
                year je z titulku, pokud byl explicitní; jinak created_at.year

        ClassificationResult.status == "unclassified":
            project = None
            matched_date = None

    Raises:
        Nikdy. Všechny error paths vrací unclassified result + Loguru warning.
    """
```

**Note:** `plaud_folder` je input pro `path_resolver.resolve_target_path()`, ne pro categorization. Categorization je čistá title-only funkce. Project-not-in-config detekce + `_unmapped_<project>/` fallback řeší path_resolver (sync-core spec).

### Regex pattern

```python
_TITLE_RE = re.compile(
    r"""^                              # začátek řetězce
        (?:(?P<year>\d{4})-)?          # volitelný rok (4 číslice + pomlčka)
        (?P<month>\d{2})-              # měsíc
        (?P<day>\d{2})                 # den
        [\s\-/]+                       # 1+ oddělovačů: mezera, pomlčka, lomítko
        (?P<project>[\w ]+?)           # projekt: Unicode word chars + mezery, lazy
        \s*:\s*                        # dvojtečka s volitelnými mezerami
        (?P<rest>.+)$                  # zbytek titulku
    """,
    re.VERBOSE | re.UNICODE,
)
```

### Doplnění roku

```
match["year"] is None
  → year = created_at.year                                  # implicit z metadata
match["year"] is not None and int(match["year"]) == created_at.year
  → year = int(match["year"])                               # konzistentní
match["year"] is not None and int(match["year"]) != created_at.year
  → year = int(match["year"])                               # title vyhrává
  → logger.warning(...)                                     # log mismatch
```

Title-explicit rok vždy vyhrává nad metadata, protože uživatel může záměrně označit nahrávku starším datem. Mismatch se loguje jako warning pro pozdější audit.

### Validace data

```python
try:
    matched_date = date(year, month, day)
except ValueError:
    return ClassificationResult(status="unclassified", ...)  # 02-30, 04-31 atd.
```

### Sanitizace folder name

`_sanitize_folder_name` přesunuto do **sync-core spec, `path_resolver.py`** — kde se sanitizace skutečně používá. Categorization vrstva neprodukuje žádné path stringy, jen project labely (raw, bez transformace).

## Data flow

### Happy path (matched, project v configu)

```
Sync engine si stáhne metadata recording z Plaud:
  title="04-25 ProjektAlfa: Kickoff meeting"
  created_at=datetime(2026, 4, 25, 13, 0, ...)
  folder_name="Klienti"        # Plaud folder, ne argument categorization

  ↓

result = classify(title, created_at)
  → _TITLE_RE.match() → groups: year=None, month="04", day="25",
                                project="ProjektAlfa", rest="Kickoff meeting"
  → year = created_at.year = 2026
  → matched_date = date(2026, 4, 25)
  → ClassificationResult(
        status="matched",
        project="ProjektAlfa",
        matched_date=date(2026, 4, 25),
    )

  ↓ (path_resolver, sync-core spec)

target_dir = path_resolver.resolve_target_path(result, plaud_folder="Klienti", config=...)
  → result.status="matched" + result.project="ProjektAlfa" v config.projects
  → return Path(config.projects["ProjektAlfa"])
  → e.g. Path("C:/Projects/Alpha/Recordings")

target_path = target_dir / f"{matched_date.isoformat()}_{slug(title)}.mp3"
sentry_sdk.set_tag("classification_status", "matched")
download_to(target_path)
```

### Soft-fallback path (matched, project chybí v configu)

```
title="04-25 ProjektGamma: Notes"   # ProjektGamma nedefinován v config.projects
created_at=datetime(2026, 4, 25, ...)
folder_name="Inbox"

  ↓

result = classify(title, created_at)
  → matched, project="ProjektGamma"

  ↓ (path_resolver)

target_dir = path_resolver.resolve_target_path(result, plaud_folder="Inbox", config=...)
  → "ProjektGamma" not in config.projects
  → logger.bind(project="ProjektGamma").warning("project unmapped — soft fallback")
  → sentry_sdk.set_tag("error_kind", "project_unmapped")
  → return Path(config.unclassified_dir) / "_unmapped_ProjektGamma"

target_path = target_dir / f"{matched_date.isoformat()}_{slug(title)}.mp3"
download_to(target_path)
```

### Unclassified path (title nematchne)

```
title="Random voice memo"
folder_name="Inbox/Misc"

  ↓

result = classify(title, created_at)
  → _TITLE_RE.match() → None
  → ClassificationResult(status="unclassified", project=None, matched_date=None)

  ↓ (path_resolver)

target_dir = path_resolver.resolve_target_path(result, plaud_folder="Inbox/Misc", config=...)
  → status="unclassified"
  → sanitized = _sanitize_folder_name("Inbox/Misc") = "Inbox_Misc"
  → return Path(config.unclassified_dir) / "Inbox_Misc"

sentry_sdk.set_tag("classification_status", "unclassified")
logger.bind(plaud_folder="Inbox/Misc").warning("Recording unclassified")
download_to(target_path)
```

### Update path (rename v Plaud)

```
Sync run #1 (2026-04-25):
  title="Random memo"  → unclassified
  path_resolver → ${unclassified_dir}/Klienti/<filename>

User v Plaud: rename → "04-25 ProjektAlfa: Kickoff"

Sync run #2 (2026-04-26):
  title="04-25 ProjektAlfa: Kickoff"  → matched, project="ProjektAlfa"
  path_resolver → ${config.projects["ProjektAlfa"]}/<filename>
```

Categorization vrstva o move/rename neví — vrací jen project label nebo None. Path resolution + state diff + fyzický move (pokud aktuální v0 implementuje, viz sync-core Decision #5 immutability) řeší sync engine.

## Error handling

Categorization vrstva **nikdy neraisuje exception**. Všechny chybové cesty (regex no-match, nevalidní datum) vrací `ClassificationResult(status="unclassified", ...)`. Důvod: classify() je čistá funkce v hot path sync běhu, exception by sync engine musel ošetřovat per recording — komplexita bez přínosu.

| Vstup | Výstup | Side effect |
|---|---|---|
| Title nematchne pattern | unclassified | žádný |
| Title matchne, ale `date(year, month, day)` vyhodí ValueError | unclassified | `logger.warning("invalid date in title")` |
| Title matchne, ale rok v titulku ≠ `created_at.year` | matched s rokem z titulku | `logger.warning("year mismatch")` |

Folder sanitizace + missing-project-in-config errors → `path_resolver.py` v sync-core specu.

**Sentry signalizace** (zodpovědnost sync engine / path_resolver, ne categorization vrstvy):
- `sentry_sdk.set_tag("classification_status", result.status)` po každém volání classify().
- `sentry_sdk.set_tag("error_kind", "project_unmapped")` v path_resolver pokud `result.project` chybí v configu.
- Žádný `capture_exception` — unclassified ani unmapped není error.

## Testing strategy

Per [CLAUDE.md](../../../CLAUDE.md):
> *"Mock-only unit tests only for pure logic (regex, classification rules)."*

Categorization je přesně tato kategorie — pure regex, žádné HTTP, žádný filesystem, žádný LLM. **Pure unit testy, žádné VCR cassetty, žádný DeepEval, žádný golden set.**

### Test file

`tests/test_categorization.py` (~150 LoC test kódu, parametrizované).

### Test cases (chronologické pořadí pro TDD)

1. **FIRST FAILING TEST** (commit, pak implementace):
   `test_classify_returns_matched_for_canonical_title_with_year`
   - Input: `title="2026-04-25 ProjektAlfa: Kickoff"`, `created_at=datetime(2026,4,25)`.
   - Assert: status="matched", project="ProjektAlfa", matched_date=date(2026,4,25).

2. `test_classify_returns_matched_for_short_date_with_year_from_metadata`
   - Input: `title="04-25 ProjektAlfa: foo"`, `created_at=datetime(2026,4,25)`.
   - Assert: matched_date.year == 2026.

3. `test_classify_supports_separator_variants` (parametrize)
   - Inputs: `"04-25 X: y"`, `"04-25 - X: y"`, `"04-25 / X: y"`, `"04-25  - / X: y"`.
   - Assert: všechny matched, project="X".

4. `test_classify_project_name_with_spaces_and_unicode`
   - Input: `"04-25 Projekt Česká Alfa: foo"`.
   - Assert: project="Projekt Česká Alfa".

5. `test_classify_lazy_match_to_first_colon`
   - Input: `"04-25 ProjektAlfa: kickoff: agenda"`.
   - Assert: project="ProjektAlfa" (ne "ProjektAlfa: kickoff").

6. `test_classify_year_in_title_overrides_created_at_year`
   - Input: `title="2025-04-25 X: y"`, `created_at=datetime(2026,4,25)`.
   - Assert: matched_date.year == 2025, log warning fired (caplog).

7. `test_classify_no_match_returns_unclassified`
   - Input: `title="Random memo"`.
   - Assert: status="unclassified", project=None, matched_date=None.

8. `test_classify_invalid_date_returns_unclassified`
   - Input: `title="02-30 X: y"` (únor 30. neexistuje).
   - Assert: status="unclassified".

9. `test_classify_missing_colon_returns_unclassified`
   - Input: `title="04-25 ProjektAlfa kickoff"` (chybí dvojtečka).
   - Assert: status="unclassified".

10. `test_classification_result_is_frozen_dataclass`
    - Instantiate ClassificationResult, attempt to mutate `.project`.
    - Assert: `dataclasses.FrozenInstanceError` raised.

`_sanitize_folder_name` testy přesunuty do **sync-core spec** (`tests/test_path_resolver.py`).

### Test infra delta

- **Smazat:** `tests/evals/golden_set.yaml` + celý adresář `tests/evals/`.
- **Smazat:** `eval` marker v `[tool.pytest.ini_options].markers` v `pyproject.toml`.
- **Beze změny:** `tests/conftest.py` (pure unit tests nepotřebují VCR fixtures).

## Repository-wide cleanup

Cleanup mrtvých závislostí + dokumentačních artefaktů držený v jednom commit chainu pro pochopitelnost diffu (ne v separátních PR).

| Soubor | Akce |
|---|---|
| `pyproject.toml` | Odstranit `anthropic>=0.40` a `msal>=1.30` z `dependencies`. Odstranit `deepeval>=1.5` z `dev`. Odstranit marker `eval` v `[tool.pytest.ini_options]`. |
| `tests/evals/` | Smazat celý adresář (`golden_set.yaml`, případný `__init__.py`). |
| `SPEC.md` | Sekce **Sync engine** kategorizace: přepsat "M365 → regex → LLM waterfall" na "single-layer regex na title". **Constraints**: odstranit "Anthropic API jako paid dep". **Success criteria #2**: nahradit "LLM accuracy ≥ 70 %" za "regex match coverage ≥ 90 % stažených recordings za měsíc". **Architectural decisions**: odstranit zmínku EDD a DeepEval. **Kill criteria**: hlavní seznam zůstává 18 — z původního #5 (kolo 1 — LLM classifier accuracy) se stává nový "regex coverage rate < 90 %"; číslo #5 zachováno pro stable references. |
| `CLAUDE.md` | Sekce **Implementation phase**: odstranit řádek "LLM classifier changes → run DeepEval against `tests/evals/golden_set.yaml`. Accuracy drop > 5 p.p. ...". Ostatní pravidla (TDD, integration-first, VCR cassetty pro Plaud/M365 — i když M365 už nepoužíváme, pravidlo zachovat pro budoucí HTTP integrace) zůstávají. |
| `DEV_LOG.md` | Přidat záznam `## 2026-04-25 — Categorization simplification: regex-only`. |
| Memory `project_plaud_categorization.md` | Přepsat: tří-vrstvý waterfall → single-layer regex; akce #0/#1/#2 odstranit; LoC odhad ~600 → ~150; kill criteria revise (jen "regex coverage rate < 90 %"). |
| `.env.example` | Beze změny (žádné nové env vars). |

### Kill criteria — co padá, co zůstává, co vzniká

**V hlavním seznamu SPEC.md (18 kill criteria napříč vrstvami):**

| # | Original | Status |
|---|---|---|
| #5 (kolo 1) | LLM classifier accuracy < 70 % na golden setu @ > 2 týdny iterací | **Swap** — nahrazuje se novým "regex coverage rate < 90 %", číslo #5 zachováno pro stable references |

Hlavní seznam tedy zůstává **18 kill criteria**, jen #5 dostane novou definici.

**V memory `project_plaud_categorization.md`** (memory-only kill criteria, mimo hlavní SPEC.md seznam):

| # | Original | Status |
|---|---|---|
| 1 | Calendar match coverage < 50 % | **Padá** (žádný kalendář) |
| 2 | LLM accuracy < 70 % na 20-record validation setu | **Padá** (žádný LLM, navíc duplicitní s SPEC.md #5) |
| 3 | Tenant blokuje device code flow / app registration | **Padá** (žádný M365) |
| 4 | LLM cost > $5/měsíc 3× za sebou | **Padá** (žádný LLM) |
| 5 | Calendar events s identifikovatelným project signal < 60 % | **Padá** (žádný kalendář) |

Memory záznam se přepíše: 5 původních memory kill criteria pryč, ponechá se jen reference na nové SPEC.md #5.

**Nové categorization kill criterion (definice pro SPEC.md #5):**

> **#5 — Regex coverage rate:** za sliding window 30 dní < 90 % stažených recordings projde matched (zbylých > 10 % končí v `_unclassified/`). Trigger: revize formátu (možná datum-only fallback?), nebo přidání druhé vrstvy (zpět ke kalendáři / LLM, dle preference v té době).

## TOS / privacy / security considerations

- **Žádné nové externí API** — categorization vrstva neopouští proces. Žádný TOS impact.
- **Žádné nové sekrety** — categorization nepotřebuje token, key, ani credential.
- **Privacy** — `_REDACTED_KEYS` v `observability.py` rozšířeno o `plaud_folder`. Tím Sentry scrubber zachytí folder name v tags/contexts. Sync engine je povinen předávat `plaud_folder` jen přes `set_tag` / `logger.bind`, nikdy jako f-string v message (per CLAUDE.md "Privacy / observability rules", platí stejně jako pro `project_name`).
- **Bandit** — pure regex + dataclass + path string composition. Žádný subprocess, žádný `shell=True`, žádný `eval/exec`. Bandit clean očekáván.

## Acceptance criteria

Feature je hotová pokud:

1. `pytest tests/test_categorization.py -v` zelený, všech 10 test cases.
2. `pytest tests/` celý zelený (auth + categorization + smoke).
3. `bandit -r src/plaudsync/categorization.py` bez findings.
4. `pyproject.toml` neobsahuje `anthropic`, `msal`, `deepeval`, ani marker `eval`.
5. Adresář `tests/evals/` neexistuje.
6. `SPEC.md`, `CLAUDE.md`, `DEV_LOG.md`, memory `project_plaud_categorization.md` aktualizované per "Repository-wide cleanup" tabulku výše.
7. Manuální smoke check: `python -c "from plaudsync.categorization import classify; from datetime import datetime; r = classify('04-25 ProjektAlfa: kickoff', datetime(2026,4,25)); print(r)"` vrátí matched result s `project="ProjektAlfa"` a `matched_date=date(2026,4,25)`.
8. `_REDACTED_KEYS` v `observability.py` obsahuje `"plaud_folder"`.

## Implementation plan

→ `writing-plans` skill (další krok po user approvalu tohoto spec dokumentu).

## Revision history

- **2026-04-25 (v0.2):** per-project absolutní cesty. `target_subdir` field dropped z `ClassificationResult`. `plaud_folder` parametr dropped z `classify()`. `_sanitize_folder_name` přesunuto do sync-core path_resolver. Test count 12 → 10. Path resolution + soft fallback (project not in config → `_unmapped_<project>/`) je sync-core zodpovědnost.
- **2026-04-25 (v0.1):** v0 draft, výstup brainstorm session. Memory `project_plaud_categorization.md` (post-průzkum 2026-04-24) označen jako superseded.
