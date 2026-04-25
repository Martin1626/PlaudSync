# PlaudSync — Dev Log

Ruční journal pro tracking kill criteria a non-obvious rozhodnutí. Přidávej odshora (nejnovější nahoru). Formát: `## YYYY-MM-DD — short title` + body.

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
