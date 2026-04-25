# Settings screen — design spec (extracted from prototype + review delta)

> **Status:** v0 (2026-04-25). Extracted from validated Claude Design prototype `frontend/PlaudSync UI.html` after review against [UI architecture umbrella spec v0.2](2026-04-25-ui-architecture-design.md), [sync-core spec v0.2](2026-04-25-sync-core-design.md) a [auth design](2026-04-24-plaud-auth-design.md). **Not a brainstorm output** — design rozhodnutí byla učiněna v Claude Design prototype session; tento dokument je extracted contract + review findings + acceptance criteria pro implementaci.
> **Scope:** Settings screen (route `/settings`), one of two MVP screens. Auth token verify + YAML config edit/save + inline parse error display.
> **Preceded by:** UI architecture umbrella v0.2, sync-core v0.2 (`config.py` modul + `Config`/`ConfigParseError`/`ConfigValidationError`), auth design (`PlaudTokenMissing`/`PlaudTokenExpired`), [Dashboard screen spec v0](2026-04-25-dashboard-screen-design.md) (companion), [frontend/PlaudSync UI.html](../../../frontend/PlaudSync%20UI.html) prototype.
> **Next step:** UI backend writing-plans cyklus (po dokončení sync-core impl). Settings frontend writing-plans cyklus (po Dashboard spec + UI backend impl).

## Problem

UI architecture umbrella zafixovala dva endpointy pro Settings: `POST /api/auth/verify` (z auth design) a `GET/PUT /api/config` (raw YAML + parsed + parse errors). Sync-core v0.2 přidala konkrétní YAML schema (`unclassified_dir` + `projects` mapping) s validation rules (absolutní paths, traversal guard, parent must exist) + exit code 7 pro `ConfigValidationError`. Per-screen Settings design byl materializován v Claude Design prototype jako interaktivní `ConnectionPanel` (token masked display + "Otestovat připojení" button) + `ConfigPanel` (YAML editor s line-number gutter + Save/Reload buttons + inline parse error display).

Tento dokument extrahuje implementation contract z prototypu (ne re-design) a identifikuje delta proti specs (gaps, missing edge cases, open implementation questions).

## Scope (tato feature)

- **Component tree** pro Settings route — `<ConnectionPanel>`, `<ConfigPanel>` (s `<YamlEditor>` sub-component containing line-number gutter + textarea + inline error footer).
- **State→UI mapping table** — explicit binding between `ConfigResponse` / `AuthVerifyResponse` Pydantic shapes (UI architecture spec) a vizuální stavy v prototypu.
- **Interaction contract** — verify button click → spinner → toast/banner; save button click → spinner → toast / inline error; reload button → re-fetch + reset local edits.
- **Default empty-config template** — DEFAULT_YAML string z prototypu (komentáře EN+CS, příklady projektů + unclassified_dir s `D:\` placeholder paths).
- **Localization** — prototype je v češtině (per user preference). Implementation MUSÍ použít stejné stringy.

## Out of scope (this screen)

- **Token rotation in-UI** — token žije v `.env` per auth design (Decision #2 — keyring rejected). Settings ho jen masked-displays + ověřuje, nepíše.
- **YAML syntax highlighting** — line numbers + monospace stačí pro MVP. Lightweight syntax HL (Prism.js / highlight.js) by stál ~30 KB minified, nad budget pro 2-screen UI. v1.1+ pokud user feedback.
- **Multi-file config / config validation preview / dry-run sync** — out of MVP.
- **Restore / version history / diff** — out of MVP. User si zazálohuje config.yaml manuálně, pokud chce.
- **Manual file path picker / "Browse" button pro project paths** — YAML edit-only v MVP. Native file picker přes PyWebView API je v1.1+ nice-to-have.
- **Auth verify retry button v error banneru** — banner má action "Otevřít Nastavení" pro Dashboard banner, ale samotný verify retry je už v Settings (klik na Test connection znovu).

## Decisions extracted from prototype

### D1. Layout: ConnectionPanel above ConfigPanel, vertical stack

```
+-----------------------------------------------------+
| <Header> (sticky)                                   |
| Logo · [Přehled] [Nastavení]   SyncStatusBadge      |
+-----------------------------------------------------+
| <BannerStack> (0+ banners — token expired surface)  |
+-----------------------------------------------------+
|                                                     |
|   <ConnectionPanel>  (Plaud token + verify)         |
|                                                     |
|   <ConfigPanel>      (YAML editor + Save/Reload)    |
|                                                     |
+-----------------------------------------------------+
| <ToastContainer> (bottom-right, fixed)              |
+-----------------------------------------------------+
```

`max-w-6xl mx-auto px-6` parent (z `<AppShell>`). Vertical gap `space-y-5` mezi panely. Tab "Nastavení" v `<Header>` má active state (underscore + `bg-gray-100`).

### D2. ConnectionPanel — token display + verify

**Section header** (`p-5 border-b border-gray-100`):
- Title: `"Připojení k Plaud"` (`text-sm font-semibold`).
- Subtitle: `"Token se načítá ze souboru .env (PLAUD_API_TOKEN). Z UI se needituje."` (`text-[13px] text-gray-500`).

**Body** (`p-5 space-y-4`):
- **Label:** `"Plaud API token"` (`text-xs font-medium text-gray-600 mb-1.5`).
- **Token display field** (read-only, masked):
  - Lock icon (gray) + masked string `"eyJhbGci•••••••••••••••AbcD9"` (font-mono).
  - Right-aligned chip `"z .env"` (light gray, smallest).
  - Container: `bg-gray-50 border-gray-200 rounded-md px-3 py-2`.
  - **Real implementation note:** masked string je rendered backend-side. UI architecture spec D5/B5 explicitly forbids exposing token value via API. Backend computes mask (`first_8 + "•" * 15 + last_4` heuristic) a vrací jako `masked_token: str` v `AuthVerifyResponse` nebo separately v `GET /api/config` response. Choice between options tracked v Gap 3 below.
- **Verify button** (right-aligned):
  - Idle: outlined gray button "Otestovat připojení" + check icon.
  - Verifying: same button disabled with spinner icon (`animate-spin`).
  - Click handler: triggers `POST /api/auth/verify` mutation.

**Footer hint** (`bg-gray-50 border-gray-200 rounded-md p-3 text-[13px]`):
> "Aktualizace tokenu: otevři `app.plaud.ai` v prohlížeči, v DevTools spusť `localStorage.tokenstr` a hodnotu vlož do souboru `.env` pod klíč `PLAUD_API_TOKEN`."

### D3. Verify button state machine

| State | Visual | Server response |
|---|---|---|
| **idle** | "Otestovat připojení" + check icon, enabled | — |
| **verifying** | Same label, disabled, spinner replaces check icon | `POST /api/auth/verify` in flight |
| **post-success** | Returns to idle; toast "Token ověřen" appears bottom-right (4 s) | 200 `{ok: true}` |
| **post-error (expired)** | Returns to idle; banner "Token vypršel" pushed to `<BannerStack>` (persistent) + toast "Ověření tokenu selhalo" (transient) | 200 `{ok: false, reason: "PlaudTokenExpired", message: ...}` |
| **post-error (missing)** | Returns to idle; banner "Token chybí" pushed | 200 `{ok: false, reason: "PlaudTokenMissing", message: ...}` |
| **post-error (5xx / network)** | Returns to idle; toast "Ověření tokenu selhalo — zkontroluj síť" | HTTP 5xx or fetch error |

**Banner action labels** (per Dashboard spec D6 + auth flow):
- `PlaudTokenExpired` → action label `"Aktualizovat token v .env"` — click no-op v Settings (user už v Settings je); na Dashboard click navigates to `/settings`. v Settings panelu banner je redundantní → derive: pokud `route === "settings"` skryj action button, banner zůstává info-only.
- `PlaudTokenMissing` → action label `"Zobrazit setup návod"` — click na footer hint v same panel (scroll-to + highlight). MVP: no-op, hint je already visible.

### D4. ConfigPanel — YAML editor + Save/Reload

**Section header** (`p-5 border-b border-gray-100 flex items-start justify-between gap-4`):
- Title: `"Konfigurace"`.
- Subtitle: `"YAML soubor v $PLAUDSYNC_STATE_ROOT\config.yaml."` (mono path).

**Body** (`p-5 space-y-4`):
- `<YamlEditor>` (height 400 px, full-width).
- **Bottom action row** (`flex items-center gap-3`):
  - **Save button** (primary blue, with disk icon): "Uložit". Spinner replaces disk icon during `PUT /api/config`.
  - **Reload button** (outlined gray, with circular-arrow icon): "Načíst znovu". Re-fetches `GET /api/config`.
  - **Right-aligned line counter:** `"{N} řádků"` (`ml-auto text-xs text-gray-400 font-mono`). Helper info-only.

### D5. YamlEditor — line numbers gutter + textarea + inline error

**Layout:**

```
+----+----------------------------------------------+
|  1 |# PlaudSync configuration — spec v0.2         |
|  2 |#                                             |
|  3 |# Categorization is single-layer regex...     |
|... |...                                           |
| 12 |unclassified_dir: D:\Recordings\Unclassified  |
|... |...                                           |
+----+----------------------------------------------+
| Řádek 12: invalidní cesta (musí být absolutní)    |  ← inline error footer
+---------------------------------------------------+
```

**Implementation contract:**
- **Container:** `rounded-md border bg-white overflow-hidden`. Border red (`border-red-300`) when error present, else gray (`border-gray-200`).
- **Line numbers gutter:**
  - Width 48 px, `bg-gray-50 border-r border-gray-100 text-right pr-3 pl-3 py-3 select-none`.
  - JetBrains Mono 13 px / 20 px line-height (must exactly match textarea metrics).
  - Per-line `<div>`. Default text `text-gray-400`. Error line: `text-red-600 font-semibold bg-red-50 -mx-3 px-3` (full-width pink stripe extends to gutter edges).
  - **`overflow-hidden`** — gutter scrolls in sync with textarea (see scroll handler).
- **Textarea:**
  - Class `yaml-textarea flex-1 py-3 px-3 outline-none resize-none text-gray-800 bg-white`.
  - Same JetBrains Mono 13 px / 20 px / `tab-size: 2`.
  - `spellCheck={false}`, `caret-color: #2563eb` (blue), selection `#dbeafe`.
  - Height 400 px (fixed; no auto-grow v MVP).
- **Scroll sync** (`onScroll`): `lineNumsRef.current.scrollTop = e.target.scrollTop` — gutter follows textarea scroll position.
- **Inline error footer** (when `error !== null`):
  - `border-t border-red-200 bg-red-50 px-4 py-2 text-[13px] text-red-800`.
  - Icon (red ⓘ-style circle) + `"Řádek {line}: {message}"` (line number monospace bold).

### D6. Save button state machine

| State | Visual | Action |
|---|---|---|
| **idle** | "Uložit" + disk icon, enabled, primary blue | Click → `PUT /api/config` mutation |
| **saving** | Same label, disabled, spinner icon | mutation in flight |
| **post-success (200)** | Returns to idle; toast "Konfigurace uložena"; inline error cleared | 200 `{ok: true, parsed: {...}}` |
| **post-error (422)** | Returns to idle; inline error footer in `<YamlEditor>` shows first error; toast "Konfigurace je neplatná — řádek N" | 422 `{ok: false, errors: [{line, message}, ...]}` |
| **post-error (5xx)** | Returns to idle; toast "Uložení selhalo — zkontroluj log" | HTTP 5xx |

**Always-enabled rule:** prototype enabluje Save button bez ohledu na "dirty" stav (textarea unchanged). Akceptováno v MVP — user může uložit identický YAML pro forced re-validation. Tracked v Gap 6 below pokud chceme později přidat dirty detection.

### D7. Reload button behavior

Click handler v prototypu: `setYaml(DEFAULT_YAML); setYamlError(null); pushToast("success", "Konfigurace načtena znovu")`.

**Real implementation contract:**
- Click → `useConfig.refetch()` → `GET /api/config` → updates `yaml` state from response.
- **No confirm dialog** if user has unsaved local edits. Prototype overwrites silently.
- Toast: `"Konfigurace načtena znovu"`.
- Inline error cleared (server YAML is authoritative).

**Gap 4 below** dokumentuje destructive-overwrite risk pokud user měl nesaved edits — defer rozhodnutí (confirm vs silent) na implementation cycle.

### D8. DEFAULT_YAML template (empty-config seed)

Backend `GET /api/config` na fresh install returns this string jako `raw_yaml`. Sync-core spec v0.2 garantuje že `${STATE_ROOT}/config.yaml` musí existovat (exit 7 jinak); first-run setup tedy potřebuje seed:

```yaml
# PlaudSync configuration — spec v0.2 (per-project absolute paths)
#
# Categorization is single-layer regex on the recording title. Title format:
#     (YYYY-)?MM-DD <separator> <Project>: <rest>
# Example titles:
#     04-25 ProjektAlfa: Kickoff
#     2026-04-25 KlientBeta: status update
# The captured "Project" name must match a key in 'projects' below; otherwise
# the recording lands under unclassified_dir/_unmapped_<project>/.

# Cílová absolutní cesta pro nahrávky bez project labelu (title nematchne)
# nebo s project labelem, který není v 'projects' (soft fallback).
unclassified_dir: D:\Recordings\Unclassified

# Per-project absolutní cesty. Každý projekt může být na jiném drive — žádný
# společný kořen. Klíč musí přesně odpovídat captured "Project" v titulku
# (case-sensitive, Unicode word + space allowed).
projects:
  ProjektAlfa: C:\Projects\Alpha\Recordings
  KlientBeta: D:\Clients\Beta\Audio
  Interní: E:\Work\Interni
```

**Open question:** generates seed v sync-core `config.load_config()` (raise on missing) nebo v UI backend `GET /api/config` (returns seed if file missing)? Tracked v Gap 7.

### D9. Banner: token-expired surface in Settings

Per Dashboard spec D6, banner derivation rules:
- Banner pushed by `<ConnectionPanel>` verify mutation `onError`.
- Banner persists across route navigation (lives v `<AppShell>` `<BannerStack>`).
- Dismissible via X — in-session memory only (per Dashboard Gap 7).
- Visibility on `route === "settings"` is redundantní (user už opravuje token), ale banner stays — symmetry s Dashboard surface, žádné special-case hide.

### D10. Localization strings (lock contract)

Implementation MUSÍ použít:

| String | Use |
|---|---|
| `"Připojení k Plaud"` | ConnectionPanel title |
| `"Plaud API token"` | label |
| `"z .env"` | source chip |
| `"Otestovat připojení"` | verify button |
| `"Token ověřen"` | success toast |
| `"Ověření tokenu selhalo"` | error toast |
| `"Token vypršel"` | banner title (PlaudTokenExpired) |
| `"Token chybí"` | banner title (PlaudTokenMissing) |
| `"Zkopíruj znovu localStorage.tokenstr z app.plaud.ai do souboru .env."` | banner body (expired) |
| `"Konfigurace"` | ConfigPanel title |
| `"Uložit"` | save button |
| `"Načíst znovu"` | reload button |
| `"Konfigurace uložena"` | save success toast |
| `"Konfigurace je neplatná — řádek N"` | save 422 toast |
| `"Konfigurace načtena znovu"` | reload toast |
| `"Řádek {N}: {message}"` | inline error line |
| `"{N} řádků"` | line counter |

## Components

```
frontend/src/
├── pages/
│   └── Settings.tsx                        [<ConnectionPanel> + <ConfigPanel>]
│       ├── ConnectionPanel.tsx             [token display + verify button]
│       ├── ConfigPanel.tsx                 [editor + Save/Reload]
│       └── YamlEditor.tsx                  [gutter + textarea + inline error]
├── api/
│   ├── types.ts                            [ConfigResponse, ConfigSaveErrors, AuthVerifyResponse]
│   └── hooks.ts                            [useConfig, useSaveConfig, useVerifyAuth]
└── components/                             [shared, viz Dashboard spec]
    ├── BannerStack.tsx                     [used for token-expired surface]
    └── ToastContainer.tsx
```

### Component LoC budget (proti UI architecture spec 500–1000 frontend LoC)

| Component | Estimated LoC |
|-----------|---------------|
| Settings.tsx | ~20 |
| ConnectionPanel.tsx | ~70 |
| ConfigPanel.tsx | ~50 |
| YamlEditor.tsx (gutter + scroll-sync + error footer) | ~80 |
| api/hooks.ts (Settings-relevant additions) | ~50 |
| api/types.ts (Config/Auth responses) | ~30 |
| **Settings subtotal** | **~300** |
| **Dashboard subtotal** (per Dashboard spec) | ~610 |
| **Total frontend** | **~910** (within 500–1000 budget; 90 % slack) |

Settings spec mírně překračuje předchozí estimate (~200) z Dashboard spec — finer breakdown po extracted prototypu zvedl YamlEditor + ConnectionPanel detail.

### Public TS types (mirror Pydantic from UI architecture spec + auth design)

```ts
interface ConfigParseError {
  line: number;
  message: string;
}

interface ConfigResponse {
  raw_yaml: string;
  parsed: Record<string, unknown> | null;        // dict shape — unclassified_dir + projects
  parse_error: ConfigParseError | null;          // present when GET reads invalid existing file
  masked_token: string | null;                   // optional, see Gap 3
}

interface ConfigSaveSuccess {
  ok: true;
  parsed: Record<string, unknown>;
}

interface ConfigSaveErrors {
  ok: false;
  errors: ConfigParseError[];                    // ≥ 1 entries
}

type ConfigSaveResponse = ConfigSaveSuccess | ConfigSaveErrors;

interface AuthVerifyResponse {
  ok: boolean;
  reason: "PlaudTokenExpired" | "PlaudTokenMissing" | null;
  message: string | null;
}
```

### Public hooks (Settings-relevant)

```ts
function useConfig() {
  return useQuery<ConfigResponse>({
    queryKey: ["config"],
    queryFn: fetchConfig,
    retry: 3,
    retryDelay: (attempt) => 100 * 2 ** attempt,
    // No refetchInterval — config is read on demand (mount + reload click).
  });
}

function useSaveConfig() {
  const qc = useQueryClient();
  return useMutation<ConfigSaveSuccess, ConfigSaveErrors | Error, string>({
    mutationFn: (raw_yaml) => putConfig({ raw_yaml }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["config"] });
      // Toast handled by component (success).
    },
    // 422 errors handled by component via mutation result inspection
    // (NOT thrown into onError — TanStack treats 422 as success structurally).
  });
}

function useVerifyAuth() {
  return useMutation<AuthVerifyResponse, Error, void>({
    mutationFn: postAuthVerify,
    // ok=true → toast; ok=false → banner + toast; HTTP error → toast.
  });
}
```

**Note on 422 handling:** TanStack Query's `useMutation` treats non-`ok` HTTP responses as `onError` callbacks. UI architecture spec specifies `PUT /api/config` returns **422** for validation errors (not 200 with `ok: false`). Recommendation: `client.ts` fetch wrapper raises typed `ValidationError` containing `errors: ConfigParseError[]` for 422, lets `useSaveConfig.onError` route to inline error display.

## Data flow

### Cold load (mount)

```
React mounts Settings route:
  → useConfig().fetch()
       → GET /api/config → 200 {raw_yaml, parsed, parse_error: null}
       → store local yaml state := raw_yaml
       → if parse_error !== null (existing config invalid on disk):
              → show inline error in YamlEditor immediately
              → toast "Existující konfigurace je neplatná — řádek N"
  → useConfig() never running; ConnectionPanel masked_token from response
```

**Note:** `parse_error` v `GET /api/config` response handles edge case "existing on-disk config.yaml je broken" (sync-core would have exited 7 on last run; user opens UI to fix). UI must surface this without breaking — `<ConfigPanel>` shows broken YAML in editor s inline error, user can edit + save.

### Save happy path

```
User edits textarea → local yaml state updates (uncontrolled-controlled hybrid):
  → onChange handler also clears yamlError if set (per prototype line 1057)

User clicks "Uložit":
  → useSaveConfig.mutate(yaml)
       → PUT /api/config body={raw_yaml: yaml}
       → 200 {ok: true, parsed}
  → onSuccess:
       → invalidate ["config"]
       → toast "Konfigurace uložena"
       → inline error (if any) cleared
```

### Save 422 (validation error)

```
User clicks "Uložit" with malformed YAML:
  → PUT /api/config → 422 {ok: false, errors: [{line: 12, message: "..."}, ...]}
  → fetch wrapper raises ValidationError containing errors array
  → useSaveConfig.onError:
       → set yamlError state := errors[0]   (display first error inline)
       → toast "Konfigurace je neplatná — řádek 12"
  → YamlEditor renders red border + line 12 highlighted in gutter +
    inline error footer with "Řádek 12: <message>"
```

**Multi-error handling:** prototype shows only first error. Real backend may return multiple. Decision tracked v Gap 1 below — recommend show first inline + "(+N dalších)" hint with click → expand modal listing all.

### Save 5xx (server error)

```
User clicks "Uložit", FS write fails (disk full, perms):
  → PUT /api/config → 500 {detail: {ok: false, reason: "save_failed", message: "..."}}
  → useSaveConfig.onError:
       → toast error "Uložení selhalo — zkontroluj log"
       → no inline error (server error, not validation)
```

### Verify success

```
User clicks "Otestovat připojení":
  → useVerifyAuth.mutate()
       → POST /api/auth/verify → 200 {ok: true, reason: null, message: null}
  → onSuccess:
       → toast "Token ověřen"
       → any pre-existing token-expired banner from <BannerStack> dismissed
         (banner derivation re-runs from latest verify outcome)
```

### Verify token expired

```
User clicks "Otestovat připojení":
  → POST /api/auth/verify → 200 {ok: false, reason: "PlaudTokenExpired",
                                  message: "Plaud API rejected token — re-paste..."}
  → onSuccess (HTTP 200, structural failure):
       → push banner {variant: "error", title: "Token vypršel",
                      message: "Zkopíruj znovu localStorage.tokenstr...",
                      actionLabel: "Aktualizovat token v .env" (only on /dashboard route)}
       → toast "Ověření tokenu selhalo"
```

### Verify token missing

```
User clicks "Otestovat připojení", but .env doesn't have PLAUD_API_TOKEN:
  → POST /api/auth/verify → 200 {ok: false, reason: "PlaudTokenMissing",
                                  message: "PLAUD_API_TOKEN not set in .env..."}
  → onSuccess:
       → push banner {variant: "error", title: "Token chybí",
                      message: "<message field from response>"}
       → toast "Ověření tokenu selhalo"
```

### Verify HTTP error (5xx / network)

```
  → POST /api/auth/verify → 500 OR fetch throws
  → onError:
       → toast "Ověření tokenu selhalo — zkontroluj síť"
       → no banner (transient, not actionable)
```

### Reload click

```
User clicks "Načíst znovu":
  → useConfig.refetch()
       → GET /api/config → 200 {raw_yaml: <server YAML>, ...}
       → yaml state := raw_yaml
       → yamlError := null
       → toast "Konfigurace načtena znovu"
  → Local edits silently discarded (Gap 4 below — destructive-overwrite risk).
```

## Review delta (gaps vs prototype/specs)

### Gap 1: Multi-error 422 response — prototype shows only first

**Issue:** Prototype's `setYamlError(errLine, errMsg)` is single-error. Sync-core `ConfigValidationError` carries `list[ConfigParseError]` (`config.py` Public API), and `PUT /api/config` 422 body schema in UI architecture spec is `errors: [ConfigParseError, ...]` (array). Real backend can return multiple errors at once (e.g., 3 missing required keys, 2 non-absolute paths). Showing only first means user fixes line 5, saves, sees line 12 error, fixes, saves, sees line 18 error — 3 round-trips for 3 fixes.

**Decision (recommend):** MVP — show first error inline (matches prototype), append `"(+{N-1} dalších chyb)"` text v inline error footer when `errors.length > 1`. Click on that text → expand list as modal or dropdown showing all errors with line numbers. Implementation: trivial conditional render, ~10 LoC v `YamlEditor`.

**Alternative:** show all errors v gutter (multiple lines highlighted) + listed in footer with `<ul>`. More complete but visual noise; defer to v1.1+ if user feedback shows multi-error pattern is common.

### Gap 2: Token masking — frontend hardcoded vs backend-rendered

**Issue:** Prototype hardcodes `masked = "eyJhbGci•••••••••••••••AbcD9"`. UI architecture spec D5 / B5 explicitly forbids `/api/config` exposing token value. Real implementation needs:
- **Option A:** Backend renders mask v `AuthVerifyResponse` (e.g., `masked_token: str` field added). Verify endpoint reads token, masks server-side, returns. UI never receives raw value.
- **Option B:** Backend renders mask v `ConfigResponse.masked_token`. Settings mount → GET /api/config → mask available without verify call.
- **Option C:** Frontend reads constant "•" placeholder + chip "z .env" without any backend hint. Simplest, no PII surfaced; user clicks Verify to confirm token works.

**Decision (recommend):** **Option C** for MVP. Reasons: (a) no new backend response field needed, (b) zero PII surfaced even masked (defense-in-depth), (c) prototype's masked rendering is decorative — user can't act on first/last chars anyway. Implementation: `<ConnectionPanel>` renders `"••••••••••••••••••••"` (20 dots) + chip "z .env". Banner title "Token chybí" surfaces if `PlaudTokenMissing`, replacing decorative mask cue.

**Alternative:** Option A if user signal comes that they want to confirm "yes, that's the token I pasted". Then add `masked_token` field to `AuthVerifyResponse` only (not config response — avoid cross-coupling). Defer to v1.1+ if requested.

### Gap 3: Inline parse error from GET /api/config (existing config broken on mount)

**Issue:** UI architecture spec says `ConfigResponse` includes `parse_error: ConfigParseError | null` for cases where existing on-disk YAML is invalid. Prototype doesn't simulate this scenario — `<YamlEditor>` only shows error after Save. Real flow: user's last sync exited 7, opens UI, Settings route mounts, GET /api/config returns broken YAML + parse_error. UI must immediately show inline error without waiting for Save click.

**Decision (recommend):** `<ConfigPanel>` mount effect: `useEffect(() => { if (config.parse_error) setYamlError(config.parse_error) }, [config])`. Toast on mount: "Existující konfigurace je neplatná — řádek N". Banner: not needed (inline footer is enough; banner would be redundant noise once user is already in Settings).

### Gap 4: Reload click silently discards local edits

**Issue:** Prototype line 1079: `setYaml(DEFAULT_YAML); setYamlError(null); pushToast(...)` — overwrites local textarea state without confirmation. If user typed 50 lines of new project paths, clicked Reload by mistake (e.g., reaching for Save), all work lost.

**Decision (recommend):** MVP — track `yamlDirty: boolean` (whether yaml differs from last fetched). If dirty + Reload clicked, show native `confirm()` dialog: "Zahodit neuložené změny?" Cancel keeps editor; OK proceeds with refetch + reset. Implementation: ~5 LoC in ConfigPanel reload handler. Native confirm is platform-ugly but functional; PyWebView passes through to Windows.

**Alternative:** custom `<ConfirmDialog>` modal (~30 LoC). Better UX, defer to v1.1+.

### Gap 5: YAML editor — no syntax highlighting, no auto-indent, no bracket matching

**Issue:** Prototype is plain `<textarea>` + line-number gutter. Real YAML editing benefits from: (a) syntax highlight (key/value/comment colors), (b) auto-indent on Enter (next line keeps indent of current), (c) bracket/quote pairing.

**Decision (recommend):** **Skip all three for MVP.** Reasoning:
- Tailored YAML library (yaml-language-server, codemirror with yaml mode) costs 30–80 KB + complex setup.
- Plain textarea with monospace + line numbers + line-error highlighting is **acceptable** for occasional edit (config je editováno ~1×/měsíc).
- Auto-indent on Enter is ~15 LoC custom (`onKeyDown` handler) but skip — easier for user to use editor's existing tab/space habits.

**Trigger for re-evaluation:** if user feedback shows config edit is ergonomically painful (>3 complaints in 1 month), add lightweight `js-yaml` for syntax check + naive highlight (regex-based, ~50 LoC).

### Gap 6: Save button always enabled (no dirty detection)

**Issue:** Prototype's Save button is enabled whenever `!savingConfig`. Saving identical YAML (e.g., user opens Settings, glances, clicks Save out of habit) triggers backend write + toast. Acceptable but slightly wasteful.

**Decision (recommend):** MVP keeps always-enabled. Reasoning: (a) backend `PUT /api/config` is idempotent, (b) "force re-validation" is occasionally useful (user wants to confirm current YAML is still valid post-edit elsewhere), (c) dirty detection requires holding "lastSaved YAML" state + diff — extra ~10 LoC complexity. Defer to v1.1+ if feedback shows it matters.

**Alternative:** Save button disabled when `yaml === lastSavedYaml`. Trivial implementation but adds state complexity for marginal UX gain.

### Gap 7: DEFAULT_YAML seed — sync-core or UI backend?

**Issue:** Sync-core spec v0.2 says "config.yaml chybí → exit 7" (config.load_config raises). UI then can't help — backend can't load config to start uvicorn (per UI architecture spec lifespan handler). User has to manually create config.yaml from README before first UI run.

This is a **chicken-and-egg problem**: first-time user can't open UI to write config because UI needs config to start.

**Decision (recommend):** Sync-core `config.load_config()` should detect missing file and **auto-create with DEFAULT_YAML seed** on first run, log `"Created seed config at {path} — please review and customize"`, then continue with parsed seed (which has placeholder paths under `D:\Recordings\...` that may not exist — config validation parent-must-exist rule needs relaxation for seed values, OR seed should use `${STATE_ROOT}/Recordings/...` to guarantee parent exists).

**Out of Settings spec scope:** this is a sync-core impl decision. Note tracked here for review:
- Update sync-core impl to seed DEFAULT_YAML when missing.
- DEFAULT_YAML should reference `${STATE_ROOT}` for guaranteed-existing parent paths in seed.
- README setup: "First UI run creates seed config at ${STATE_ROOT}/config.yaml — edit projects mapping in Settings."

**Defer:** flag this v open questions for sync-core impl cycle, not blocker for Settings spec approval.

### Gap 8: PUT /api/config 422 vs 200+ok=false discrepancy

**Issue:** UI architecture spec B2 documents:
```
// PUT /api/config — body: { raw_yaml: string }
// 200 OK: { ok: true, parsed: {...} }
// 422 Unprocessable: { ok: false, errors: [{line, message}] }
```

But auth verify (separate endpoint) uses different convention:
```
// 200 OK with reason: { ok: false, reason: "PlaudTokenExpired", message: ... }
```

Two different patterns: config uses HTTP status taxonomy (200/422), auth uses 200-with-ok-flag. Frontend handling diverges:
- `useSaveConfig` must catch 422 in fetch wrapper, route to `onError`.
- `useVerifyAuth` checks `response.ok` flag in `onSuccess` payload.

**Decision:** match UI architecture spec as-is. Fetch wrapper (`api/client.ts`) needs branching:
- 4xx for config endpoint → throw `ValidationError(errors)`.
- 200 for auth endpoint → return body, let component check `ok`.

Document v `client.ts` why two conventions coexist (auth verify must distinguish HTTP 5xx — true error — from token issues — semantic state). ~10 LoC + 5 LoC comment.

**Alternative:** harmonize both endpoints. Out of Settings spec scope — would require UI architecture spec revision.

## Open questions (for implementation cycle)

1. **`masked_token` placement** (Gap 2) — Option A (verify response), B (config response), C (frontend constant)? Default: C.
2. **Multi-error 422 display** (Gap 1) — first-only with `(+N dalších)` hint vs all-listed? Default: first-only with hint.
3. **Reload confirm dialog** (Gap 4) — native `confirm()` vs custom modal vs silent overwrite? Default: native confirm if dirty.
4. **DEFAULT_YAML seed** (Gap 7) — sync-core auto-creates vs user creates manually per README? Default: sync-core auto-creates (revisit in sync-core impl).
5. **Save button dirty disable** (Gap 6) — always-enabled vs disabled-when-clean? Default: always-enabled.

These are implementation-cycle questions, not blockers for spec approval.

## Acceptance criteria

Settings implementation je hotová pokud:

1. **Visual parity with prototype** — `frontend/PlaudSync UI.html` rendered side-by-side with built React app shows pixel-equivalent UI for ConnectionPanel + ConfigPanel + YamlEditor.
2. **Token mask renders without raw token leak** — manual smoke: set `PLAUD_API_TOKEN=secret123-xyz` v `.env`, open Settings, inspect HTML source + DOM — no `secret123` substring anywhere.
3. **Verify success** — valid token → spinner → idle + toast "Token ověřen" within 1500 ms.
4. **Verify expired** — invalid token → spinner → idle + banner "Token vypršel" + toast "Ověření tokenu selhalo" within 1500 ms.
5. **Verify missing** — empty `.env` → backend returns `PlaudTokenMissing` → banner "Token chybí".
6. **Save happy path** — edit YAML, click Uložit → spinner → toast "Konfigurace uložena" within 1000 ms; second mount shows persisted YAML.
7. **Save 422** — write tab character at line N, click Uložit → spinner → inline error footer "Řádek N: ..." + line N highlighted in gutter (red bg + bold) + toast "Konfigurace je neplatná — řádek N".
8. **Save 422 multi-error** — submit YAML with 3 errors → first inline + footer hint "(+2 dalších)" with click revealing list.
9. **Save 5xx** — induce backend write failure (chmod read-only state dir) → toast "Uložení selhalo — zkontroluj log" + no inline error.
10. **Reload — dirty confirm** — edit YAML, click Načíst znovu → confirm dialog appears, Cancel keeps edits, OK refetches + clears.
11. **Reload — clean** — no dirty edits → click Načíst znovu → silent refetch + toast "Konfigurace načtena znovu".
12. **Existing broken config on mount** — corrupt config.yaml on disk, open Settings → inline error footer immediately + toast "Existující konfigurace je neplatná — řádek N".
13. **Line gutter scroll sync** — paste 100-line YAML, scroll textarea, gutter scrolls in lockstep (no drift).
14. **Czech localization** — all strings match D10 lock contract.
15. **Frontend bundle ≤ 500 KB gzipped** — UI architecture umbrella W-U2 watch (combined Dashboard + Settings).
16. **Accessibility minimum** — keyboard nav: Tab cycles Verify → textarea → Save → Reload. Focus rings visible. aria-labels on icon-only spinners.

## Implementation plan

→ `writing-plans` skill (next step **after**: sync-core impl on master + UI backend impl + Dashboard spec).

Pořadí navazujících kroků:

1. **Tento spec** schválen userem (autonomní review, pokud OK, jinak revise).
2. **Sync-core implementation** dokončena (paralelně, jiná session) — `config.py` + `path_resolver.py` + state DB.
3. **UI backend writing-plans** cyklus (FastAPI app.py + state_reader + config_io + sync_starter + runner; consumes Dashboard + Settings specs).
4. **Frontend writing-plans** cyklus (React + TS + Tailwind + Vite; transcribes prototype HTML do `frontend/src/` Vite project; consumes Dashboard + Settings specs jako single feature).
5. **Implementation execution** přes superpowers:subagent-driven-development.

## Revision history

- **2026-04-25 (v0):** Extracted z `frontend/PlaudSync UI.html` Claude Design prototype (commit `1ea6bd3`). Review delta proti UI architecture umbrella v0.2 + sync-core v0.2 + auth design. 8 gaps identified, 5 deferred to implementation cycle as open questions, 3 with documented decisions inline.
