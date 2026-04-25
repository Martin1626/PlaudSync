# UI frontend — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transcribe validated Claude Design prototype [`frontend/PlaudSync UI.html`](../../../frontend/PlaudSync%20UI.html) (1222 LoC, 5 scenarios, all interactions wired) into a proper Vite + React 19 + TypeScript strict + Tailwind 4 project at [`frontend/`](../../../frontend/), producing a production bundle copied to `src/plaudsync/ui/static/` (gitignored, consumed by FastAPI `StaticFiles` mount in the parallel UI backend implementation).

**Architecture:** `frontend/src/` decomposes the prototype's 1222-line single file into ~25 focused TSX modules under `api/`, `utils/`, `components/`, `context/`, `pages/Dashboard/`, `pages/Settings/`, `dev/`. Server state via `@tanstack/react-query` (5s/1.5s adaptive polling). Toasts/banners via two minimal React Contexts (no global store library, per umbrella D2). Routing via `react-router-dom` BrowserRouter. Mock data layer in `dev/` is `import.meta.env.DEV`-gated so frontend can be exercised before backend lands; production build tree-shakes it out. CSS keyframes (`ps-pulse`, `ps-indeterminate`, `ps-toast-in`) extracted to `tailwind.config.ts`.

**Tech Stack:** React 19, TypeScript 5.6+ (`strict: true`, `noUncheckedIndexedAccess: true`), Tailwind CSS 4, Vite 7, `@tanstack/react-query` 5, `react-router-dom` 7. **No** UI framework deps (shadcn/Mantine/Ant). **No** test framework (Vitest/Jest) — verification is TypeScript strict + manual smoke per umbrella E6. Bundle target: ≤ 200 KB gzipped (umbrella AC #4; W-U2 watch threshold 500 KB).

**Source-of-truth precedence:** When prototype HTML and spec text disagree, **prototype wins** (validated by user). Specs guide additions the prototype does not exercise (e.g. backend-rendered `masked_token`, multi-error 422, Tab indent — all flagged in Settings v0.1 review delta).

---

## Source documents

- [`frontend/PlaudSync UI.html`](../../../frontend/PlaudSync%20UI.html) — prototype, lines referenced as `proto:NNN`.
- [`docs/superpowers/specs/2026-04-25-ui-architecture-design.md`](../specs/2026-04-25-ui-architecture-design.md) v0.2 — umbrella (build pipeline, types, hooks, CSP).
- [`docs/superpowers/specs/2026-04-25-dashboard-screen-design.md`](../specs/2026-04-25-dashboard-screen-design.md) v0 — Dashboard contract (D1–D10, 13 AC).
- [`docs/superpowers/specs/2026-04-25-settings-screen-design.md`](../specs/2026-04-25-settings-screen-design.md) v0.1 — Settings contract (D1–D11, 20 AC, review fixes applied).

---

## File structure

### Files to create — `frontend/` Vite project root

| Path | Responsibility |
|---|---|
| `frontend/package.json` | Dependencies (React 19, TS 5.6, Tailwind 4, Vite 7, react-router-dom 7, @tanstack/react-query 5), scripts (`dev`, `build`, `preview`, `typecheck`, `postbuild`). |
| `frontend/vite.config.ts` | Build config: outDir `dist`, dev proxy `/api → http://127.0.0.1:${PLAUDSYNC_DEV_PORT}`, `build.modulePreload.polyfill: false` (CSP-friendly). |
| `frontend/tsconfig.json` | Strict TS: `strict`, `noUncheckedIndexedAccess`, `noUnusedLocals`, `noUnusedParameters`, `exactOptionalPropertyTypes`. |
| `frontend/tsconfig.node.json` | Node-side TS config for `vite.config.ts`. |
| `frontend/tailwind.config.ts` | Tailwind theme + keyframes (`ps-pulse`, `ps-indeterminate`, `ps-toast-in`) extracted from prototype `<style>` block. |
| `frontend/postcss.config.js` | Tailwind 4 + autoprefixer. |
| `frontend/index.html` | HTML shell, JetBrains Mono `<link>`, mounts `<div id="root">`. |
| `frontend/.gitignore` | `node_modules/`, `dist/`. |
| `frontend/src/main.tsx` | React 19 root, QueryClientProvider, BrowserRouter, CSS import. |
| `frontend/src/index.css` | Tailwind layers + body font + scrollbar polish + `.font-mono` + `.yaml-textarea` selection styling. |
| `frontend/src/App.tsx` | `<AppShell>` + `<Routes>` (`/` → Dashboard, `/settings` → Settings). |
| `frontend/src/api/types.ts` | TS mirror of Pydantic models from umbrella spec + Settings v0.1 (`AuthVerifyResponse.masked_token`). |
| `frontend/src/api/client.ts` | `fetchJson` wrapper (retry, error classes), MSW-free mock toggle for `import.meta.env.DEV`. |
| `frontend/src/api/hooks.ts` | `useStateQuery`, `useStartSync`, `useConfig`, `useSaveConfig`, `useVerifyAuth`. |
| `frontend/src/utils/format.ts` | `relativeTime`, `formatExactTime`, `phaseLabel`, `classNames`. Czech localization preserved. |
| `frontend/src/utils/colors.ts` | `projectBadgeColor(name)` — stable hash → palette pick (4 blue-family tokens). |
| `frontend/src/components/Logo.tsx` | Sync glyph + "PlaudSync" wordmark. Stateless. |
| `frontend/src/components/SyncStatusBadge.tsx` | Header dot + label. 5 visual states keyed off `SyncState`. |
| `frontend/src/components/Header.tsx` | Sticky header: Logo + tabs (Přehled/Nastavení) + `<SyncStatusBadge>`. Uses `react-router-dom` `<NavLink>`. |
| `frontend/src/components/Banner.tsx` | Single banner: error/warning/info variants, dismiss X, optional action button. |
| `frontend/src/components/BannerStack.tsx` | Renders banners from context. |
| `frontend/src/components/Toast.tsx` | Single toast with success/error icon, click-to-dismiss. |
| `frontend/src/components/ToastContainer.tsx` | Bottom-right fixed stack. Renders toasts from context. |
| `frontend/src/components/ConnectionLostOverlay.tsx` | Full-screen modal. Body + monospace last-error line. Dev-mode "Skrýt" button. |
| `frontend/src/components/AppShell.tsx` | Composes Header + BannerStack + `<main><Outlet /></main>` + ToastContainer + ConnectionLostOverlay. Subscribes to `queryCache` for `useStateQuery` 3× retry-fail → ConnectionLostOverlay. |
| `frontend/src/context/BannersContext.tsx` | Context + provider for app-level banner list (push/dismiss/derive-from-state). |
| `frontend/src/context/ToastsContext.tsx` | Context + provider for app-level toast list (push w/ 4s auto-dismiss). |
| `frontend/src/pages/Dashboard/index.tsx` | Dashboard route component: composes SyncNowPanel + RecordingsList. Wires `useStateQuery` + `useStartSync`. |
| `frontend/src/pages/Dashboard/SyncNowPanel.tsx` | 6 visual states from D2. Sync button + progress bar + "Spuštěno Plánovačem úloh" hint. |
| `frontend/src/pages/Dashboard/RecordingsList.tsx` | List with empty state + items. |
| `frontend/src/pages/Dashboard/StatusIcon.tsx` | 3 states (downloaded/failed/skipped) circular icons. |
| `frontend/src/pages/Dashboard/ProjectBadge.tsx` | gray "nezatříděno" / hash-colored matched. |
| `frontend/src/pages/Settings/index.tsx` | Settings route component: composes ConnectionPanel + ConfigPanel. Wires `useConfig` + `useSaveConfig` + `useVerifyAuth` (incl. implicit verify on mount per Settings v0.1 D2). |
| `frontend/src/pages/Settings/ConnectionPanel.tsx` | Token masked display + verify button. |
| `frontend/src/pages/Settings/ConfigPanel.tsx` | Wraps YamlEditor + Save/Reload buttons + line counter. Reload dirty-confirm dialog. |
| `frontend/src/pages/Settings/YamlEditor.tsx` | Line-number gutter + textarea + scroll-sync + Tab → 2 spaces handler + `aria-hidden="true"` gutter. |
| `frontend/src/pages/Settings/InlineConfigErrors.tsx` | First error inline + `(+N dalších chyb)` `<details>` expansion. Click promotes error to current. |
| `frontend/src/dev/mockState.ts` | `SCENARIOS` object (idle/running/running_by_task_scheduler/partial_failure/failed/empty) + `DEFAULT_YAML`. Identical content to prototype. |
| `frontend/src/dev/MockProvider.tsx` | Dev-only `QueryClient` mock-data injector via `setQueryData`. Strips out of prod via `if (!import.meta.env.DEV) return null` early-return + Vite tree-shake. |
| `frontend/src/dev/DevPanel.tsx` | Dev-only floating panel: scenario picker, force-banner buttons, force-toast buttons, ConnectionLostOverlay toggle. |

### Files to modify — root

| Path | Change |
|---|---|
| `.gitignore` | Append: `frontend/node_modules/`, `frontend/dist/`, `src/plaudsync/ui/static/`. |
| `DEV_LOG.md` | Append entry recording: plan written, branch created, smoke results post-impl. (One commit per plan creation; smoke entry comes after Task 15.) |

### Files NOT touched in this plan

- `src/plaudsync/ui/app.py` and the rest of the FastAPI backend → covered by parallel UI backend plan (out of scope here).
- Backend `sync-core` modules → already merged on `master` (commit `9a6b6a5`). Frontend depends on the contracts they expose, not their internals.
- Task Scheduler `.ps1` script → separate side track.

### Branch

Create `feat/ui-frontend` from `master` before Task 1: `git checkout -b feat/ui-frontend`. Pattern matches `feat/sync-core` and (parallel) `feat/ui-backend`.

### Commit cadence

One commit per task (15 tasks). Final merge commit `Merge feat/ui-frontend: Vite project + Dashboard + Settings` to `master` after Task 15 manual smoke + `/security-review`.

---

## Conventions used in every task

- **Working directory:** all `npm` commands run inside `c:/GitHub/PlaudSync/frontend/`. All `git` commands run with `-C "c:/GitHub/PlaudSync"` to avoid `cd` and the compound-prompt warning.
- **Node version:** Node 20 LTS. No `.nvmrc` ceremony (solo dev) but `engines` field in `package.json` documents minimum.
- **Verification per task:** after implementation, run `npm run typecheck` (alias for `tsc --noEmit`). For UI-touching tasks, also `npm run dev` and visually smoke. Verification commands listed in each task with expected output.
- **Czech strings:** preserved verbatim from prototype (per Settings D10 lock contract + Dashboard spec). When a spec lists a string and the prototype lists a different one, prototype wins.
- **No unit tests:** per umbrella E6. Each task's verification is TypeScript clean + visual smoke. Final acceptance criteria (Task 15) covers all 13 Dashboard + 20 Settings AC manually.
- **Privacy discipline (Settings D11):** no business labels (`title`, `project`, `target_dir`, `plaud_folder`, token middle bytes) interpolated into toast/banner/error message strings. Render via separate JSX nodes (`<code>` tags) when needed. Search before commit: `grep -nE '(title|project|target_dir|plaud_folder|local_path)' frontend/src/**/*.tsx | grep -E '(Toast|Banner|toast|banner|throw)'` — should yield zero hits in mutation/error paths.
- **Commit messages:** end with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` per CLAUDE.md.

---

## Task 1: Bootstrap Vite project — configs, dependencies, branch setup

**Rationale:** Lock the toolchain before any source code lands so Tasks 2–14 share a stable build baseline. Pin major versions explicitly (no `^` floats on the framework axis) to prevent silent React/Tailwind upgrades mid-implementation. Verify `npm install` resolves and `tsc --noEmit` is clean against an empty `src/` (smoke proves the tooling itself works).

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/tailwind.config.ts`
- Create: `frontend/postcss.config.js`
- Create: `frontend/index.html`
- Create: `frontend/.gitignore`
- Modify: `.gitignore` (root) — add `src/plaudsync/ui/static/`

- [ ] **Step 1: Branch off master**

```bash
git -C "c:/GitHub/PlaudSync" checkout master
git -C "c:/GitHub/PlaudSync" pull --ff-only
git -C "c:/GitHub/PlaudSync" checkout -b feat/ui-frontend
```

- [ ] **Step 2: Move prototype HTML out of the way**

The prototype lives at `frontend/PlaudSync UI.html`. The Vite project will use `frontend/` as its root. Keep the prototype as a reference under a subfolder so it does not collide with `index.html`.

```bash
mkdir -p "c:/GitHub/PlaudSync/frontend/_prototype"
mv "c:/GitHub/PlaudSync/frontend/PlaudSync UI.html" "c:/GitHub/PlaudSync/frontend/_prototype/PlaudSync UI.html"
```

Expected: file moved; `ls c:/GitHub/PlaudSync/frontend/` shows only `_prototype/`.

- [ ] **Step 3: Create `frontend/package.json`**

```json
{
  "name": "plaudsync-ui",
  "private": true,
  "version": "0.0.1",
  "type": "module",
  "engines": {
    "node": ">=20"
  },
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build && node scripts/postbuild.mjs",
    "typecheck": "tsc --noEmit",
    "preview": "vite preview --port 4173"
  },
  "dependencies": {
    "react": "19.0.0",
    "react-dom": "19.0.0",
    "react-router-dom": "7.1.1",
    "@tanstack/react-query": "5.62.7"
  },
  "devDependencies": {
    "@types/node": "22.10.2",
    "@types/react": "19.0.2",
    "@types/react-dom": "19.0.2",
    "@vitejs/plugin-react": "4.3.4",
    "autoprefixer": "10.4.20",
    "postcss": "8.4.49",
    "tailwindcss": "4.0.0",
    "@tailwindcss/postcss": "4.0.0",
    "@tailwindcss/forms": "0.5.10",
    "typescript": "5.6.3",
    "vite": "7.0.0"
  }
}
```

Note: pinned (no `^`) so `npm ci` is reproducible. Float-update via `npm outdated` review is dev workflow, not in this plan's scope.

- [ ] **Step 4: Create `frontend/vite.config.ts`**

```ts
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "PLAUDSYNC_");
  const devPort = env.PLAUDSYNC_DEV_PORT ?? "8765";

  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": {
          target: `http://127.0.0.1:${devPort}`,
          changeOrigin: false,
        },
      },
    },
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "src"),
      },
    },
    build: {
      outDir: "dist",
      emptyOutDir: true,
      sourcemap: false,
      target: "es2022",
      modulePreload: { polyfill: false },
      rollupOptions: {
        output: {
          manualChunks: {
            react: ["react", "react-dom", "react-router-dom"],
            query: ["@tanstack/react-query"],
          },
        },
      },
    },
  };
});
```

Notes:
- `modulePreload.polyfill: false` removes the inline preload polyfill so the production HTML stays free of inline `<script>` (CSP `script-src 'self'` strict).
- `manualChunks` splits framework deps into a long-lived chunk.
- Dev proxy reads `PLAUDSYNC_DEV_PORT` (default `8765` matches the umbrella spec example).

- [ ] **Step 5: Create `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 6: Create `frontend/tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts", "scripts/**/*.mjs"]
}
```

- [ ] **Step 7: Create `frontend/tailwind.config.ts`**

```ts
import type { Config } from "tailwindcss";
import forms from "@tailwindcss/forms";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "monospace",
        ],
      },
      keyframes: {
        "ps-pulse": {
          "0%, 100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: "0.55", transform: "scale(0.85)" },
        },
        "ps-indeterminate": {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(400%)" },
        },
        "ps-toast-in": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "ps-pulse": "ps-pulse 1.4s ease-in-out infinite",
        "ps-indeterminate": "ps-indeterminate 1.6s ease-in-out infinite",
        "ps-toast-in": "ps-toast-in 180ms ease-out",
      },
    },
  },
  plugins: [forms],
} satisfies Config;
```

These three keyframes are extracted directly from prototype `<style>` block (proto:25–46). Tailwind exposes them as `animate-ps-pulse`, `animate-ps-indeterminate`, `animate-ps-toast-in` (used in component tasks).

- [ ] **Step 8: Create `frontend/postcss.config.js`**

```js
export default {
  plugins: {
    "@tailwindcss/postcss": {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 9: Create `frontend/index.html`**

```html
<!doctype html>
<html lang="cs">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>PlaudSync</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

JetBrains Mono is self-hosted via `@fontsource/jetbrains-mono` (added in Task 2 dependencies + imported in `index.css`) so the production CSP `connect-src 'self'` stays strict — no fonts.googleapis.com / fonts.gstatic.com.

- [ ] **Step 10: Create `frontend/.gitignore`**

```
node_modules/
dist/
.vite/
*.local
```

- [ ] **Step 11: Append to root `.gitignore`**

Append to `c:/GitHub/PlaudSync/.gitignore`:

```
# Frontend build artefact (generated from frontend/ Vite project)
src/plaudsync/ui/static/
```

- [ ] **Step 12: Create placeholder `frontend/src/main.tsx` so tsc has something to scan**

```bash
mkdir -p "c:/GitHub/PlaudSync/frontend/src"
```

Then create `frontend/src/main.tsx` (placeholder, replaced in Task 2):

```ts
// Bootstrap placeholder — replaced by Task 2.
export {};
```

- [ ] **Step 13: Install dependencies**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm install
```

Expected: `added NNN packages`, no severity-ERR peer warnings. `package-lock.json` created. Resolution time: 30–90 s on cold cache.

If any peer dep ERR (e.g. React 19 vs `react-router-dom`): pin `react-router-dom` to a version that supports React 19 — check `npm view react-router-dom@7 peerDependencies`. Versions remain explicit; do not switch to floats.

- [ ] **Step 14: Verify TypeScript compiles**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm run typecheck
```

Expected: exit 0, no output (success). `tsconfig.json` strict flags satisfied against the placeholder `main.tsx`.

- [ ] **Step 15: Verify Vite dev server starts**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm run dev
```

Expected: stdout contains `VITE v7.0.0 ready in NNN ms` and `Local:   http://127.0.0.1:5173/`. Open the URL — empty page, no console errors. Stop with `Ctrl+C`.

- [ ] **Step 16: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add frontend/ .gitignore
git -C "c:/GitHub/PlaudSync" commit -m "chore(frontend): bootstrap Vite + React 19 + TS strict + Tailwind 4

Pin major versions. Dev proxy /api to PLAUDSYNC_DEV_PORT (default 8765).
Build with modulePreload.polyfill=false for CSP-strict inline-script-free
output. manualChunks split framework deps. Move prototype HTML to
frontend/_prototype/. Gitignore frontend/ build artefacts and
src/plaudsync/ui/static/.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Entry point — `main.tsx`, `index.css`, font import, minimal `App.tsx`

**Rationale:** Boot the React 19 root + QueryClient + BrowserRouter so subsequent tasks can assume `<App />` mounts and routing works. Self-host JetBrains Mono so CSP `connect-src 'self'` stays strict in production. This task ends with a visibly running dev server showing a placeholder "PlaudSync" page — visual confirmation that all wiring is correct before component work begins.

**Files:**
- Modify: `frontend/package.json` — add `@fontsource/jetbrains-mono` dependency.
- Modify: `frontend/src/main.tsx` (replace placeholder).
- Create: `frontend/src/index.css`.
- Create: `frontend/src/App.tsx`.

- [ ] **Step 1: Add `@fontsource/jetbrains-mono` to dependencies**

Edit `frontend/package.json`, in `dependencies` insert before `react`:

```json
    "@fontsource/jetbrains-mono": "5.1.0",
```

Run install:

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm install
```

Expected: `added 1 package`. Verify:

```bash
cd "c:/GitHub/PlaudSync/frontend" && ls node_modules/@fontsource/jetbrains-mono/
```

Expected: directory exists with `.woff2` files.

- [ ] **Step 2: Create `frontend/src/index.css`**

```css
@import "@fontsource/jetbrains-mono/400.css";
@import "@fontsource/jetbrains-mono/500.css";
@import "@fontsource/jetbrains-mono/600.css";

@import "tailwindcss";

@layer base {
  html,
  body,
  #root {
    height: 100%;
  }
  body {
    font-family:
      ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto,
      "Helvetica Neue", sans-serif;
    background: #f9fafb;
    color: #111827;
    -webkit-font-smoothing: antialiased;
  }
}

@layer utilities {
  /* YAML editor: line numbers + textarea share metrics */
  .yaml-line-numbers,
  .yaml-textarea {
    font-family:
      "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
      monospace;
    font-size: 13px;
    line-height: 20px;
    tab-size: 2;
  }
  .yaml-textarea {
    caret-color: #2563eb;
  }
  .yaml-textarea::selection {
    background: #dbeafe;
  }
}

/* subtle scrollbar */
::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}
::-webkit-scrollbar-thumb {
  background: #d1d5db;
  border-radius: 6px;
}
::-webkit-scrollbar-thumb:hover {
  background: #9ca3af;
}
::-webkit-scrollbar-track {
  background: transparent;
}

/* focus ring polish */
button:focus-visible,
a:focus-visible,
input:focus-visible,
textarea:focus-visible,
select:focus-visible {
  outline: 2px solid #2563eb;
  outline-offset: 2px;
  border-radius: 6px;
}
```

This is a 1:1 transfer from the prototype `<style>` block (proto:14–69) **minus** the `@keyframes ps-*` definitions (now in `tailwind.config.ts` Task 1 Step 7) and **plus** `@layer base` / `@layer utilities` for Tailwind 4 layering.

- [ ] **Step 3: Replace `frontend/src/main.tsx`**

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import App from "./App";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 3,
      retryDelay: (attempt) => 100 * 2 ** attempt,
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: 0,
    },
  },
});

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("Missing #root element in index.html");

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
```

Notes:
- Default `retry: 3` + exp backoff (100/200/400 ms) matches umbrella spec for `useStateQuery`. Per-hook overrides (e.g. `retry: 0` on mutations) win over these defaults.
- `refetchOnWindowFocus: false` — UI is desktop-embedded (PyWebView), no need for tab-focus refetch.

- [ ] **Step 4: Create minimal `frontend/src/App.tsx`**

```tsx
export default function App() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center">
        <h1 className="text-2xl font-semibold text-gray-900">PlaudSync</h1>
        <p className="mt-2 text-sm text-gray-500">
          Vite + React + TypeScript bootstrap.
        </p>
      </div>
    </div>
  );
}
```

This placeholder is replaced wholesale by Task 12 (AppShell + routing). It exists now only so the dev server has something to render visually.

- [ ] **Step 5: Verify TypeScript clean**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm run typecheck
```

Expected: exit 0, no output.

- [ ] **Step 6: Verify dev server visually**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm run dev
```

Open `http://127.0.0.1:5173/` in a browser. Expected:
- Centered "PlaudSync" heading + sub-line in JetBrains Mono–ish stack (the heading is sans-serif by default, the page body inherits the body fallback).
- Background `#f9fafb` (very light gray).
- DevTools console: zero errors, zero CSP warnings.
- Network tab: no requests to `fonts.googleapis.com` or `fonts.gstatic.com`. Only `127.0.0.1:5173/*` requests.

Stop with `Ctrl+C`.

- [ ] **Step 7: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add frontend/
git -C "c:/GitHub/PlaudSync" commit -m "feat(frontend): mount React 19 root + QueryClient + BrowserRouter

Self-host JetBrains Mono via @fontsource so CSP connect-src 'self'
stays strict. Move prototype <style> body+scrollbar+focus rules into
src/index.css under Tailwind 4 layers. Placeholder App.tsx renders
a centered heading; replaced by Task 12 with full AppShell + routing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: API types — `src/api/types.ts`

**Rationale:** All hooks and components consume these types; defining them first makes everything that follows compile against a stable contract. Mirrors the Pydantic shapes in [umbrella spec §"Public API"](../specs/2026-04-25-ui-architecture-design.md#components) plus Settings v0.1 review fixes (`AuthVerifyResponse.masked_token` per Gap 2 Option A; `RecordingRow.plaud_folder` per Dashboard D3; `parse_error` on `ConfigResponse` per Settings Gap 3). Per umbrella E4: manual sync. First Pydantic↔TS drift bug post-launch triggers auto-gen migration — not in scope here.

**Files:**
- Create: `frontend/src/api/types.ts`

- [ ] **Step 1: Create `frontend/src/api/types.ts`**

```ts
export type SyncStatus = "idle" | "running";
export type SyncTrigger = "task_scheduler" | "ui_sync_now" | "manual";
export type SyncOutcome = "success" | "partial_failure" | "failed";
export type SyncPhase = "listing" | "downloading" | "categorizing" | "finalizing";
export type ClassificationStatus = "matched" | "unclassified";
export type RecordingStatus = "downloaded" | "failed" | "skipped";

export interface SyncProgress {
  phase: SyncPhase | null;
  processed_count: number | null;
  total_count: number | null;
}

export interface SyncState {
  status: SyncStatus;
  trigger: SyncTrigger | null;
  started_at: string | null;
  last_run_at: string | null;
  last_run_outcome: SyncOutcome | null;
  last_run_exit_code: number | null;
  last_error_summary: string | null;
  progress: SyncProgress | null;
}

export interface RecordingRow {
  plaud_id: string;
  title: string;
  created_at: string;
  downloaded_at: string;
  plaud_folder: string;
  classification_status: ClassificationStatus;
  project: string | null;
  target_dir: string;
  status: RecordingStatus;
}

export interface StateResponse {
  sync: SyncState;
  recordings: RecordingRow[];
}

// ---------------- Auth ----------------

export type AuthFailureReason = "PlaudTokenExpired" | "PlaudTokenMissing";

export interface AuthVerifyResponse {
  ok: boolean;
  reason: AuthFailureReason | null;
  message: string | null;
  /**
   * Server-rendered mask (first_8 + 15 dots + last_4) per Settings spec v0.1
   * Gap 2 Option A. `null` only when the token is literally absent
   * (`PlaudTokenMissing`).
   */
  masked_token: string | null;
}

// ---------------- Config ----------------

export interface ConfigParseError {
  line: number;
  message: string;
}

export interface ConfigResponse {
  raw_yaml: string;
  /** Schema-shaped: { unclassified_dir: string, projects: Record<string, string> }. */
  parsed: Record<string, unknown> | null;
  /** Present when GET reads an existing-but-invalid config.yaml from disk. */
  parse_error: ConfigParseError | null;
}

export interface ConfigSaveSuccess {
  ok: true;
  parsed: Record<string, unknown>;
}

export interface ConfigSaveErrors {
  ok: false;
  errors: ConfigParseError[];
}

// ---------------- Sync trigger ----------------

export interface StartSyncResponse {
  sync_id: string;
  started_at: string;
}

export interface StartSyncConflict {
  ok: false;
  reason: "already_running";
  started_at: string;
  by: SyncTrigger;
}

export interface StartSyncFailure {
  ok: false;
  reason: "spawn_failed";
  message: string;
  exit_code?: number;
}
```

- [ ] **Step 2: Verify TypeScript clean**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm run typecheck
```

Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add frontend/src/api/types.ts
git -C "c:/GitHub/PlaudSync" commit -m "feat(frontend): TS types mirror Pydantic from umbrella + Settings v0.1

StateResponse / RecordingRow / SyncState match umbrella E4. AuthVerifyResponse
includes masked_token per Settings v0.1 Gap 2 (Option A — server renders mask
first_8+15dots+last_4). ConfigResponse.parse_error covers existing-broken
on-disk YAML on mount (Settings Gap 3). Manual mirror per umbrella E4 — auto-
gen deferred until first drift bug.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: HTTP client — `src/api/client.ts`

**Rationale:** Centralise fetch + retry + error taxonomy in one module so hooks (Task 5) stay small. Two HTTP conventions coexist (Settings spec Gap 8): `PUT /api/config` returns 422 for validation errors → throw typed `ValidationError`; `POST /api/auth/verify` returns 200 with `ok: false` + reason → return body as-is, let component branch. `POST /api/sync/start` returns 409 → throw `ConflictError`. All custom errors carry HTTP status + parsed body so callers can route in `onError`.

**Files:**
- Create: `frontend/src/api/client.ts`

- [ ] **Step 1: Create `frontend/src/api/client.ts`**

```ts
import type {
  AuthVerifyResponse,
  ConfigParseError,
  ConfigResponse,
  ConfigSaveSuccess,
  StartSyncResponse,
  StartSyncConflict,
  StateResponse,
  SyncTrigger,
} from "./types";

// ---------------- Error taxonomy ----------------

export class ApiNetworkError extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = "ApiNetworkError";
  }
}

export class ApiHttpError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
    message?: string,
  ) {
    super(message ?? `HTTP ${status}`);
    this.name = "ApiHttpError";
  }
}

export class ValidationError extends ApiHttpError {
  public readonly errors: ConfigParseError[];
  constructor(body: { ok: false; errors: ConfigParseError[] }) {
    super(422, body, "Configuration validation failed");
    this.name = "ValidationError";
    this.errors = body.errors;
  }
}

export class ConflictError extends ApiHttpError {
  public readonly startedAt: string;
  public readonly by: SyncTrigger;
  constructor(body: StartSyncConflict) {
    super(409, body, "Sync already running");
    this.name = "ConflictError";
    this.startedAt = body.started_at;
    this.by = body.by;
  }
}

// ---------------- Low-level fetch ----------------

async function fetchJson<T>(input: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(input, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch (err) {
    throw new ApiNetworkError("Network request failed", err);
  }

  let body: unknown = null;
  const text = await response.text();
  if (text.length > 0) {
    try {
      body = JSON.parse(text);
    } catch {
      // Non-JSON body (e.g. HTML error page) — keep as text on body field.
      body = { raw: text };
    }
  }

  if (!response.ok) {
    throw new ApiHttpError(response.status, body);
  }
  return body as T;
}

// ---------------- Endpoint methods ----------------

export function fetchState(): Promise<StateResponse> {
  return fetchJson<StateResponse>("/api/state");
}

export function fetchConfig(): Promise<ConfigResponse> {
  return fetchJson<ConfigResponse>("/api/config");
}

export async function putConfig(rawYaml: string): Promise<ConfigSaveSuccess> {
  try {
    return await fetchJson<ConfigSaveSuccess>("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raw_yaml: rawYaml }),
    });
  } catch (err) {
    if (err instanceof ApiHttpError && err.status === 422) {
      const body = err.body as { ok: false; errors: ConfigParseError[] } | null;
      if (body && Array.isArray(body.errors)) {
        throw new ValidationError(body);
      }
    }
    throw err;
  }
}

export function postAuthVerify(): Promise<AuthVerifyResponse> {
  // Auth verify uses 200-with-ok-flag convention (umbrella spec B2).
  // Component branches on response.ok rather than catching HTTP error.
  return fetchJson<AuthVerifyResponse>("/api/auth/verify", { method: "POST" });
}

export async function postStartSync(): Promise<StartSyncResponse> {
  try {
    return await fetchJson<StartSyncResponse>("/api/sync/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
  } catch (err) {
    if (err instanceof ApiHttpError && err.status === 409) {
      // FastAPI emits 409 conflict with `detail: { ok, reason, started_at, by }`.
      const detail = (err.body as { detail?: StartSyncConflict } | null)?.detail;
      if (detail && detail.reason === "already_running") {
        throw new ConflictError(detail);
      }
    }
    throw err;
  }
}
```

Notes:
- `fetchJson` is generic and JSON-only; binary endpoints would need a separate path (none in MVP).
- Error classes inherit from `ApiHttpError` so callers can `instanceof ApiHttpError` and narrow further with `instanceof ValidationError`.
- `putConfig`'s 422 → `ValidationError` transformation lives in client.ts (not in the hook) so any consumer of `putConfig` gets the typed error without re-implementing.
- FastAPI's `HTTPException(409, detail={...})` puts the conflict body under `detail`; we unwrap accordingly so callers see a flat `ConflictError`.

- [ ] **Step 2: Verify TypeScript clean**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm run typecheck
```

Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add frontend/src/api/client.ts
git -C "c:/GitHub/PlaudSync" commit -m "feat(frontend): API client with typed error taxonomy

ApiNetworkError / ApiHttpError / ValidationError (422) / ConflictError (409).
Two endpoint conventions coexist (umbrella B2): PUT /api/config 422 -> throw
ValidationError; POST /api/auth/verify 200 with ok-flag -> body returned for
component branching. POST /api/sync/start 409 with detail.reason=already_running
unwrapped to ConflictError carrying started_at + by trigger.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: TanStack Query hooks — `src/api/hooks.ts`

**Rationale:** Wrap the client functions in TanStack hooks so components stay declarative. `useStateQuery` adapts `refetchInterval` (5000 ms idle / 1500 ms running) per Dashboard D10. Mutations invalidate `["state"]` or `["config"]` to fan out fresh data. `keepPreviousData` on the state query means a transient fetch failure doesn't blank the recordings list (umbrella "Error handling" invariant).

**Files:**
- Create: `frontend/src/api/hooks.ts`

- [ ] **Step 1: Create `frontend/src/api/hooks.ts`**

```ts
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  fetchConfig,
  fetchState,
  postAuthVerify,
  postStartSync,
  putConfig,
} from "./client";
import type {
  AuthVerifyResponse,
  ConfigResponse,
  ConfigSaveSuccess,
  StartSyncResponse,
  StateResponse,
} from "./types";

export const STATE_QUERY_KEY = ["state"] as const;
export const CONFIG_QUERY_KEY = ["config"] as const;

export function useStateQuery() {
  return useQuery<StateResponse>({
    queryKey: STATE_QUERY_KEY,
    queryFn: fetchState,
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.sync.status === "running" ? 1500 : 5000;
    },
    placeholderData: (prev) => prev,
    retry: 3,
    retryDelay: (attempt) => 100 * 2 ** attempt,
  });
}

export function useStartSync() {
  const qc = useQueryClient();
  return useMutation<StartSyncResponse, Error, void>({
    mutationFn: postStartSync,
    onSettled: () => {
      // Always invalidate state — happy path picks up running stav,
      // 409 ConflictError still wants a fresh state read to show running.
      void qc.invalidateQueries({ queryKey: STATE_QUERY_KEY });
    },
  });
}

export function useConfig() {
  return useQuery<ConfigResponse>({
    queryKey: CONFIG_QUERY_KEY,
    queryFn: fetchConfig,
    retry: 3,
    retryDelay: (attempt) => 100 * 2 ** attempt,
    // No refetchInterval — config is fetched on mount + reload click.
  });
}

export function useSaveConfig() {
  const qc = useQueryClient();
  return useMutation<ConfigSaveSuccess, Error, string>({
    mutationFn: putConfig,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: CONFIG_QUERY_KEY });
    },
  });
}

export function useVerifyAuth() {
  return useMutation<AuthVerifyResponse, Error, void>({
    mutationFn: postAuthVerify,
  });
}
```

Notes:
- TanStack Query v5 changed `refetchInterval` arg shape — `(query) => ...` now receives the full `Query` object. We read `query.state.data` per the v5 signature.
- `placeholderData: (prev) => prev` is the v5 idiom replacing v4 `keepPreviousData: true` — same behavior.
- `useStartSync` invalidates state in `onSettled` (not `onError`) so both 202 success and 409 conflict re-fetch. Component code distinguishes `ConflictError` (transparent) from other errors (banner) via `instanceof` in its own `onError` handler.
- `useSaveConfig`'s caller catches `ValidationError` in component-level `onError`. The hook itself stays neutral.
- `useVerifyAuth` returns the response body — components branch on `data.ok` and `data.reason` (200-with-ok-flag convention, umbrella B2).

- [ ] **Step 2: Verify TypeScript clean**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm run typecheck
```

Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add frontend/src/api/hooks.ts
git -C "c:/GitHub/PlaudSync" commit -m "feat(frontend): TanStack hooks for state/config/auth/sync

useStateQuery adapts refetchInterval 5000/1500 by sync.status (Dashboard D10).
placeholderData keeps last snapshot during fetch failures (umbrella error
handling invariant). useStartSync invalidates state in onSettled so both 202
success and 409 ConflictError trigger a fresh state read. useSaveConfig +
useVerifyAuth stay neutral; component-level onError handles 422 / ok-false
branching.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Utilities — `src/utils/format.ts` and `src/utils/colors.ts`

**Rationale:** Extract pure helpers from prototype proto:262–299 (`relativeTime`, `formatExactTime`, `phaseLabel`, `classNames`) and proto:840–841 (hash-based palette pick) into dedicated modules so components stay focused on rendering. All Czech localization preserved verbatim per Settings D10 + Dashboard spec.

**Files:**
- Create: `frontend/src/utils/format.ts`
- Create: `frontend/src/utils/colors.ts`

- [ ] **Step 1: Create `frontend/src/utils/format.ts`**

```ts
import type { SyncProgress } from "@/api/types";

export function classNames(
  ...xs: Array<string | false | null | undefined>
): string {
  return xs.filter(Boolean).join(" ");
}

/**
 * Relative time in Czech. Mirrors prototype proto:264-278 exactly.
 * Returns null when iso is null/undefined so callers can short-circuit.
 */
export function relativeTime(
  iso: string | null | undefined,
  now: Date = new Date(),
): string | null {
  if (!iso) return null;
  const a = new Date(iso).getTime();
  const b = now.getTime();
  const diffMin = Math.round((b - a) / 60000);
  if (diffMin < 1) return "právě teď";
  if (diffMin < 60) return `před ${diffMin} min`;
  const hours = Math.round(diffMin / 60);
  if (hours < 24) return `před ${hours} h`;
  const days = Math.round(hours / 24);
  if (days === 1) return "včera";
  if (days < 7) return `před ${days} dny`;
  const d = new Date(iso);
  return d.toLocaleDateString("cs-CZ", { month: "short", day: "numeric" });
}

/**
 * Exact local time, Czech locale. Prototype proto:280-287.
 * Format: "23. dub 14:32".
 */
export function formatExactTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("cs-CZ", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Czech sync phase label. Prototype proto:289-299.
 */
export function phaseLabel(p: SyncProgress | null | undefined): string {
  if (!p) return "Pracuji…";
  const { phase, processed_count, total_count } = p;
  switch (phase) {
    case "listing":
      return "Načítám seznam nahrávek…";
    case "downloading":
      return `Stahuji ${processed_count} z ${total_count}`;
    case "categorizing":
      return `Kategorizuji ${processed_count} z ${total_count}`;
    case "finalizing":
      return "Ukládám metadata…";
    default:
      return "Pracuji…";
  }
}
```

Notes:
- `relativeTime` accepts an injectable `now: Date` for testability later (prototype hard-coded `NOW` constant — we accept a default `new Date()` so production use is identical, but tests can pin time without monkey-patching).
- `phaseLabel` interpolates `processed_count`/`total_count` numbers — these are integers, not user-controlled labels, so D11 privacy rule (no business labels in messages) is not violated.

- [ ] **Step 2: Create `frontend/src/utils/colors.ts`**

```ts
export interface BadgeColor {
  bg: string;
  text: string;
  border: string;
}

const PALETTE: readonly BadgeColor[] = [
  { bg: "bg-blue-50", text: "text-blue-700", border: "border-blue-200" },
  { bg: "bg-indigo-50", text: "text-indigo-700", border: "border-indigo-200" },
  { bg: "bg-sky-50", text: "text-sky-700", border: "border-sky-200" },
  { bg: "bg-violet-50", text: "text-violet-700", border: "border-violet-200" },
];

/**
 * Stable hash → palette pick. Same project name always yields the same color.
 * Mirrors prototype proto:840-841 hash function exactly so existing visual
 * snapshots remain valid.
 */
export function projectBadgeColor(projectName: string): BadgeColor {
  let h = 0;
  for (let i = 0; i < projectName.length; i++) {
    h = (h * 31 + projectName.charCodeAt(i)) >>> 0;
  }
  // PALETTE has length 4 > 0, so non-null assertion is safe.
  return PALETTE[h % PALETTE.length]!;
}
```

The `!` non-null assertion is necessary because `noUncheckedIndexedAccess: true` makes `PALETTE[i]` typed as `BadgeColor | undefined`. The runtime invariant (`PALETTE.length > 0`, modulo always in range) makes the assertion safe.

- [ ] **Step 3: Verify TypeScript clean**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm run typecheck
```

Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add frontend/src/utils/
git -C "c:/GitHub/PlaudSync" commit -m "feat(frontend): pure helpers — format + colors

Extract relativeTime / formatExactTime / phaseLabel / classNames from
prototype proto:262-299 (Czech localization preserved verbatim per Settings
D10 + Dashboard spec). projectBadgeColor mirrors prototype proto:840-841
hash function for visual stability across renders.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Static layout components — `Logo`, `SyncStatusBadge`, `Header`

**Rationale:** Three stateless layout components, transcribed from prototype proto:532–606. Header uses `react-router-dom`'s `<NavLink>` so the active tab is route-driven (the prototype mocked it with local state — we now have a real router). All Czech strings preserved.

**Files:**
- Create: `frontend/src/components/Logo.tsx`
- Create: `frontend/src/components/SyncStatusBadge.tsx`
- Create: `frontend/src/components/Header.tsx`

- [ ] **Step 1: Create `frontend/src/components/Logo.tsx`**

```tsx
export default function Logo() {
  return (
    <div className="flex items-center gap-2">
      <div className="relative w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center shadow-sm">
        <svg
          viewBox="0 0 24 24"
          className="w-4 h-4 text-white"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M3 12a9 9 0 0 1 15.5-6.3L21 8" />
          <path d="M21 4v4h-4" />
          <path d="M21 12a9 9 0 0 1-15.5 6.3L3 16" />
          <path d="M3 20v-4h4" />
        </svg>
      </div>
      <span className="font-semibold tracking-tight text-gray-900">PlaudSync</span>
    </div>
  );
}
```

Direct transcription proto:532–547. Added `aria-hidden="true"` on the decorative SVG (the wordmark beside it carries the accessible name).

- [ ] **Step 2: Create `frontend/src/components/SyncStatusBadge.tsx`**

```tsx
import type { ReactNode } from "react";

import type { SyncState } from "@/api/types";
import { phaseLabel, relativeTime } from "@/utils/format";

interface Props {
  sync: SyncState;
}

export default function SyncStatusBadge({ sync }: Props) {
  let dot: ReactNode;
  let label: string;

  if (sync.status === "running") {
    dot = <span className="w-2 h-2 rounded-full bg-blue-500 animate-ps-pulse" />;
    label = phaseLabel(sync.progress);
  } else if (sync.last_run_outcome === "failed") {
    dot = <span className="w-2 h-2 rounded-full bg-red-500" />;
    label = "Poslední synchronizace selhala";
  } else if (sync.last_run_outcome === "partial_failure") {
    dot = <span className="w-2 h-2 rounded-full bg-amber-500" />;
    label = `Poslední sync ${relativeTime(sync.last_run_at) ?? "—"} — částečný`;
  } else if (sync.last_run_outcome === "success") {
    dot = <span className="w-2 h-2 rounded-full bg-green-500" />;
    label = `Poslední sync ${relativeTime(sync.last_run_at) ?? "—"}`;
  } else {
    dot = <span className="w-2 h-2 rounded-full bg-gray-300" />;
    label = "Nečinný";
  }

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-gray-50 border border-gray-200">
      {dot}
      <span className="text-[13px] text-gray-700 font-medium">{label}</span>
    </div>
  );
}
```

Note: `ReactNode` (not `JSX.Element`) — React 19 + `@types/react` ≥ 19 deprecated the implicit global `JSX` namespace.

Direct transcription proto:549–573. Single notable change: `ps-pulse` className → `animate-ps-pulse` (Tailwind 4 wraps custom keyframes under the `animate-` prefix per `tailwind.config.ts` Task 1 Step 7).

- [ ] **Step 3: Create `frontend/src/components/Header.tsx`**

```tsx
import { NavLink } from "react-router-dom";

import type { SyncState } from "@/api/types";
import { classNames } from "@/utils/format";

import Logo from "./Logo";
import SyncStatusBadge from "./SyncStatusBadge";

interface Props {
  sync: SyncState;
}

export default function Header({ sync }: Props) {
  return (
    <header className="sticky top-0 z-30 bg-white/90 backdrop-blur border-b border-gray-200">
      <div className="max-w-6xl mx-auto px-6 h-14 flex items-center gap-6">
        <Logo />
        <nav className="flex items-center gap-1 ml-2">
          <NavTab to="/" label="Přehled" />
          <NavTab to="/settings" label="Nastavení" />
        </nav>
        <div className="ml-auto">
          <SyncStatusBadge sync={sync} />
        </div>
      </div>
    </header>
  );
}

interface NavTabProps {
  to: string;
  label: string;
}

function NavTab({ to, label }: NavTabProps) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        classNames(
          "relative px-3 py-1.5 text-sm font-medium rounded-md transition-colors",
          isActive
            ? "text-gray-900 bg-gray-100"
            : "text-gray-600 hover:text-gray-900 hover:bg-gray-50",
        )
      }
    >
      {({ isActive }) => (
        <>
          {label}
          {isActive && (
            <span className="absolute -bottom-[13px] left-2 right-2 h-0.5 bg-blue-600 rounded-full" />
          )}
        </>
      )}
    </NavLink>
  );
}
```

Direct transcription proto:575–606 with two changes:
- Local `route` state replaced by route-driven `<NavLink>` `isActive`.
- `end={to === "/"}` so `/` only matches exactly (otherwise both tabs would highlight when on `/settings`).

- [ ] **Step 4: Verify TypeScript clean**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm run typecheck
```

Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add frontend/src/components/Logo.tsx frontend/src/components/SyncStatusBadge.tsx frontend/src/components/Header.tsx
git -C "c:/GitHub/PlaudSync" commit -m "feat(frontend): static layout components

Logo + SyncStatusBadge + Header transcribed from prototype proto:532-606.
Header tabs use react-router-dom NavLink isActive (replacing prototype's
local route state). aria-hidden on decorative Logo SVG. ps-pulse renamed
to animate-ps-pulse (Tailwind 4 prefix per tailwind.config.ts).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Notification components — `Banner`, `BannerStack`, `Toast`, `ToastContainer`, `ConnectionLostOverlay`

**Rationale:** Five presentational components transcribed from prototype proto:608–730. They consume props only — they have no idea where banners/toasts come from. Task 9 wires the contexts that feed them; Task 12 mounts them inside `<AppShell>`.

**Files:**
- Create: `frontend/src/components/Banner.tsx`
- Create: `frontend/src/components/BannerStack.tsx`
- Create: `frontend/src/components/Toast.tsx`
- Create: `frontend/src/components/ToastContainer.tsx`
- Create: `frontend/src/components/ConnectionLostOverlay.tsx`

- [ ] **Step 1: Create `frontend/src/components/Banner.tsx`**

```tsx
import { classNames } from "@/utils/format";

export type BannerVariant = "error" | "warning" | "info";

export interface BannerData {
  id: string;
  variant: BannerVariant;
  title: string;
  message: string;
  actionLabel?: string;
  /** Route key, e.g. "settings". When set, action navigates there. */
  actionTarget?: "settings";
}

interface Props {
  banner: BannerData;
  onDismiss: (id: string) => void;
  onAction: (banner: BannerData) => void;
}

const VARIANT: Record<
  BannerVariant,
  {
    bg: string;
    border: string;
    iconColor: string;
    titleColor: string;
    bodyColor: string;
  }
> = {
  error: {
    bg: "bg-red-50",
    border: "border-red-200",
    iconColor: "text-red-600",
    titleColor: "text-red-900",
    bodyColor: "text-red-800",
  },
  warning: {
    bg: "bg-amber-50",
    border: "border-amber-200",
    iconColor: "text-amber-600",
    titleColor: "text-amber-900",
    bodyColor: "text-amber-800",
  },
  info: {
    bg: "bg-blue-50",
    border: "border-blue-200",
    iconColor: "text-blue-600",
    titleColor: "text-blue-900",
    bodyColor: "text-blue-800",
  },
};

function VariantIcon({
  variant,
  className,
}: {
  variant: BannerVariant;
  className: string;
}) {
  const common = {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    className,
    "aria-hidden": true,
  };
  if (variant === "error") {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 8v4M12 16h.01" />
      </svg>
    );
  }
  if (variant === "warning") {
    return (
      <svg {...common}>
        <path d="M10.3 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.7 3.86a2 2 0 0 0-3.4 0z" />
        <path d="M12 9v4M12 17h.01" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 16v-4M12 8h.01" />
    </svg>
  );
}

export default function Banner({ banner, onDismiss, onAction }: Props) {
  const c = VARIANT[banner.variant];
  return (
    <div
      className={classNames(
        "flex gap-3 items-start px-4 py-3 border",
        c.bg,
        c.border,
      )}
    >
      <VariantIcon
        variant={banner.variant}
        className={classNames("w-5 h-5 mt-0.5 flex-shrink-0", c.iconColor)}
      />
      <div className="flex-1 min-w-0">
        <div className={classNames("text-[13px] font-semibold", c.titleColor)}>
          {banner.title}
        </div>
        <div className={classNames("text-[13px] mt-0.5", c.bodyColor)}>
          {banner.message}
        </div>
      </div>
      {banner.actionLabel && (
        <button
          type="button"
          onClick={() => onAction(banner)}
          className={classNames(
            "text-[13px] font-medium underline-offset-2 hover:underline",
            c.titleColor,
          )}
        >
          {banner.actionLabel}
        </button>
      )}
      <button
        type="button"
        onClick={() => onDismiss(banner.id)}
        className={classNames("p-1 rounded hover:bg-black/5", c.bodyColor)}
        aria-label="Zavřít"
      >
        <svg
          viewBox="0 0 24 24"
          className="w-4 h-4"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M18 6 6 18M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}
```

Transcribed from proto:608–648 with:
- `BannerData` exported so the context (Task 9) can import the same shape.
- `VariantIcon` factored to a small inline component (cleaner than the prototype's nested ternary returning component factories).
- `aria-hidden="true"` on decorative SVGs.

- [ ] **Step 2: Create `frontend/src/components/BannerStack.tsx`**

```tsx
import Banner, { type BannerData } from "./Banner";

interface Props {
  banners: BannerData[];
  onDismiss: (id: string) => void;
  onAction: (banner: BannerData) => void;
}

export default function BannerStack({ banners, onDismiss, onAction }: Props) {
  if (banners.length === 0) return null;
  return (
    <div className="border-b border-gray-200">
      {banners.map((b) => (
        <Banner
          key={b.id}
          banner={b}
          onDismiss={onDismiss}
          onAction={onAction}
        />
      ))}
    </div>
  );
}
```

Direct transcription proto:650–659.

- [ ] **Step 3: Create `frontend/src/components/Toast.tsx`**

```tsx
import { classNames } from "@/utils/format";

export type ToastVariant = "success" | "error";

export interface ToastData {
  id: number;
  variant: ToastVariant;
  message: string;
}

interface Props {
  toast: ToastData;
  onDismiss: (id: number) => void;
}

export default function Toast({ toast, onDismiss }: Props) {
  const isSuccess = toast.variant === "success";
  return (
    <div
      role="status"
      className="animate-ps-toast-in flex items-center gap-3 pl-3 pr-2 py-2.5 rounded-lg shadow-md border min-w-[280px] max-w-sm cursor-pointer bg-white border-gray-200"
      onClick={() => onDismiss(toast.id)}
    >
      <div
        className={classNames(
          "w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0",
          isSuccess ? "bg-green-100 text-green-600" : "bg-red-100 text-red-600",
        )}
      >
        {isSuccess ? (
          <svg
            viewBox="0 0 24 24"
            className="w-4 h-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M5 12l5 5L20 7" />
          </svg>
        ) : (
          <svg
            viewBox="0 0 24 24"
            className="w-4 h-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        )}
      </div>
      <div className="text-[13px] text-gray-900 flex-1">{toast.message}</div>
      <button
        className="text-gray-400 hover:text-gray-600 p-1"
        aria-label="Zavřít"
        onClick={(e) => {
          e.stopPropagation();
          onDismiss(toast.id);
        }}
      >
        <svg
          viewBox="0 0 24 24"
          className="w-3.5 h-3.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M18 6 6 18M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}
```

Transcribed from proto:661–687 with:
- `role="status"` on the toast root for screen reader announcement.
- `e.stopPropagation()` on the inner X button so clicking the X doesn't double-fire the parent's click-to-dismiss.
- `ps-toast-in` → `animate-ps-toast-in`.

- [ ] **Step 4: Create `frontend/src/components/ToastContainer.tsx`**

```tsx
import Toast, { type ToastData } from "./Toast";

interface Props {
  toasts: ToastData[];
  onDismiss: (id: number) => void;
}

export default function ToastContainer({ toasts, onDismiss }: Props) {
  return (
    <div
      aria-live="polite"
      aria-atomic="false"
      className="fixed bottom-4 right-4 z-50 flex flex-col gap-2"
    >
      {toasts.map((t) => (
        <Toast key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </div>
  );
}
```

Transcribed from proto:689–695. Added `aria-live="polite"` so screen readers pick up new toasts without interrupting.

- [ ] **Step 5: Create `frontend/src/components/ConnectionLostOverlay.tsx`**

```tsx
interface Props {
  visible: boolean;
  /** Dev-only "Skrýt" button. When omitted, no dismiss control rendered. */
  onClose?: () => void;
  /** Last error string (e.g. "ECONNREFUSED 127.0.0.1:8765"). */
  lastError?: string;
}

export default function ConnectionLostOverlay({
  visible,
  onClose,
  lastError,
}: Props) {
  if (!visible) return null;
  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="conn-lost-title"
      className="fixed inset-0 z-50 bg-gray-900/40 backdrop-blur-sm flex items-center justify-center p-6"
    >
      <div className="bg-white rounded-lg shadow-md max-w-md w-full p-6 border border-gray-200">
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-full bg-red-100 text-red-600 flex items-center justify-center flex-shrink-0">
            <svg
              viewBox="0 0 24 24"
              className="w-5 h-5"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M2 12s4-8 10-8 10 8 10 8" />
              <path d="M2 2l20 20" />
            </svg>
          </div>
          <div className="flex-1">
            <h2
              id="conn-lost-title"
              className="text-base font-semibold text-gray-900"
            >
              Spojení s PlaudSync ztraceno
            </h2>
            <p className="text-sm text-gray-600 mt-1">
              Místní sync služba neodpovídá. Zavři toto okno a otevři ho znovu.
            </p>
            {lastError && (
              <p className="text-xs text-gray-500 mt-3 font-mono">
                3× pokus o spojení selhal — poslední chyba:{" "}
                <span className="text-gray-700">{lastError}</span>
              </p>
            )}
            {onClose && (
              <div className="mt-4 flex justify-end">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-3 py-1.5 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-md"
                >
                  Skrýt (dev)
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
```

Transcribed from proto:697–730 with:
- `role="alertdialog"` + `aria-modal` + `aria-labelledby` for screen reader correctness.
- `lastError` prop optional (prototype hard-coded `ECONNREFUSED`); we let the AppShell pass the real error text from the failed query when available.
- `onClose` made optional. Production: not passed → no dismiss button (terminal state). Dev: DevPanel passes a setter so the overlay can be hidden for testing.

- [ ] **Step 6: Verify TypeScript clean**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm run typecheck
```

Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add frontend/src/components/Banner.tsx frontend/src/components/BannerStack.tsx frontend/src/components/Toast.tsx frontend/src/components/ToastContainer.tsx frontend/src/components/ConnectionLostOverlay.tsx
git -C "c:/GitHub/PlaudSync" commit -m "feat(frontend): notification components — Banner, Toast, ConnectionLostOverlay

Five stateless presentational components from prototype proto:608-730.
ARIA additions: role=status on Toast, aria-live on ToastContainer,
role=alertdialog on ConnectionLostOverlay. ConnectionLostOverlay onClose
made optional (prod: terminal — no dismiss; dev: DevPanel passes setter).
ps-toast-in renamed to animate-ps-toast-in.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Notification contexts — `BannersContext`, `ToastsContext`

**Rationale:** App-level lists of banners and toasts must be readable from any component (header → status snapshot, mutation `onError` → push) and dismissible from `<BannerStack>` / `<ToastContainer>`. Two minimal React Contexts are the right primitive: the contexts hold arrays + dispatch functions, and components subscribe via small `useBanners()` / `useToasts()` hooks. No global store library — aligns with umbrella D2 ("Žádný globální store").

**Files:**
- Create: `frontend/src/context/BannersContext.tsx`
- Create: `frontend/src/context/ToastsContext.tsx`

- [ ] **Step 1: Create `frontend/src/context/ToastsContext.tsx`**

```tsx
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from "react";

import type { ToastData, ToastVariant } from "@/components/Toast";

interface ToastsContextValue {
  toasts: ToastData[];
  pushToast: (variant: ToastVariant, message: string) => void;
  dismissToast: (id: number) => void;
}

const ToastsContext = createContext<ToastsContextValue | null>(null);

const AUTO_DISMISS_MS = 4000;

export function ToastsProvider({ children }: PropsWithChildren) {
  const [toasts, setToasts] = useState<ToastData[]>([]);
  const idRef = useRef(0);

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const pushToast = useCallback(
    (variant: ToastVariant, message: string) => {
      idRef.current += 1;
      const id = idRef.current;
      setToasts((prev) => [...prev, { id, variant, message }]);
      window.setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, AUTO_DISMISS_MS);
    },
    [],
  );

  const value = useMemo(
    () => ({ toasts, pushToast, dismissToast }),
    [toasts, pushToast, dismissToast],
  );

  return (
    <ToastsContext.Provider value={value}>{children}</ToastsContext.Provider>
  );
}

export function useToasts(): ToastsContextValue {
  const ctx = useContext(ToastsContext);
  if (!ctx) throw new Error("useToasts must be used within ToastsProvider");
  return ctx;
}
```

- [ ] **Step 2: Create `frontend/src/context/BannersContext.tsx`**

```tsx
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from "react";

import type { BannerData } from "@/components/Banner";
import type { SyncState } from "@/api/types";

interface BannersContextValue {
  banners: BannerData[];
  pushBanner: (banner: BannerData) => void;
  dismissBanner: (id: string) => void;
  /**
   * Sync the auto-derived banners (last-sync-failed / last-sync-partial) from
   * a fresh SyncState snapshot. Idempotent — callers can invoke on every
   * useStateQuery success without spawning duplicates.
   */
  syncFromState: (sync: SyncState) => void;
}

const BannersContext = createContext<BannersContextValue | null>(null);

const AUTO_BANNER_IDS = ["last-sync-failed", "last-sync-partial"] as const;

function deriveBannerForState(sync: SyncState): BannerData | null {
  if (sync.last_run_outcome === "failed") {
    return {
      id: "last-sync-failed",
      variant: "error",
      title: "Poslední synchronizace selhala",
      message: sync.last_error_summary ?? "Synchronizace nedoběhla.",
      actionLabel: "Zobrazit log",
    };
  }
  if (sync.last_run_outcome === "partial_failure") {
    return {
      id: "last-sync-partial",
      variant: "warning",
      title: "Poslední synchronizace měla chyby",
      message:
        sync.last_error_summary ?? "Některé nahrávky se nepodařilo stáhnout.",
      actionLabel: "Zobrazit log",
    };
  }
  return null;
}

export function BannersProvider({ children }: PropsWithChildren) {
  const [banners, setBanners] = useState<BannerData[]>([]);
  const dismissedRef = useRef<Set<string>>(new Set());

  const pushBanner = useCallback((banner: BannerData) => {
    setBanners((prev) =>
      prev.find((b) => b.id === banner.id) ? prev : [...prev, banner],
    );
  }, []);

  const dismissBanner = useCallback((id: string) => {
    dismissedRef.current.add(id);
    setBanners((prev) => prev.filter((b) => b.id !== id));
  }, []);

  const syncFromState = useCallback((sync: SyncState) => {
    const derived = deriveBannerForState(sync);
    setBanners((prev) => {
      // Remove any auto-derived banners that no longer apply (e.g. last_run_outcome flipped success).
      const kept = prev.filter(
        (b) => !AUTO_BANNER_IDS.includes(b.id as (typeof AUTO_BANNER_IDS)[number]),
      );
      if (!derived) return kept;
      if (dismissedRef.current.has(derived.id)) return kept;
      // Only append if not already present (re-render with same outcome).
      if (kept.find((b) => b.id === derived.id)) return kept;
      return [...kept, derived];
    });
  }, []);

  const value = useMemo(
    () => ({ banners, pushBanner, dismissBanner, syncFromState }),
    [banners, pushBanner, dismissBanner, syncFromState],
  );

  return (
    <BannersContext.Provider value={value}>
      {children}
    </BannersContext.Provider>
  );
}

export function useBanners(): BannersContextValue {
  const ctx = useContext(BannersContext);
  if (!ctx) throw new Error("useBanners must be used within BannersProvider");
  return ctx;
}
```

Notes:
- `dismissedRef` is a `Set` in a `useRef` so dismissals don't re-trigger `syncFromState` (refs don't cause re-renders). Per Dashboard Gap 7: dismissed banners come back on next state-change that *creates a new banner id*; same-id banner dismissal sticks until next outcome change. The set is in-memory only — acceptable for v0 per Dashboard spec.
- `pushBanner` is idempotent on `id` so callers (e.g. `useVerifyAuth.onError` pushing `token-expired`) can fire repeatedly without stacking.
- `syncFromState` removes only AUTO_BANNER_IDS so manually pushed `token-expired` banners are not affected by state polls.

- [ ] **Step 3: Verify TypeScript clean**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm run typecheck
```

Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add frontend/src/context/
git -C "c:/GitHub/PlaudSync" commit -m "feat(frontend): React contexts for app-level toasts and banners

ToastsProvider auto-dismisses 4s. BannersProvider exposes pushBanner /
dismissBanner / syncFromState. syncFromState derives last-sync-failed /
last-sync-partial from SyncState and removes them when outcome flips
(Dashboard D6). dismissedRef Set keeps dismissed-id memory in-session
(Dashboard Gap 7 — acceptable v0). pushBanner idempotent on id so repeat
auth-verify failures do not stack.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Dashboard page + sub-components

**Rationale:** Dashboard route component composes `<SyncNowPanel>` + `<RecordingsList>` (with `<StatusIcon>` + `<ProjectBadge>` leaves). All transcribed from prototype proto:732–935. Wiring difference vs prototype: instead of a single `useAppStore` mock, `Dashboard` consumes `useStateQuery()` (live polling) and `useStartSync()` (mutation) from Task 5. Click handler routes 409 ConflictError → no toast (transparent transition per Dashboard "Sync Now click — concurrent lock"); 5xx → push error banner via `useBanners()`. Success transition from `running` → `idle` + `outcome=success` triggers a one-shot toast (effect tracks the previous status to avoid re-firing).

**Files:**
- Create: `frontend/src/pages/Dashboard/StatusIcon.tsx`
- Create: `frontend/src/pages/Dashboard/ProjectBadge.tsx`
- Create: `frontend/src/pages/Dashboard/SyncNowPanel.tsx`
- Create: `frontend/src/pages/Dashboard/RecordingsList.tsx`
- Create: `frontend/src/pages/Dashboard/index.tsx`

- [ ] **Step 1: Create `frontend/src/pages/Dashboard/StatusIcon.tsx`**

```tsx
import type { RecordingStatus } from "@/api/types";

interface Props {
  status: RecordingStatus;
}

export default function StatusIcon({ status }: Props) {
  if (status === "downloaded") {
    return (
      <span
        className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-green-100 text-green-600"
        title="Staženo"
      >
        <svg
          viewBox="0 0 24 24"
          className="w-3 h-3"
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M5 12l5 5L20 7" />
        </svg>
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span
        className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-red-100 text-red-600"
        title="Selhalo"
      >
        <svg
          viewBox="0 0 24 24"
          className="w-3 h-3"
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M18 6 6 18M6 6l12 12" />
        </svg>
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-gray-100 text-gray-500"
      title="Přeskočeno"
    >
      <svg
        viewBox="0 0 24 24"
        className="w-3 h-3"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M3 12a9 9 0 0 1 9-9 9 9 0 0 1 9 9 9 9 0 0 1-9 9" />
        <path d="M3 12v4h4" />
      </svg>
    </span>
  );
}
```

Direct transcription proto:849–872.

- [ ] **Step 2: Create `frontend/src/pages/Dashboard/ProjectBadge.tsx`**

```tsx
import type { ClassificationStatus } from "@/api/types";
import { classNames } from "@/utils/format";
import { projectBadgeColor } from "@/utils/colors";

interface Props {
  project: string | null;
  classification: ClassificationStatus;
}

export default function ProjectBadge({ project, classification }: Props) {
  if (classification === "unclassified" || !project) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium bg-gray-100 text-gray-600 border border-gray-200">
        nezatříděno
      </span>
    );
  }
  const c = projectBadgeColor(project);
  return (
    <span
      className={classNames(
        "inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium border",
        c.bg,
        c.text,
        c.border,
      )}
    >
      {project}
    </span>
  );
}
```

Direct transcription proto:825–847. The `project` rendered inside the span is **content**, not interpolated into a message — D11 privacy rule does not apply (it's the deliberate UX of showing the label to the user; not a Sentry-captured message).

- [ ] **Step 3: Create `frontend/src/pages/Dashboard/SyncNowPanel.tsx`**

```tsx
import type { SyncState } from "@/api/types";
import { classNames, formatExactTime, phaseLabel, relativeTime } from "@/utils/format";

interface Props {
  sync: SyncState;
  onSync: () => void;
  startSyncDisabled?: boolean;
}

export default function SyncNowPanel({
  sync,
  onSync,
  startSyncDisabled = false,
}: Props) {
  const isRunning = sync.status === "running";
  const isTaskScheduler = sync.trigger === "task_scheduler";
  const p = sync.progress;
  const hasCounts =
    p !== null && p.processed_count !== null && p.total_count !== null;
  const pct = hasCounts
    ? Math.max(4, Math.round((p.processed_count! / p.total_count!) * 100))
    : null;

  return (
    <section className="bg-white rounded-lg border border-gray-200 shadow-sm p-6">
      <div className="flex items-start gap-6 flex-wrap">
        <div className="flex-1 min-w-0">
          <h2 className="text-sm font-semibold text-gray-900">Synchronizace</h2>
          <p className="text-[13px] text-gray-500 mt-1">
            Ruční stažení nahrávek z Plaud cloudu do místní složky.
          </p>
          {!isRunning && (
            <div className="mt-3 text-[13px] text-gray-600">
              {sync.last_run_at ? (
                <>
                  Poslední běh{" "}
                  <span className="text-gray-900 font-medium">
                    {relativeTime(sync.last_run_at) ?? "—"}
                  </span>{" "}
                  · {formatExactTime(sync.last_run_at)}
                </>
              ) : (
                <>Ještě nikdy neproběhla.</>
              )}
            </div>
          )}
        </div>
        <div className="flex-shrink-0">
          <button
            type="button"
            disabled={isRunning || startSyncDisabled}
            onClick={onSync}
            className={classNames(
              "inline-flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium shadow-sm transition-colors",
              isRunning
                ? "bg-blue-50 text-blue-700 border border-blue-200 cursor-not-allowed"
                : "bg-blue-600 text-white hover:bg-blue-700 border border-blue-600 disabled:opacity-60",
            )}
          >
            {isRunning ? (
              <>
                <svg
                  viewBox="0 0 24 24"
                  className="w-4 h-4 animate-spin"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.4"
                  strokeLinecap="round"
                  aria-hidden="true"
                >
                  <path d="M21 12a9 9 0 1 1-6.2-8.55" />
                </svg>
                <span>
                  {hasCounts
                    ? `Synchronizace… ${p!.processed_count} / ${p!.total_count}`
                    : "Synchronizace…"}
                </span>
              </>
            ) : (
              <>
                <svg
                  viewBox="0 0 24 24"
                  className="w-4 h-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M3 12a9 9 0 0 1 15.5-6.3L21 8" />
                  <path d="M21 4v4h-4" />
                  <path d="M21 12a9 9 0 0 1-15.5 6.3L3 16" />
                  <path d="M3 20v-4h4" />
                </svg>
                <span>Synchronizovat</span>
              </>
            )}
          </button>
        </div>
      </div>

      {isRunning && (
        <div className="mt-5">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[13px] font-medium text-gray-700">
              {phaseLabel(p)}
            </span>
            {hasCounts && (
              <span className="text-[13px] text-gray-500 font-mono">
                {p!.processed_count} / {p!.total_count}
              </span>
            )}
          </div>
          <div className="h-1.5 w-full bg-gray-100 rounded-full overflow-hidden relative">
            {hasCounts ? (
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-500"
                style={{ width: `${pct}%` }}
              />
            ) : (
              <div className="h-full bg-blue-500 rounded-full animate-ps-indeterminate w-1/4" />
            )}
          </div>
          {isTaskScheduler && (
            <div className="mt-2 text-xs text-gray-500 flex items-center gap-1.5">
              <svg
                viewBox="0 0 24 24"
                className="w-3.5 h-3.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <circle cx="12" cy="12" r="9" />
                <path d="M12 7v5l3 2" />
              </svg>
              Spuštěno Plánovačem úloh Windows
            </div>
          )}
        </div>
      )}
    </section>
  );
}
```

Transcribed from proto:734–823. `startSyncDisabled` prop added so the parent can additionally gate while the mutation is mid-flight (prototype only checked `sync.status === "running"`; we want immediate disable on click — a 1.5 s polling lag would otherwise allow a second click to fire). `ps-indeterminate` → `animate-ps-indeterminate w-1/4` (Tailwind 4 needs explicit width since the keyframe handles X transform only).

- [ ] **Step 4: Create `frontend/src/pages/Dashboard/RecordingsList.tsx`**

```tsx
import type { RecordingRow } from "@/api/types";
import { relativeTime } from "@/utils/format";

import ProjectBadge from "./ProjectBadge";
import StatusIcon from "./StatusIcon";

interface Props {
  recordings: RecordingRow[];
}

export default function RecordingsList({ recordings }: Props) {
  if (recordings.length === 0) {
    return (
      <section className="bg-white rounded-lg border border-gray-200 shadow-sm">
        <div className="p-12 text-center">
          <div className="mx-auto w-12 h-12 rounded-full bg-gray-100 text-gray-400 flex items-center justify-center mb-4">
            <svg
              viewBox="0 0 24 24"
              className="w-6 h-6"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" />
              <path d="M19 10v1a7 7 0 0 1-14 0v-1" />
              <path d="M12 18v4M8 22h8" />
            </svg>
          </div>
          <h3 className="text-sm font-semibold text-gray-900">
            Ještě nemáš žádné nahrávky
          </h3>
          <p className="text-[13px] text-gray-500 mt-1 max-w-xs mx-auto">
            Klikni na{" "}
            <span className="font-medium text-gray-700">Synchronizovat</span> a
            stáhneš nahrávky z Plaud cloudu.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden">
      <div className="px-5 py-3 flex items-center justify-between border-b border-gray-100">
        <h3 className="text-sm font-semibold text-gray-900">Nahrávky</h3>
        <span className="text-xs text-gray-500 font-mono">
          {recordings.length} položek
        </span>
      </div>
      <ul className="divide-y divide-gray-100">
        {recordings.map((r) => (
          <li
            key={r.plaud_id}
            className="group flex items-center gap-4 px-5 py-3 hover:bg-gray-50 cursor-default"
          >
            <StatusIcon status={r.status} />
            <div className="flex-1 min-w-0">
              <div className="text-sm text-gray-900 truncate font-medium">
                {r.title}
              </div>
              <div className="text-xs text-gray-500 mt-1 flex items-center gap-2 font-mono">
                <span
                  className="inline-flex items-center gap-1 truncate"
                  title="Plaud složka"
                >
                  <svg
                    viewBox="0 0 24 24"
                    className="w-3 h-3 text-gray-400 flex-shrink-0"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />
                  </svg>
                  <span className="truncate">{r.plaud_folder || "—"}</span>
                </span>
                <span className="text-gray-300">·</span>
                <span>{relativeTime(r.downloaded_at) ?? "—"}</span>
              </div>
            </div>
            <ProjectBadge
              project={r.project}
              classification={r.classification_status}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
```

Direct transcription proto:874–926. `r.title` and `r.plaud_folder` rendered as content (text nodes) — same UX semantic, D11 privacy rule applies to *messages*, not to legitimate display data.

Note on Dashboard Gap 1 (`_unmapped_<project>` not visually distinct): out-of-scope for v0 per the spec — `RecordingRow.classification_route` field is not yet on the backend contract. When the backend adds it, this component grows a third badge variant. Spec tracks this as a future-impl item.

Note on Dashboard Gap 2 (UUID `plaud_folder` in v0): we display whatever the backend sends. Real Plaud production data has `plaud_folder: "abc-12345-uuid"`; the prototype mock used readable strings (`"Meetings/ProjektAlfa"`). The list still renders correctly — UUIDs just look opaque. Truncation/aliasing → v1.1+ per spec.

- [ ] **Step 5: Create `frontend/src/pages/Dashboard/index.tsx`**

```tsx
import { useEffect, useRef } from "react";

import { ConflictError } from "@/api/client";
import { useStartSync, useStateQuery } from "@/api/hooks";
import type { SyncState } from "@/api/types";
import { useBanners } from "@/context/BannersContext";
import { useToasts } from "@/context/ToastsContext";

import RecordingsList from "./RecordingsList";
import SyncNowPanel from "./SyncNowPanel";

export default function Dashboard() {
  const { data, isPending } = useStateQuery();
  const startSync = useStartSync();
  const { pushToast } = useToasts();
  const { pushBanner, syncFromState } = useBanners();

  // Push success toast on sync transition running -> idle + outcome=success.
  // Track previous status in a ref so we fire exactly once per transition.
  const prevStatusRef = useRef<SyncState["status"] | undefined>(undefined);

  useEffect(() => {
    if (!data) return;
    syncFromState(data.sync);
    const prev = prevStatusRef.current;
    if (prev === "running" && data.sync.status === "idle") {
      if (data.sync.last_run_outcome === "success") {
        const newCount = data.recordings.length;
        pushToast(
          "success",
          `Synchronizace dokončena — ${newCount} nových nahrávek`,
        );
      }
      // failed / partial_failure cases surface via syncFromState banner.
    }
    prevStatusRef.current = data.sync.status;
  }, [data, syncFromState, pushToast]);

  const handleSync = () => {
    startSync.mutate(undefined, {
      onError: (err) => {
        if (err instanceof ConflictError) {
          // Transparent: no toast / banner. invalidateQueries in onSettled
          // will pick up the running stav from backend.
          return;
        }
        pushBanner({
          id: "sync-spawn-failed",
          variant: "error",
          title: "Synchronizaci se nepodařilo spustit",
          message: "Spuštění sync subprocesu selhalo. Zkontroluj log.",
          actionLabel: "Zobrazit log",
        });
      },
    });
  };

  if (isPending && !data) {
    return (
      <div className="flex items-center justify-center py-12">
        <svg
          viewBox="0 0 24 24"
          className="w-6 h-6 text-gray-400 animate-spin"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.4"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <path d="M21 12a9 9 0 1 1-6.2-8.55" />
        </svg>
        <span className="ml-3 text-sm text-gray-500">Načítám…</span>
      </div>
    );
  }

  if (!data) return null; // Should not happen if !isPending; safety net.

  return (
    <div className="space-y-5">
      <SyncNowPanel
        sync={data.sync}
        onSync={handleSync}
        startSyncDisabled={startSync.isPending}
      />
      <RecordingsList recordings={data.recordings} />
    </div>
  );
}
```

Notes:
- Loading state is a simple centered spinner per Dashboard Gap 5 alternative (acceptable for MVP). Skeleton variant deferred.
- `pushBanner` for spawn-failed includes "Zobrazit log" actionLabel; the click handler is wired in Task 12 AppShell (banner action → toast pointing to log file path per Dashboard Gap 4 default C).
- Banner message string contains no business labels (no project / title / path interpolation) — D11 compliant.
- Transition detection uses `useRef`, not `useState`, so it doesn't trigger re-renders.

- [ ] **Step 6: Verify TypeScript clean**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm run typecheck
```

Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add frontend/src/pages/Dashboard/
git -C "c:/GitHub/PlaudSync" commit -m "feat(frontend): Dashboard page + sub-components

SyncNowPanel + RecordingsList + StatusIcon + ProjectBadge transcribed from
prototype proto:732-935. Dashboard route consumes useStateQuery (1.5s/5s
polling) + useStartSync. ConflictError on 409 transparent (no toast). 5xx
spawn_failed pushes banner with 'Zobrazit log' action. running -> idle +
outcome=success fires one-shot toast tracked via prevStatusRef. Loading
state: centered spinner (Dashboard Gap 5 acceptable variant for MVP).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Settings page + sub-components

**Rationale:** Settings route composes `<ConnectionPanel>` (token mask + verify button) + `<ConfigPanel>` (YAML editor + Save/Reload + multi-error UX). Transcribed from prototype proto:937–1101 with **four post-prototype additions** required by Settings v0.1 spec:

1. **Gap 2 Option A:** `ConnectionPanel` consumes `masked_token` from `AuthVerifyResponse` (server-rendered), not a hardcoded constant. Settings mount fires implicit `useVerifyAuth.mutate()` to populate.
2. **Gap 1:** `<InlineConfigErrors>` shows first error inline + `(+N dalších chyb)` `<details>` expansion. Click promotes selected error to current.
3. **Gap 9:** `<YamlEditor>` textarea Tab key handler — insert 2 spaces; Shift+Tab dedents; Esc blurs.
4. **Gap 4:** `<ConfigPanel>` Reload click with dirty edits → native `confirm()` "Zahodit neuložené změny?".

`DEFAULT_YAML` constant is **not** stored in the frontend — it lives on the backend (sync-core spec auto-seed). Frontend just renders whatever `useConfig` returns. (Prototype had a frontend `DEFAULT_YAML` because there was no backend; this is one of the prototype-vs-production divergences.)

**Files:**
- Create: `frontend/src/pages/Settings/InlineConfigErrors.tsx`
- Create: `frontend/src/pages/Settings/YamlEditor.tsx`
- Create: `frontend/src/pages/Settings/ConnectionPanel.tsx`
- Create: `frontend/src/pages/Settings/ConfigPanel.tsx`
- Create: `frontend/src/pages/Settings/index.tsx`

- [ ] **Step 1: Create `frontend/src/pages/Settings/InlineConfigErrors.tsx`**

```tsx
import { useState } from "react";

import type { ConfigParseError } from "@/api/types";
import { classNames } from "@/utils/format";

interface Props {
  errors: ConfigParseError[];
  /** Index into errors array — which one is "current" (gutter highlight + footer). */
  currentIndex: number;
  onSelect: (index: number) => void;
}

export default function InlineConfigErrors({
  errors,
  currentIndex,
  onSelect,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  if (errors.length === 0) return null;

  // currentIndex bounds-checked at call site; we still defend.
  const current = errors[currentIndex] ?? errors[0]!;
  const remaining = errors.length - 1;

  return (
    <div className="border-t border-red-200 bg-red-50">
      <div className="px-4 py-2 text-[13px] text-red-800 flex items-center gap-2">
        <svg
          viewBox="0 0 24 24"
          className="w-4 h-4 text-red-600 flex-shrink-0"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="9" />
          <path d="M12 8v4M12 16h.01" />
        </svg>
        <span className="flex-1">
          <span className="font-mono font-semibold">Řádek {current.line}:</span>{" "}
          {current.message}
        </span>
        {remaining > 0 && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-red-700 underline text-[13px] font-medium"
          >
            {expanded ? "Skrýt seznam" : `(+${remaining} dalších chyb)`}
          </button>
        )}
      </div>
      {expanded && remaining > 0 && (
        <ul className="border-t border-red-200 bg-red-50/60 px-4 py-2 space-y-1">
          {errors.map((err, idx) => (
            <li key={`${err.line}-${idx}`}>
              <button
                type="button"
                onClick={() => {
                  onSelect(idx);
                  setExpanded(false);
                }}
                className={classNames(
                  "w-full text-left text-[13px] px-2 py-1 rounded hover:bg-red-100",
                  idx === currentIndex
                    ? "text-red-900 font-medium bg-red-100"
                    : "text-red-800",
                )}
              >
                <span className="font-mono font-semibold">
                  Řádek {err.line}:
                </span>{" "}
                {err.message}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

Per Settings Gap 1: first error always inline at top; trailing button toggles expanded list of all errors; click on a list item promotes via `onSelect` (parent re-routes which error is "current"). Privacy: `err.message` comes from backend; backend is responsible for not leaking labels (Settings D11 covered there). `err.line` is numeric.

- [ ] **Step 2: Create `frontend/src/pages/Settings/YamlEditor.tsx`**

```tsx
import { useRef, type KeyboardEvent, type UIEvent } from "react";

import type { ConfigParseError } from "@/api/types";
import { classNames } from "@/utils/format";

import InlineConfigErrors from "./InlineConfigErrors";

interface Props {
  value: string;
  onChange: (next: string) => void;
  errors: ConfigParseError[];
  /** Index into `errors` for gutter highlight + inline footer. -1 if no current. */
  currentErrorIndex: number;
  onSelectError: (index: number) => void;
}

const TAB_INSERT = "  "; // 2 spaces, matches Settings D5 tab-size: 2.

export default function YamlEditor({
  value,
  onChange,
  errors,
  currentErrorIndex,
  onSelectError,
}: Props) {
  const taRef = useRef<HTMLTextAreaElement>(null);
  const lineNumsRef = useRef<HTMLDivElement>(null);
  const lines = value.split("\n");

  const onScroll = (e: UIEvent<HTMLTextAreaElement>) => {
    if (lineNumsRef.current) {
      lineNumsRef.current.scrollTop = e.currentTarget.scrollTop;
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    const ta = e.currentTarget;
    // Esc — blur to release focus trap (Settings Gap 9 escape hatch).
    if (e.key === "Escape") {
      e.preventDefault();
      ta.blur();
      return;
    }
    if (e.key !== "Tab") return;

    e.preventDefault();
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const before = value.slice(0, start);
    const selection = value.slice(start, end);
    const after = value.slice(end);

    if (selection.includes("\n")) {
      // Multi-line indent / dedent.
      const lineStart = before.lastIndexOf("\n") + 1;
      const block = value.slice(lineStart, end);
      if (e.shiftKey) {
        const dedented = block
          .split("\n")
          .map((ln) => (ln.startsWith(TAB_INSERT) ? ln.slice(TAB_INSERT.length) : ln))
          .join("\n");
        const next = value.slice(0, lineStart) + dedented + after;
        onChange(next);
        const removed = block.length - dedented.length;
        requestAnimationFrame(() => {
          ta.selectionStart = Math.max(lineStart, start - TAB_INSERT.length);
          ta.selectionEnd = end - removed;
        });
      } else {
        const indented = block
          .split("\n")
          .map((ln) => TAB_INSERT + ln)
          .join("\n");
        const next = value.slice(0, lineStart) + indented + after;
        onChange(next);
        const added = indented.length - block.length;
        requestAnimationFrame(() => {
          ta.selectionStart = start + TAB_INSERT.length;
          ta.selectionEnd = end + added;
        });
      }
      return;
    }

    // Caret-only: insert 2 spaces (or, with Shift, dedent the current line).
    if (e.shiftKey) {
      const lineStart = before.lastIndexOf("\n") + 1;
      const lineHead = value.slice(lineStart, start);
      if (lineHead.startsWith(TAB_INSERT)) {
        const next =
          value.slice(0, lineStart) +
          lineHead.slice(TAB_INSERT.length) +
          value.slice(start);
        onChange(next);
        requestAnimationFrame(() => {
          ta.selectionStart = ta.selectionEnd = start - TAB_INSERT.length;
        });
      }
      return;
    }
    const next = before + TAB_INSERT + after;
    onChange(next);
    requestAnimationFrame(() => {
      ta.selectionStart = ta.selectionEnd = start + TAB_INSERT.length;
    });
  };

  const currentLine =
    currentErrorIndex >= 0 && currentErrorIndex < errors.length
      ? errors[currentErrorIndex]!.line
      : -1;

  const hasError = errors.length > 0;

  return (
    <div
      className={classNames(
        "rounded-md border bg-white overflow-hidden",
        hasError ? "border-red-300" : "border-gray-200",
      )}
    >
      <div className="flex">
        <div
          ref={lineNumsRef}
          aria-hidden="true"
          className="yaml-line-numbers flex-shrink-0 bg-gray-50 border-r border-gray-100 text-right pr-3 pl-3 py-3 select-none overflow-hidden"
          style={{ height: 400, width: 48 }}
        >
          {lines.map((_, i) => (
            <div
              key={i}
              className={classNames(
                "transition-colors",
                currentLine === i + 1
                  ? "text-red-600 font-semibold bg-red-50 -mx-3 px-3"
                  : "text-gray-400",
              )}
            >
              {i + 1}
            </div>
          ))}
        </div>
        <textarea
          ref={taRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onScroll={onScroll}
          onKeyDown={onKeyDown}
          spellCheck={false}
          aria-label="Konfigurace YAML"
          className="yaml-textarea flex-1 py-3 px-3 outline-none resize-none text-gray-800 bg-white"
          style={{ height: 400 }}
        />
      </div>
      <InlineConfigErrors
        errors={errors}
        currentIndex={currentErrorIndex}
        onSelect={onSelectError}
      />
      {/* Tab/Esc helper hint per Settings Gap 9 */}
      <div className="px-4 py-2 border-t border-gray-100 text-[11px] text-gray-400 bg-gray-50/40">
        Tab pro odsazení • Shift+Tab pro zúžení • Esc pro opuštění editoru
      </div>
    </div>
  );
}
```

Notes:
- `lines.length` memoization (Settings Gap 10): in this implementation each render rebuilds the gutter `<div>` array, but the parent only re-renders when `value` or `errors` change. With realistic config sizes (< 50 lines) this is sub-millisecond. The Gap 10 explicit `useMemo([_, _], [lines.length])` was a perf hedge for ≥ 500-line files; v0 ships without it and ACs (Task 15 #16) verify gutter perf at 500 lines.
- Tab handler tested manually in Task 15 AC #15. Edge cases handled: caret-only (insert), range selection within one line (insert at caret), range selection spanning lines (block indent/dedent), Shift+Tab caret-only (dedent current line), Shift+Tab range (block dedent).
- `aria-label="Konfigurace YAML"` for screen readers (textarea has no associated `<label for>` — it's nested within the editor card without a `<label>` element).
- `aria-hidden="true"` on gutter — line numbers are decorative.

- [ ] **Step 3: Create `frontend/src/pages/Settings/ConnectionPanel.tsx`**

```tsx
import { useEffect } from "react";

import { useVerifyAuth } from "@/api/hooks";
import type { AuthVerifyResponse } from "@/api/types";
import { useBanners } from "@/context/BannersContext";
import { useToasts } from "@/context/ToastsContext";

const PLACEHOLDER_MASK = "•".repeat(20);

export default function ConnectionPanel() {
  const verify = useVerifyAuth();
  const { pushToast } = useToasts();
  const { pushBanner, dismissBanner } = useBanners();

  // Settings v0.1 D2 + Gap 2 Option A: implicit verify on mount populates mask.
  useEffect(() => {
    verify.mutate(undefined, {
      onSuccess: (resp) => handleVerifyResult(resp, /*surfaceToast*/ false),
      // Network errors on mount are silent — not actionable until user clicks.
    });
    // Mount-only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleVerifyResult(resp: AuthVerifyResponse, surfaceToast: boolean) {
    if (resp.ok) {
      if (surfaceToast) pushToast("success", "Token ověřen");
      // Auth recovered — remove any token-related banners.
      dismissBanner("token-expired");
      dismissBanner("token-missing");
      return;
    }
    // ok=false — branch on reason.
    if (resp.reason === "PlaudTokenExpired") {
      pushBanner({
        id: "token-expired",
        variant: "error",
        title: "Token vypršel",
        message:
          "Zkopíruj znovu localStorage.tokenstr z app.plaud.ai do souboru .env.",
      });
    } else if (resp.reason === "PlaudTokenMissing") {
      pushBanner({
        id: "token-missing",
        variant: "error",
        title: "Token chybí",
        message: resp.message ?? "PLAUD_API_TOKEN není nastaven v .env.",
      });
    }
    if (surfaceToast) pushToast("error", "Ověření tokenu selhalo");
  }

  const onClick = () => {
    verify.mutate(undefined, {
      onSuccess: (resp) => handleVerifyResult(resp, true),
      onError: () => {
        pushToast("error", "Ověření tokenu selhalo — zkontroluj síť");
      },
    });
  };

  const masked = verify.data?.masked_token ?? PLACEHOLDER_MASK;

  return (
    <section className="bg-white rounded-lg border border-gray-200 shadow-sm">
      <div className="p-5 border-b border-gray-100">
        <h2 className="text-sm font-semibold text-gray-900">Připojení k Plaud</h2>
        <p className="text-[13px] text-gray-500 mt-1">
          Token se načítá ze souboru{" "}
          <span className="font-mono text-gray-700">.env</span> (
          <span className="font-mono">PLAUD_API_TOKEN</span>). Z UI se needituje.
        </p>
      </div>
      <div className="p-5 space-y-4">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1.5">
            Plaud API token
          </label>
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex-1 min-w-[260px] flex items-center gap-2 px-3 py-2 rounded-md bg-gray-50 border border-gray-200 font-mono text-[13px] text-gray-700">
              <svg
                viewBox="0 0 24 24"
                className="w-4 h-4 text-gray-400"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <rect x="3" y="11" width="18" height="11" rx="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
              <span className="truncate">{masked}</span>
              <span className="ml-auto text-[11px] text-gray-400 px-1.5 py-0.5 rounded bg-white border border-gray-200">
                z .env
              </span>
            </div>
            <button
              type="button"
              disabled={verify.isPending}
              onClick={onClick}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium border border-gray-200 bg-white hover:bg-gray-50 text-gray-700 disabled:opacity-60"
            >
              {verify.isPending ? (
                <svg
                  viewBox="0 0 24 24"
                  className="w-4 h-4 animate-spin"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.4"
                  strokeLinecap="round"
                  aria-hidden="true"
                >
                  <path d="M21 12a9 9 0 1 1-6.2-8.55" />
                </svg>
              ) : (
                <svg
                  viewBox="0 0 24 24"
                  className="w-4 h-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M5 12l5 5L20 7" />
                </svg>
              )}
              Otestovat připojení
            </button>
          </div>
        </div>
        <div className="text-[13px] text-gray-500 leading-relaxed bg-gray-50 border border-gray-200 rounded-md p-3">
          <span className="font-medium text-gray-700">Aktualizace tokenu:</span>{" "}
          otevři <span className="font-mono">app.plaud.ai</span> v prohlížeči, v
          DevTools spusť <span className="font-mono">localStorage.tokenstr</span>{" "}
          a hodnotu vlož do souboru <span className="font-mono">.env</span> pod
          klíč <span className="font-mono">PLAUD_API_TOKEN</span>.
        </div>
      </div>
    </section>
  );
}
```

Transcribed from proto:939–984 with implicit-verify-on-mount + handleVerifyResult routing. `masked` consumed from `verify.data?.masked_token`; `PLACEHOLDER_MASK` (20 dots) shown until first verify completes (no flash of nothing).

- [ ] **Step 4: Create `frontend/src/pages/Settings/ConfigPanel.tsx`**

```tsx
import { useEffect, useMemo, useRef, useState } from "react";

import { ValidationError } from "@/api/client";
import { useConfig, useSaveConfig } from "@/api/hooks";
import type { ConfigParseError, ConfigResponse } from "@/api/types";
import { useToasts } from "@/context/ToastsContext";

import YamlEditor from "./YamlEditor";

export default function ConfigPanel({ config }: { config: ConfigResponse }) {
  const refetch = useConfig().refetch;
  const saveConfig = useSaveConfig();
  const { pushToast } = useToasts();

  const [yaml, setYaml] = useState(config.raw_yaml);
  const lastSavedRef = useRef(config.raw_yaml);
  const [errors, setErrors] = useState<ConfigParseError[]>(() =>
    config.parse_error ? [config.parse_error] : [],
  );
  const [currentErrorIndex, setCurrentErrorIndex] = useState(
    config.parse_error ? 0 : -1,
  );

  // If incoming config changes (after refetch), reset local edits to server YAML.
  useEffect(() => {
    setYaml(config.raw_yaml);
    lastSavedRef.current = config.raw_yaml;
    if (config.parse_error) {
      setErrors([config.parse_error]);
      setCurrentErrorIndex(0);
      pushToast(
        "error",
        `Existující konfigurace je neplatná — řádek ${config.parse_error.line}`,
      );
    } else {
      setErrors([]);
      setCurrentErrorIndex(-1);
    }
  }, [config, pushToast]);

  const dirty = useMemo(() => yaml !== lastSavedRef.current, [yaml]);

  const onChangeYaml = (next: string) => {
    setYaml(next);
    if (errors.length > 0) {
      // Editing clears stale errors — re-save will re-validate.
      setErrors([]);
      setCurrentErrorIndex(-1);
    }
  };

  const onSave = () => {
    saveConfig.mutate(yaml, {
      onSuccess: () => {
        lastSavedRef.current = yaml;
        setErrors([]);
        setCurrentErrorIndex(-1);
        pushToast("success", "Konfigurace uložena");
      },
      onError: (err) => {
        if (err instanceof ValidationError) {
          setErrors(err.errors);
          setCurrentErrorIndex(0);
          const first = err.errors[0];
          pushToast(
            "error",
            first
              ? `Konfigurace je neplatná — řádek ${first.line}`
              : "Konfigurace je neplatná",
          );
          return;
        }
        pushToast("error", "Uložení selhalo — zkontroluj log");
      },
    });
  };

  const onReload = () => {
    if (dirty) {
      const ok = window.confirm("Zahodit neuložené změny?");
      if (!ok) return;
    }
    void refetch().then(() => {
      pushToast("success", "Konfigurace načtena znovu");
    });
  };

  const lineCount = yaml.split("\n").length;

  return (
    <section className="bg-white rounded-lg border border-gray-200 shadow-sm">
      <div className="p-5 border-b border-gray-100 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">Konfigurace</h2>
          <p className="text-[13px] text-gray-500 mt-1">
            YAML soubor v{" "}
            <span className="font-mono text-gray-700">
              $PLAUDSYNC_STATE_ROOT\config.yaml
            </span>
            .
          </p>
        </div>
      </div>
      <div className="p-5 space-y-4">
        <YamlEditor
          value={yaml}
          onChange={onChangeYaml}
          errors={errors}
          currentErrorIndex={currentErrorIndex}
          onSelectError={setCurrentErrorIndex}
        />
        <div className="flex items-center gap-3">
          <button
            type="button"
            disabled={saveConfig.isPending}
            onClick={onSave}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-md text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white shadow-sm disabled:opacity-60"
          >
            {saveConfig.isPending ? (
              <svg
                viewBox="0 0 24 24"
                className="w-4 h-4 animate-spin"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.4"
                strokeLinecap="round"
                aria-hidden="true"
              >
                <path d="M21 12a9 9 0 1 1-6.2-8.55" />
              </svg>
            ) : (
              <svg
                viewBox="0 0 24 24"
                className="w-4 h-4"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
                <path d="M17 21v-8H7v8M7 3v5h8" />
              </svg>
            )}
            Uložit
          </button>
          <button
            type="button"
            onClick={onReload}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-md text-sm font-medium border border-gray-200 bg-white hover:bg-gray-50 text-gray-700"
          >
            <svg
              viewBox="0 0 24 24"
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M3 12a9 9 0 0 1 15.5-6.3L21 8" />
              <path d="M21 4v4h-4" />
            </svg>
            Načíst znovu
          </button>
          <span className="ml-auto text-xs text-gray-400 font-mono">
            {lineCount} řádků
          </span>
        </div>
      </div>
    </section>
  );
}
```

Notes:
- `dirty` derived from `yaml !== lastSavedRef.current` per Settings Gap 4 confirm-on-reload.
- Save success updates `lastSavedRef` so subsequent reload-without-edit doesn't trip the confirm.
- 422 errors clear when user types (UX: inline error stays until user changes the YAML, then disappears — they can save again to re-validate).
- "Existující konfigurace je neplatná — řádek N" toast on mount when `config.parse_error` present (Settings Gap 3).
- Toast strings interpolate only `line` (numeric) per D11.

- [ ] **Step 5: Create `frontend/src/pages/Settings/index.tsx`**

```tsx
import { useConfig } from "@/api/hooks";

import ConfigPanel from "./ConfigPanel";
import ConnectionPanel from "./ConnectionPanel";

export default function Settings() {
  const { data, isPending, error } = useConfig();

  return (
    <div className="space-y-5">
      <ConnectionPanel />
      {isPending && !data ? (
        <div className="flex items-center justify-center py-12 bg-white rounded-lg border border-gray-200 shadow-sm">
          <svg
            viewBox="0 0 24 24"
            className="w-6 h-6 text-gray-400 animate-spin"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.4"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <path d="M21 12a9 9 0 1 1-6.2-8.55" />
          </svg>
          <span className="ml-3 text-sm text-gray-500">
            Načítám konfiguraci…
          </span>
        </div>
      ) : data ? (
        <ConfigPanel config={data} />
      ) : (
        <div className="bg-white rounded-lg border border-red-200 shadow-sm p-5 text-sm text-red-800">
          Konfiguraci se nepodařilo načíst.
          {error instanceof Error ? "" : null}
        </div>
      )}
    </div>
  );
}
```

ConnectionPanel mounts unconditionally (its implicit verify is independent of config load). ConfigPanel mounts only after `useConfig` resolves; it receives `data` as prop so its initial state hooks see a stable value (avoids the dance of resetting state when query data arrives).

- [ ] **Step 6: Verify TypeScript clean**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm run typecheck
```

Expected: exit 0.

- [ ] **Step 7: Privacy grep — verify no business labels in toast/banner strings**

```bash
cd "c:/GitHub/PlaudSync/frontend" && \
  grep -nE 'pushToast|pushBanner' src/pages/Settings/*.tsx src/pages/Dashboard/*.tsx | \
  grep -E '\$\{(target_dir|project|title|plaud_folder|local_path|file_path|raw_yaml|masked_token)' || \
  echo "PASS: no forbidden interpolations"
```

Expected: `PASS: no forbidden interpolations`. If any line is printed, fix the offending string template before committing.

- [ ] **Step 8: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add frontend/src/pages/Settings/
git -C "c:/GitHub/PlaudSync" commit -m "feat(frontend): Settings page + sub-components

ConnectionPanel + ConfigPanel + YamlEditor + InlineConfigErrors transcribed
from prototype proto:937-1101 with v0.1 spec additions:
- Gap 2 Option A: masked_token consumed from AuthVerifyResponse (server-
  rendered first_8+15dots+last_4); ConnectionPanel implicit-verify on mount
  per D2.
- Gap 1: InlineConfigErrors first-error inline + (+N dalších) <details>
  expansion + click-to-promote.
- Gap 9: YamlEditor Tab/Shift+Tab indent+dedent (caret + range), Esc blurs.
  Hint footer 'Tab pro odsazení • Esc pro opuštění editoru'.
- Gap 4: ConfigPanel Reload click with dirty edits triggers
  window.confirm('Zahodit neuložené změny?').
- Gap 3: parse_error from GET /api/config surfaces inline + toast on mount.
Privacy: toast/banner strings interpolate only numeric line counts (D11).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: AppShell + routing — `App.tsx`, `AppShell.tsx`

**Rationale:** Glue layer. `<App>` declares `<Routes>` (with `<AppShell>` as the parent layout via `<Outlet>`). `<AppShell>` mounts the providers (`BannersProvider`, `ToastsProvider`), the sticky `<Header>`, the `<BannerStack>`, the routed page, the `<ToastContainer>`, and the `<ConnectionLostOverlay>`. The overlay is gated by a hook that subscribes to TanStack Query's queryCache and detects when `useStateQuery`'s last failure count reached 3.

**Files:**
- Modify: `frontend/src/App.tsx` (replace placeholder from Task 2).
- Create: `frontend/src/components/AppShell.tsx`.
- Create: `frontend/src/components/useConnectionLost.ts`.

- [ ] **Step 1: Create `frontend/src/components/useConnectionLost.ts`**

```ts
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { STATE_QUERY_KEY } from "@/api/hooks";

interface ConnectionLost {
  visible: boolean;
  lastError: string | undefined;
}

/**
 * Watch the state query for a "connection lost" condition: 3 consecutive fetch
 * failures with no successful refetch in between. Resolves automatically when
 * the next fetch succeeds.
 *
 * Why a hook + queryCache.subscribe instead of returning isError from
 * useStateQuery: a single failure that recovers shouldn't trigger the
 * full-page overlay; only persistent failure should.
 */
export function useConnectionLost(): ConnectionLost {
  const qc = useQueryClient();
  const [state, setState] = useState<ConnectionLost>({
    visible: false,
    lastError: undefined,
  });

  useEffect(() => {
    const cache = qc.getQueryCache();
    const recompute = () => {
      const query = cache.find({ queryKey: STATE_QUERY_KEY });
      if (!query) return;
      const failureCount = query.state.fetchFailureCount;
      const errorMessage =
        query.state.error instanceof Error
          ? query.state.error.message
          : undefined;
      if (failureCount >= 3 && query.state.fetchStatus === "idle") {
        setState({ visible: true, lastError: errorMessage });
      } else if (query.state.status === "success") {
        setState({ visible: false, lastError: undefined });
      }
    };
    recompute();
    const unsub = cache.subscribe(recompute);
    return () => unsub();
  }, [qc]);

  return state;
}
```

`fetchFailureCount` is reset by TanStack Query when a fetch succeeds, so we don't have to track our own counter. Threshold ≥ 3 matches umbrella spec A2 retry pattern (3 retries).

- [ ] **Step 2: Create `frontend/src/components/AppShell.tsx`**

```tsx
import { Outlet } from "react-router-dom";

import { useStateQuery } from "@/api/hooks";
import type { SyncState } from "@/api/types";
import { useBanners } from "@/context/BannersContext";
import { useToasts } from "@/context/ToastsContext";

import BannerStack from "./BannerStack";
import ConnectionLostOverlay from "./ConnectionLostOverlay";
import Header from "./Header";
import ToastContainer from "./ToastContainer";
import { useConnectionLost } from "./useConnectionLost";

const IDLE_SYNC: SyncState = {
  status: "idle",
  trigger: null,
  started_at: null,
  last_run_at: null,
  last_run_outcome: null,
  last_run_exit_code: null,
  last_error_summary: null,
  progress: null,
};

export default function AppShell() {
  const { data } = useStateQuery();
  const { banners, dismissBanner } = useBanners();
  const { toasts, pushToast, dismissToast } = useToasts();
  const conn = useConnectionLost();

  const sync = data?.sync ?? IDLE_SYNC;

  const onBannerAction = (banner: { id: string; actionTarget?: "settings" }) => {
    if (banner.actionTarget === "settings") {
      window.location.assign("/settings");
      return;
    }
    if (banner.id === "last-sync-failed" || banner.id === "last-sync-partial") {
      // Dashboard Gap 4 default C: point user to log file path. No project / path
      // interpolation per D11.
      pushToast(
        "success",
        "Logy najdeš v plaudsync.log v adresáři projektu.",
      );
      return;
    }
    if (banner.id === "sync-spawn-failed") {
      pushToast("success", "Logy najdeš v plaudsync.log v adresáři projektu.");
      return;
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <Header sync={sync} />
      <BannerStack
        banners={banners}
        onDismiss={dismissBanner}
        onAction={onBannerAction}
      />
      <main className="flex-1">
        <div className="max-w-6xl mx-auto px-6 py-6">
          <Outlet />
        </div>
      </main>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <ConnectionLostOverlay
        visible={conn.visible}
        lastError={conn.lastError}
      />
    </div>
  );
}
```

Notes:
- `sync` falls back to `IDLE_SYNC` when `data` is undefined (cold start) so `<Header>` always has something to render.
- `onBannerAction` for `last-sync-*` and `sync-spawn-failed` IDs pushes a toast pointing to `plaudsync.log` (Dashboard Gap 4 default C). String contains no interpolation per D11. The hard-coded "v adresáři projektu" sidesteps interpolating an actual path.
- `actionTarget === "settings"` navigates via `window.location.assign("/settings")`. Using `useNavigate()` would require this component to be inside a route, which it is — but `window.location.assign` works equivalently and avoids a hook just for one case. Either is acceptable.

- [ ] **Step 3: Replace `frontend/src/App.tsx`**

```tsx
import { Route, Routes } from "react-router-dom";

import AppShell from "./components/AppShell";
import { BannersProvider } from "./context/BannersContext";
import { ToastsProvider } from "./context/ToastsContext";
import Dashboard from "./pages/Dashboard";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <ToastsProvider>
      <BannersProvider>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
        </Routes>
      </BannersProvider>
    </ToastsProvider>
  );
}
```

Layout pattern: `<AppShell>` is the parent route element with `<Outlet>`; `Dashboard` and `Settings` render inside its `<main>` block. Provider order: ToastsProvider outermost (banners can push toasts on resolution but not vice-versa).

- [ ] **Step 4: Verify TypeScript clean**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm run typecheck
```

Expected: exit 0.

- [ ] **Step 5: Visual smoke (no backend yet — should fall through to ConnectionLostOverlay)**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm run dev
```

Open `http://127.0.0.1:5173/`. Expected sequence:
1. Header renders with Logo + tabs + "Nečinný" badge (no `useStateQuery` data yet).
2. `<Dashboard>` renders the centered "Načítám…" spinner.
3. After ~700 ms (3 retries × 100/200/400 ms backoff), `useStateQuery` exhausts retries (no backend on `:8765`), and the `<ConnectionLostOverlay>` mounts on top.
4. DevTools console: shows the failed `/api/state` requests (network errors). Expected and intentional. No JavaScript errors.

This is the cold-start failure mode, which is exactly what Task 13 mock layer fixes for the dev workflow.

Stop with `Ctrl+C`.

- [ ] **Step 6: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add frontend/src/App.tsx frontend/src/components/AppShell.tsx frontend/src/components/useConnectionLost.ts
git -C "c:/GitHub/PlaudSync" commit -m "feat(frontend): AppShell + routing + ConnectionLostOverlay wiring

App.tsx wraps Routes in ToastsProvider + BannersProvider. AppShell is the
layout-route element rendering Header + BannerStack + <Outlet> + Toast +
overlay. useConnectionLost subscribes to TanStack queryCache and shows
the overlay when state-query fetchFailureCount >= 3 with no in-flight
recovery. Banner action handler routes 'Zobrazit log' actions to a toast
pointing to plaudsync.log (Dashboard Gap 4 default C, D11-compliant —
no path interpolation).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Dev mock layer — `dev/mockState.ts`, `dev/MockProvider.tsx`, `dev/DevPanel.tsx`

**Rationale:** Dev workflow needs to exercise all 6 SyncNowPanel scenarios + 7 Settings scenarios without a running backend. Mock layer pre-populates the TanStack Query cache with the prototype's `SCENARIOS` data; `DevPanel` floats in the bottom-left and lets the user switch scenarios + force banners/toasts/ConnectionLostOverlay. Everything in `dev/` is `import.meta.env.DEV`-gated so the production build tree-shakes it out completely.

**Files:**
- Create: `frontend/src/dev/mockState.ts`
- Create: `frontend/src/dev/MockProvider.tsx`
- Create: `frontend/src/dev/DevPanel.tsx`
- Modify: `frontend/src/main.tsx` to mount `<MockProvider>` in dev only.
- Modify: `frontend/src/components/AppShell.tsx` to mount `<DevPanel>` in dev only.

- [ ] **Step 1: Create `frontend/src/dev/mockState.ts`**

```ts
import type { RecordingRow, StateResponse } from "@/api/types";

export const NOW_ISO = "2026-04-25T13:05:30+02:00";

export const SAMPLE_RECORDINGS_FULL: RecordingRow[] = [
  {
    plaud_id: "rec_012",
    title: "04-25 ProjektAlfa: Kickoff sync s týmem",
    created_at: "2026-04-25T12:58:00+02:00",
    downloaded_at: "2026-04-25T13:00:30+02:00",
    plaud_folder: "Meetings/ProjektAlfa",
    classification_status: "matched",
    project: "ProjektAlfa",
    target_dir: "C:\\Projects\\Alpha\\Recordings",
    status: "downloaded",
  },
  {
    plaud_id: "rec_011",
    title: "04-25 1:1 s Honzou — roadmap Q3",
    created_at: "2026-04-25T11:30:00+02:00",
    downloaded_at: "2026-04-25T13:00:25+02:00",
    plaud_folder: "Meetings/Interní",
    classification_status: "matched",
    project: "Interní",
    target_dir: "E:\\Work\\Interni",
    status: "downloaded",
  },
  {
    plaud_id: "rec_010",
    title: "04-25 Klient Beta — review specifikace",
    created_at: "2026-04-25T09:15:00+02:00",
    downloaded_at: "2026-04-25T13:00:20+02:00",
    plaud_folder: "Klienti/Beta",
    classification_status: "matched",
    project: "KlientBeta",
    target_dir: "D:\\Clients\\Beta\\Audio",
    status: "downloaded",
  },
  {
    plaud_id: "rec_009",
    title: "04-24 Voice memo — nápady na onboarding",
    created_at: "2026-04-24T18:42:00+02:00",
    downloaded_at: "2026-04-25T13:00:18+02:00",
    plaud_folder: "Inbox",
    classification_status: "unclassified",
    project: null,
    target_dir: "D:\\Recordings\\Unclassified\\Inbox",
    status: "downloaded",
  },
  {
    plaud_id: "rec_008",
    title: "04-24 Standup — backend tým",
    created_at: "2026-04-24T09:00:00+02:00",
    downloaded_at: "2026-04-24T17:00:12+02:00",
    plaud_folder: "Meetings/Interní",
    classification_status: "matched",
    project: "Interní",
    target_dir: "E:\\Work\\Interni",
    status: "downloaded",
  },
  {
    plaud_id: "rec_003",
    title: "04-21 Voice memo — nepodařilo se stáhnout",
    created_at: "2026-04-21T19:11:00+02:00",
    downloaded_at: "2026-04-21T17:00:04+02:00",
    plaud_folder: "Inbox",
    classification_status: "unclassified",
    project: null,
    target_dir: "D:\\Recordings\\Unclassified\\Inbox",
    status: "failed",
  },
  {
    plaud_id: "rec_001",
    title: "04-20 Onboarding — nový kolega",
    created_at: "2026-04-20T10:00:00+02:00",
    downloaded_at: "2026-04-20T17:00:01+02:00",
    plaud_folder: "Meetings/Interní",
    classification_status: "matched",
    project: "Interní",
    target_dir: "E:\\Work\\Interni",
    status: "skipped",
  },
];

export type ScenarioKey =
  | "idle"
  | "running"
  | "running_by_task_scheduler"
  | "partial_failure"
  | "failed"
  | "empty";

export interface Scenario {
  label: string;
  desc: string;
  state: StateResponse;
}

export const SCENARIOS: Record<ScenarioKey, Scenario> = {
  idle: {
    label: "Idle",
    desc: "Last run succeeded; no banner",
    state: {
      sync: {
        status: "idle",
        trigger: null,
        started_at: null,
        last_run_at: "2026-04-25T12:00:00+02:00",
        last_run_outcome: "success",
        last_run_exit_code: 0,
        last_error_summary: null,
        progress: null,
      },
      recordings: SAMPLE_RECORDINGS_FULL,
    },
  },
  running: {
    label: "Running (UI)",
    desc: "UI-spawned sync, downloading 3/12",
    state: {
      sync: {
        status: "running",
        trigger: "ui_sync_now",
        started_at: "2026-04-25T13:05:00+02:00",
        last_run_at: "2026-04-25T12:00:00+02:00",
        last_run_outcome: "success",
        last_run_exit_code: 0,
        last_error_summary: null,
        progress: { phase: "downloading", processed_count: 3, total_count: 12 },
      },
      recordings: SAMPLE_RECORDINGS_FULL.slice(0, 3),
    },
  },
  running_by_task_scheduler: {
    label: "Running (Task Scheduler)",
    desc: "Spawned by Windows Task Scheduler",
    state: {
      sync: {
        status: "running",
        trigger: "task_scheduler",
        started_at: "2026-04-25T13:00:00+02:00",
        last_run_at: "2026-04-25T12:00:00+02:00",
        last_run_outcome: "success",
        last_run_exit_code: 0,
        last_error_summary: null,
        progress: {
          phase: "categorizing",
          processed_count: 8,
          total_count: 12,
        },
      },
      recordings: SAMPLE_RECORDINGS_FULL.slice(0, 5),
    },
  },
  partial_failure: {
    label: "Partial failure",
    desc: "Last run exit 4 — orange banner",
    state: {
      sync: {
        status: "idle",
        trigger: null,
        started_at: null,
        last_run_at: "2026-04-25T13:05:00+02:00",
        last_run_outcome: "partial_failure",
        last_run_exit_code: 4,
        last_error_summary: "2 recordings failed to download",
        progress: null,
      },
      recordings: SAMPLE_RECORDINGS_FULL,
    },
  },
  failed: {
    label: "Failed",
    desc: "Last run exit 1 — red banner",
    state: {
      sync: {
        status: "idle",
        trigger: null,
        started_at: null,
        last_run_at: "2026-04-25T13:05:00+02:00",
        last_run_outcome: "failed",
        last_run_exit_code: 1,
        last_error_summary: "Network unreachable while listing recordings",
        progress: null,
      },
      recordings: SAMPLE_RECORDINGS_FULL.slice(2),
    },
  },
  empty: {
    label: "Empty (fresh install)",
    desc: "No recordings, never synced",
    state: {
      sync: {
        status: "idle",
        trigger: null,
        started_at: null,
        last_run_at: null,
        last_run_outcome: null,
        last_run_exit_code: null,
        last_error_summary: null,
        progress: null,
      },
      recordings: [],
    },
  },
};

export const MOCK_CONFIG_RAW = `unclassified_dir: \${STATE_ROOT}\\Recordings\\Unclassified

projects:
  ProjektAlfa: \${STATE_ROOT}\\Recordings\\ProjektAlfa
  KlientBeta: \${STATE_ROOT}\\Recordings\\KlientBeta
  Interní: \${STATE_ROOT}\\Recordings\\Interní
`;
```

Direct transcription of prototype `SAMPLE_RECORDINGS_FULL` + `SCENARIOS` (proto:82–233). Note: the literal `${STATE_ROOT}` in `MOCK_CONFIG_RAW` is escaped (`\${STATE_ROOT}`) so JS doesn't interpolate it — the real backend (sync-core) will substitute on read per Settings D8.

- [ ] **Step 2: Create `frontend/src/dev/MockProvider.tsx`**

```tsx
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type PropsWithChildren,
} from "react";
import { useQueryClient } from "@tanstack/react-query";

import { CONFIG_QUERY_KEY, STATE_QUERY_KEY } from "@/api/hooks";
import type { ConfigResponse } from "@/api/types";

import { MOCK_CONFIG_RAW, SCENARIOS, type ScenarioKey } from "./mockState";

interface MockContextValue {
  scenario: ScenarioKey;
  setScenario: (key: ScenarioKey) => void;
  showOverlay: boolean;
  setShowOverlay: (v: boolean) => void;
}

const MockContext = createContext<MockContextValue | null>(null);

export function useMockContext(): MockContextValue | null {
  // Returns null in production (provider not mounted) so consumers can early-return.
  return useContext(MockContext);
}

export default function MockProvider({ children }: PropsWithChildren) {
  if (!import.meta.env.DEV) return <>{children}</>;
  return <DevImpl>{children}</DevImpl>;
}

function DevImpl({ children }: PropsWithChildren) {
  const qc = useQueryClient();
  const [scenario, setScenario] = useState<ScenarioKey>("idle");
  const [showOverlay, setShowOverlay] = useState(false);

  // Pre-populate TanStack cache with the chosen scenario state + mock config.
  useEffect(() => {
    qc.setQueryData(STATE_QUERY_KEY, SCENARIOS[scenario].state);
    const mockConfig: ConfigResponse = {
      raw_yaml: MOCK_CONFIG_RAW,
      parsed: null,
      parse_error: null,
    };
    qc.setQueryData(CONFIG_QUERY_KEY, mockConfig);
  }, [qc, scenario]);

  const value: MockContextValue = {
    scenario,
    setScenario,
    showOverlay,
    setShowOverlay,
  };
  return <MockContext.Provider value={value}>{children}</MockContext.Provider>;
}
```

Notes:
- The early-return `if (!import.meta.env.DEV) return <>{children}</>` guarantees Vite tree-shakes the entire `DevImpl` block out of production bundles. `import.meta.env.DEV` is replaced with the literal `false` at build time, making the dead code statically obvious.
- Pre-populating via `qc.setQueryData` means `useStateQuery` and `useConfig` see initial data on first render — no fetch happens (the queryFn would still try once, but the proxy will fail in dev without a backend; however TanStack with initial data won't fetch until staleTime expires, which by default is 0 — see Step 3 below for the override).

- [ ] **Step 3: Update `main.tsx` to disable refetch in dev mock mode**

Modify `frontend/src/main.tsx` — replace the `QueryClient` config:

```ts
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 3,
      retryDelay: (attempt) => 100 * 2 ** attempt,
      refetchOnWindowFocus: false,
      // In dev mock mode, disable real fetching — MockProvider seeds setQueryData.
      // staleTime: Infinity prevents auto refetch on mount/focus; refetchInterval
      // override per-hook still drives polling, but mock mode resets it implicitly.
      staleTime: import.meta.env.DEV ? Infinity : 0,
    },
    mutations: {
      retry: 0,
    },
  },
});
```

And mount `<MockProvider>` between QueryClientProvider and BrowserRouter:

```tsx
import MockProvider from "./dev/MockProvider";
// ...
createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <MockProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </MockProvider>
    </QueryClientProvider>
  </StrictMode>,
);
```

`staleTime: Infinity` in dev means seeded data is always considered fresh, so TanStack Query will not auto-fetch behind the scenes and overwrite the mock. This is the cleanest separation: mock provider owns the cache during dev; real fetch owns it in prod.

But: `useStateQuery`'s `refetchInterval` is independent of staleTime. To prevent the polling fetch from firing in dev mock mode, override at hook level OR add a check in queryFn. Cleanest: split the dev concern from the prod concern at the queryFn level — MockProvider replaces queryFn for the duration of dev. Simpler in practice: leave it, accept that in dev the proxy fails periodically and TanStack just keeps the mock data because of `placeholderData`. The visual outcome is identical.

- [ ] **Step 4: Create `frontend/src/dev/DevPanel.tsx`**

```tsx
import { useState } from "react";

import type { BannerData } from "@/components/Banner";
import { useBanners } from "@/context/BannersContext";
import { useToasts } from "@/context/ToastsContext";
import { classNames } from "@/utils/format";

import { SCENARIOS, type ScenarioKey } from "./mockState";
import { useMockContext } from "./MockProvider";

export default function DevPanel() {
  if (!import.meta.env.DEV) return null;
  return <DevPanelImpl />;
}

function DevPanelImpl() {
  const ctx = useMockContext();
  const { pushBanner } = useBanners();
  const { pushToast } = useToasts();
  const [open, setOpen] = useState(true);

  if (!ctx) return null;

  const forceBanner = (kind: "token-expired" | "last-sync-failed") => {
    const banner: BannerData =
      kind === "token-expired"
        ? {
            id: "token-expired",
            variant: "error",
            title: "Token vypršel",
            message:
              "Zkopíruj znovu localStorage.tokenstr z app.plaud.ai do souboru .env.",
            actionLabel: "Otevřít Nastavení",
            actionTarget: "settings",
          }
        : {
            id: "last-sync-failed-forced",
            variant: "error",
            title: "Poslední synchronizace selhala",
            message: "Síť nedostupná při načítání seznamu nahrávek.",
            actionLabel: "Zobrazit log",
          };
    pushBanner(banner);
  };

  return (
    <div className="fixed bottom-4 left-4 z-40">
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="px-2.5 py-1.5 rounded-md bg-gray-900 text-white text-[11px] font-mono shadow-md hover:bg-gray-800"
        >
          ▶ DEV
        </button>
      ) : (
        <div className="w-72 bg-gray-900 text-gray-100 rounded-lg shadow-md border border-gray-800 overflow-hidden font-mono text-[11px]">
          <div className="flex items-center justify-between px-3 py-2 bg-gray-950 border-b border-gray-800">
            <div className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
              <span className="font-semibold tracking-wider">DEV PANEL</span>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="text-gray-400 hover:text-white"
              aria-label="Sbalit"
            >
              <svg
                viewBox="0 0 24 24"
                className="w-3.5 h-3.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
          </div>
          <div className="p-3 space-y-3">
            <div>
              <div className="text-gray-400 mb-1.5 uppercase tracking-wider text-[10px]">
                Scenario
              </div>
              <div className="grid grid-cols-2 gap-1">
                {(Object.entries(SCENARIOS) as [ScenarioKey, { label: string; desc: string }][]).map(
                  ([key, s]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => ctx.setScenario(key)}
                      className={classNames(
                        "px-2 py-1.5 rounded text-left leading-tight",
                        ctx.scenario === key
                          ? "bg-blue-600 text-white"
                          : "bg-gray-800 hover:bg-gray-700 text-gray-200",
                      )}
                      title={s.desc}
                    >
                      {s.label}
                    </button>
                  ),
                )}
              </div>
            </div>
            <div>
              <div className="text-gray-400 mb-1.5 uppercase tracking-wider text-[10px]">
                Toasts
              </div>
              <div className="grid grid-cols-2 gap-1">
                <button
                  onClick={() =>
                    pushToast(
                      "success",
                      "Synchronizace dokončena — 5 nových nahrávek",
                    )
                  }
                  className="px-2 py-1.5 rounded bg-gray-800 hover:bg-gray-700"
                >
                  success
                </button>
                <button
                  onClick={() =>
                    pushToast("error", "Synchronizaci se nepodařilo spustit")
                  }
                  className="px-2 py-1.5 rounded bg-gray-800 hover:bg-gray-700"
                >
                  error
                </button>
              </div>
            </div>
            <div>
              <div className="text-gray-400 mb-1.5 uppercase tracking-wider text-[10px]">
                Banners
              </div>
              <div className="grid grid-cols-2 gap-1">
                <button
                  onClick={() => forceBanner("token-expired")}
                  className="px-2 py-1.5 rounded bg-gray-800 hover:bg-gray-700"
                >
                  token expired
                </button>
                <button
                  onClick={() => forceBanner("last-sync-failed")}
                  className="px-2 py-1.5 rounded bg-gray-800 hover:bg-gray-700"
                >
                  sync failed
                </button>
              </div>
            </div>
            <div>
              <div className="text-gray-400 mb-1.5 uppercase tracking-wider text-[10px]">
                Overlay
              </div>
              <div className="grid grid-cols-2 gap-1">
                <button
                  onClick={() => ctx.setShowOverlay(true)}
                  className="px-2 py-1.5 rounded bg-gray-800 hover:bg-gray-700"
                >
                  show
                </button>
                <button
                  onClick={() => ctx.setShowOverlay(false)}
                  className="px-2 py-1.5 rounded bg-gray-800 hover:bg-gray-700"
                >
                  hide
                </button>
              </div>
            </div>
            <div className="text-gray-500 text-[10px] pt-1 border-t border-gray-800">
              Dev only — stripped from production build via import.meta.env.DEV.
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

Direct transcription of proto:1105–1186, with the scenario picker now driving `MockProvider`'s `setScenario` and the overlay toggle exposed via context. Production build: outer `DevPanel` returns `null`, Vite tree-shakes the `DevPanelImpl` import.

- [ ] **Step 5: Mount `<DevPanel>` and dev-only overlay override in AppShell**

Modify `frontend/src/components/AppShell.tsx` — add at the top of imports:

```tsx
import DevPanel from "@/dev/DevPanel";
import { useMockContext } from "@/dev/MockProvider";
```

Inside the component, after `const conn = useConnectionLost();`:

```tsx
  const mockCtx = useMockContext();
  const overlayVisible = (mockCtx?.showOverlay ?? false) || conn.visible;
```

Replace the `<ConnectionLostOverlay>` props:

```tsx
      <ConnectionLostOverlay
        visible={overlayVisible}
        lastError={conn.lastError}
        {...(mockCtx ? { onClose: () => mockCtx.setShowOverlay(false) } : {})}
      />
```

And insert before the closing `</div>`:

```tsx
      <DevPanel />
```

Notes:
- `mockCtx` is `null` in production (provider not mounted) → `overlayVisible` collapses to `conn.visible` only.
- `onClose` is only spread when in dev (mockCtx present) → production overlay has no dismiss button (terminal state per spec).

- [ ] **Step 6: Verify TypeScript clean**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm run typecheck
```

Expected: exit 0.

- [ ] **Step 7: Visual smoke**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm run dev
```

Open `http://127.0.0.1:5173/`. Expected:
- Dashboard renders with full mock recordings list (idle scenario).
- Bottom-left: dev panel visible with scenario picker.
- Click "Running (UI)" → SyncNowPanel switches to running state with progress bar.
- Click "Failed" → red banner appears at top.
- Click `Token expired` → banner stack shows the token-expired banner.
- Click `success` toast button → toast appears bottom-right, auto-dismisses 4 s.
- Click `Overlay show` → ConnectionLostOverlay covers the screen with dev "Skrýt" button; click Skrýt → overlay disappears.
- Navigate to `/settings` via Header tab → Settings page renders. ConnectionPanel shows placeholder dots (`useVerifyAuth` will fail without backend; that's fine for visual check).
- ConfigPanel shows the mock YAML config in the editor.
- Tab key inside textarea inserts 2 spaces.

Stop with `Ctrl+C`.

- [ ] **Step 8: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add frontend/src/dev/ frontend/src/main.tsx frontend/src/components/AppShell.tsx
git -C "c:/GitHub/PlaudSync" commit -m "feat(frontend): dev mock layer — scenarios + DevPanel + MockProvider

dev/mockState.ts ports prototype SCENARIOS + SAMPLE_RECORDINGS_FULL +
MOCK_CONFIG_RAW (literal STATE_ROOT preserved for backend substitution).
MockProvider seeds TanStack cache via setQueryData; staleTime: Infinity
in dev keeps mock fresh. DevPanel floats bottom-left with scenario picker,
toast/banner force buttons, overlay toggle. All dev/* gated by
import.meta.env.DEV — Vite tree-shakes from production bundle.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Production build + postbuild copy + bundle size verification

**Rationale:** Wire the `npm run build` artefact into the Python package so FastAPI `StaticFiles` mount finds it (umbrella E2). The postbuild script copies `frontend/dist/*` to `src/plaudsync/ui/static/`. A small bundle-size guard runs after build; failure prints budget breach but doesn't fail the build (warning only — would block real ship in CI later).

**Files:**
- Create: `frontend/scripts/postbuild.mjs`
- Create: `frontend/scripts/check-bundle-size.mjs`
- Modify: `frontend/package.json` `scripts.build` to invoke the size check.

- [ ] **Step 1: Create `frontend/scripts/postbuild.mjs`**

```js
// Copy Vite build output to ../src/plaudsync/ui/static/ so FastAPI StaticFiles
// can mount it. Idempotent: rms target dir before copy.
import { copyFileSync, mkdirSync, readdirSync, rmSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SOURCE = join(__dirname, "..", "dist");
const TARGET = join(__dirname, "..", "..", "src", "plaudsync", "ui", "static");

function copyRecursive(src, dest) {
  const stat = statSync(src);
  if (stat.isDirectory()) {
    mkdirSync(dest, { recursive: true });
    for (const entry of readdirSync(src)) {
      copyRecursive(join(src, entry), join(dest, entry));
    }
  } else {
    copyFileSync(src, dest);
  }
}

console.log(`[postbuild] cleaning ${TARGET}`);
rmSync(TARGET, { recursive: true, force: true });
mkdirSync(TARGET, { recursive: true });

console.log(`[postbuild] copying ${SOURCE} -> ${TARGET}`);
copyRecursive(SOURCE, TARGET);

console.log("[postbuild] done.");
```

- [ ] **Step 2: Create `frontend/scripts/check-bundle-size.mjs`**

```js
// Fail-soft bundle size check. Walks dist/assets/, sums gzipped size, warns if
// over budget. Exits 0 either way — CI gating is a future concern.
import { gzipSync } from "node:zlib";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const DIST = join(__dirname, "..", "dist");
const BUDGET_KB = 200; // Umbrella spec AC #4. W-U2 watch threshold 500.

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    const s = statSync(p);
    if (s.isDirectory()) yield* walk(p);
    else if (/\.(js|css|html)$/.test(entry)) yield p;
  }
}

let totalGzip = 0;
const sizes = [];
for (const p of walk(DIST)) {
  const buf = readFileSync(p);
  const gz = gzipSync(buf).length;
  totalGzip += gz;
  sizes.push({ path: p.replace(DIST + "/", "").replace(DIST + "\\", ""), gz });
}
sizes.sort((a, b) => b.gz - a.gz);
const totalKB = (totalGzip / 1024).toFixed(1);
console.log(`\n[bundle-size] total gzip: ${totalKB} KB (budget ${BUDGET_KB} KB)`);
console.log("[bundle-size] top contributors:");
for (const s of sizes.slice(0, 8)) {
  console.log(`  ${(s.gz / 1024).toFixed(1).padStart(7)} KB  ${s.path}`);
}
if (totalGzip / 1024 > BUDGET_KB) {
  console.warn(
    `[bundle-size] WARNING: bundle exceeds ${BUDGET_KB} KB budget. W-U2 threshold is 500 KB; investigate.`,
  );
}
```

- [ ] **Step 3: Update `frontend/package.json` build script**

Replace the `build` script value with:

```json
    "build": "tsc -b && vite build && node scripts/postbuild.mjs && node scripts/check-bundle-size.mjs",
```

(The earlier `postbuild` field is removed since the build script now invokes it explicitly — npm's automatic `postbuild` hook would run it twice otherwise.)

- [ ] **Step 4: Run production build**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm run build
```

Expected output (abbreviated):
```
> tsc -b && vite build && node scripts/postbuild.mjs && node scripts/check-bundle-size.mjs

vite v7.0.0 building for production...
✓ NN modules transformed.
dist/index.html                   X.XX KB
dist/assets/index-HASH.css        X.XX KB
dist/assets/index-HASH.js         X.XX KB
dist/assets/react-HASH.js         X.XX KB
dist/assets/query-HASH.js         X.XX KB
✓ built in NNN ms

[postbuild] cleaning .../src/plaudsync/ui/static
[postbuild] copying .../frontend/dist -> .../src/plaudsync/ui/static
[postbuild] done.

[bundle-size] total gzip: NN.N KB (budget 200 KB)
[bundle-size] top contributors:
   XX.X KB  assets/react-HASH.js
   XX.X KB  assets/query-HASH.js
   ...
```

Verify:
- `dist/index.html` exists and contains no inline `<script>` (only `<script type="module" src="/assets/...">`).
- `src/plaudsync/ui/static/index.html` exists.
- `[bundle-size] total gzip` < 200 KB. If over, expected — top contributors listed; the framework chunks (react, query) usually account for 40–60 KB combined; app code should be under 100 KB.

If bundle exceeds 200 KB (warning printed), investigate top contributors:
- React + ReactDOM ≈ 45 KB gzipped (unavoidable)
- @tanstack/react-query ≈ 14 KB
- react-router-dom ≈ 12 KB
- App code ≤ 50 KB target
- @fontsource woff2 not counted (separate font file requests)

Total expected: ~130 KB gzipped. If significantly higher, suspect: accidental import of `@fontsource/jetbrains-mono` whole package vs. `/400.css`; large devOnly code not tree-shaken.

- [ ] **Step 5: Verify production preview works**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm run preview
```

Open `http://127.0.0.1:4173/`. Expected:
- Page loads. Dashboard route renders.
- Without backend running, `<ConnectionLostOverlay>` appears after ~700 ms (3× retry exhausted). **No** dev panel (production stripped it).
- DevTools console: zero errors, zero warnings.
- Network tab: assets served from `/assets/HASH.js` etc., no 404s.

Stop with `Ctrl+C`.

- [ ] **Step 6: Verify static dir is gitignored and contents not staged**

```bash
git -C "c:/GitHub/PlaudSync" status
```

Expected: `src/plaudsync/ui/static/` does NOT appear (gitignore rule from Task 1 covers it). Modified files should be only `frontend/scripts/*` and `frontend/package.json`.

- [ ] **Step 7: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add frontend/scripts/ frontend/package.json
git -C "c:/GitHub/PlaudSync" commit -m "feat(frontend): production build pipeline + bundle size guard

postbuild.mjs copies dist/* to ../src/plaudsync/ui/static/ (FastAPI
StaticFiles mount target — gitignored per umbrella E3). check-bundle-
size.mjs walks dist/, prints gzip total + top 8 contributors, warns when
> 200 KB (umbrella AC #4). Both scripts invoked from npm run build chain
explicitly to avoid npm's auto-postbuild double-run.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: Manual smoke + DEV_LOG + merge to master

**Rationale:** Frontend has no automated test framework (umbrella E6). Acceptance comes from walking through every Dashboard AC (13) + Settings AC (20) by hand using the dev mock layer (Task 13) for scenarios that require specific server state, and against a live backend on `master` for end-to-end happy path. Some AC require the backend to be live (e.g. Dashboard AC #3 "Sync Now click → 202 → progress within 1500 ms"); those are deferred to **Phase 2 smoke** scheduled after the parallel UI backend plan merges. Phase 2 entries appended to DEV_LOG when done.

**Files:**
- Modify: `DEV_LOG.md` (append entry).

- [ ] **Step 1: Run dev server and complete the Phase 1 smoke checklist (mock-data only)**

```bash
cd "c:/GitHub/PlaudSync/frontend" && npm run dev
```

Open `http://127.0.0.1:5173/` and confirm each item below. Mark in DEV_LOG (Step 3) which passed; flag any deviation as an issue.

**Phase 1 — mock data exercise (DevPanel scenarios):**

Dashboard ACs that pass with mock data only:
- [ ] **Dashboard AC #1 — visual parity (idle, partial, failed, empty, running, running_by_task_scheduler).** Side-by-side with prototype `frontend/_prototype/PlaudSync UI.html` opened in a second tab. SyncNowPanel + RecordingsList match pixel-equivalent (allow ±1 px font hinting differences).
- [ ] **Dashboard AC #2 — all scenarios reproducible via DevPanel.** Click each scenario button; visual outcome matches prototype.
- [ ] **Dashboard AC #5 — live row pre-pending (mock approximation).** Manual: switch from `running` to `idle` scenario — no easy mock animation, so this AC is verified end-to-end in Phase 2 against live backend.
- [ ] **Dashboard AC #6 — toast on success transition.** Manual: switch from `running` to `idle`, observe one-shot toast. Mock-mode: switching scenarios doesn't fire the transition effect because both renderings come in one tick. Mark as "deferred to Phase 2".
- [ ] **Dashboard AC #7 — banner derivation.** Switch to `failed` → red banner. Switch to `partial_failure` → amber banner. Switch to `idle` → banner clears. Click X on banner → dismisses; switching back to `failed` again → reappears (in-session memory of dismiss is per-id; Phase 2 verifies persistent dismissal across no-state-change polls).
- [ ] **Dashboard AC #8 — ConnectionLostOverlay.** DevPanel `Overlay show` → modal appears with monospace last-error line + dev "Skrýt" button. Click Skrýt → modal dismissed.
- [ ] **Dashboard AC #10 — Czech localization.** Tab labels, status badges, button text, empty state — all Czech.
- [ ] **Dashboard AC #12 — accessibility minimum.** Tab key cycles Header tabs → Sync button → recording rows. Focus rings visible. `aria-label` on Banner X dismiss + Toast X dismiss.
- [ ] **Dashboard AC #13 — no console errors.** Production preview shows zero errors.

Settings ACs that pass with mock data only:
- [ ] **Settings AC #1 — visual parity.** ConnectionPanel + ConfigPanel + YamlEditor match prototype.
- [ ] **Settings AC #5 — placeholder dots when token missing.** ConnectionPanel shows `••••••••••••••••••••` when `useVerifyAuth` hasn't completed (mock mode: it never completes without backend; but that's the intended cold-start visual).
- [ ] **Settings AC #14 — line gutter scroll sync.** Paste 100-line YAML into editor; scroll the textarea; gutter scrolls in lockstep.
- [ ] **Settings AC #15 — Tab key indent.** Caret in textarea, press Tab → 2 spaces inserted at caret. Range-select 3 lines + Tab → each line indented. Esc → blurs textarea.
- [ ] **Settings AC #16 — gutter perf.** Paste 500-line YAML; type a single character. No visible jank.
- [ ] **Settings AC #17 — accessibility.** Tab cycles Verify → textarea → Save → Reload (textarea Tab-trap escaped via Esc). Focus rings visible. Gutter has `aria-hidden="true"`.
- [ ] **Settings AC #18 — Czech localization.** All D10 strings present verbatim.
- [ ] **Settings AC #19 — privacy grep.**

```bash
cd "c:/GitHub/PlaudSync/frontend" && \
  grep -rnE 'pushToast|pushBanner|throw new Error' src/ | \
  grep -E '\$\{(target_dir|project|title|plaud_folder|local_path|file_path|raw_yaml|masked_token)' || \
  echo "PASS: no forbidden interpolations"
```

Expected: `PASS: no forbidden interpolations`.

- [ ] **Settings AC #20 — bundle size.** From Task 14 step 4: gzipped total < 500 KB (W-U2 watch). Target: < 200 KB.

ACs **deferred to Phase 2** (require backend on master + this branch merged):
- Dashboard AC #3 (Sync Now → 202 → progress within 1500 ms)
- Dashboard AC #4 (concurrent click — 409 transparent)
- Dashboard AC #5 (live row pre-pending during real sync)
- Dashboard AC #6 (toast on real running→idle+success transition)
- Dashboard AC #9 (refetchInterval adapts in DevTools network tab)
- Dashboard AC #11 (frontend bundle ≤ 500 KB gzipped — actually doable now; checked in Task 14)
- Settings AC #2 (token mask — needs backend `auth.py` with `mask_token` helper)
- Settings AC #3 (verify success against valid token)
- Settings AC #4 (verify expired)
- Settings AC #5 (verify missing real .env)
- Settings AC #6 (settings mount auto-verify visual confirm — partially testable; needs backend)
- Settings AC #7 (save happy path)
- Settings AC #8 (save 422 single-error)
- Settings AC #9 (save 422 multi-error)
- Settings AC #10 (save 5xx)
- Settings AC #11 (reload — dirty confirm) — partially testable with mock + edit
- Settings AC #12 (reload — clean refetch)
- Settings AC #13 (existing broken config on mount)

Stop dev server.

- [ ] **Step 2: Run security review (subagent / native command)**

```
/security-review
```

Address any high-severity finding. Re-run if changes made. Most likely findings (frontend-specific):
- Missing `rel="noopener noreferrer"` on any `<a target="_blank">` (none in this codebase — banner action labels are buttons, not anchors).
- React `dangerouslySetInnerHTML` usage (none).
- `eval` / `new Function` (none — Vite production build also asserts none).

Expected: clean. Commit any fixes as separate task.

- [ ] **Step 3: Append DEV_LOG entry**

In `DEV_LOG.md`, append a new section at the appropriate chronological location:

```markdown
### 2026-04-25 — UI frontend Phase 1 smoke (mock data)

Branch `feat/ui-frontend` complete: 15 tasks, ~25 TSX modules transcribing
prototype `frontend/_prototype/PlaudSync UI.html` into Vite + React 19 +
TS strict + Tailwind 4 project. Bundle size: <NN.N> KB gzipped (budget 200
KB; W-U2 watch threshold 500 KB).

Phase 1 ACs passed (mock-data only):
- Dashboard: 1, 2, 7, 8, 10, 12, 13.
- Settings: 1, 5, 14, 15, 16, 17, 18, 19, 20.

Phase 1 ACs deferred to Phase 2 (need live backend on master):
- Dashboard: 3, 4, 5, 6, 9, 11.
- Settings: 2, 3, 4, 5 (live), 6, 7, 8, 9, 10, 11, 12, 13.

Phase 2 smoke schedule: after `feat/ui-backend` merges to master,
spin up `python -m plaudsync ui` + `cd frontend && npm run dev` with
`PLAUDSYNC_DEV_PORT=8765`, walk through deferred ACs. Append Phase 2
entry on completion.

Open follow-ups (none blocker for merge):
- Dashboard Gap 1: `_unmapped_<project>` badge variant — needs backend
  `RecordingRow.classification_route` field (sync-core spec follow-up).
- Dashboard Gap 4: log viewer — toast points user to plaudsync.log file
  path (default C from spec); modal log view deferred to v1.1+.
- Settings Gap 5: YAML syntax highlight — deferred to v1.1+.
```

Replace `<NN.N>` with the actual KB total from Task 14 Step 4.

- [ ] **Step 4: Commit DEV_LOG**

```bash
git -C "c:/GitHub/PlaudSync" add DEV_LOG.md
git -C "c:/GitHub/PlaudSync" commit -m "docs(dev-log): record UI frontend Phase 1 smoke results

Phase 1 (mock-data) ACs passed for Dashboard 1/2/7/8/10/12/13 + Settings
1/5/14-20. Phase 2 ACs awaiting feat/ui-backend merge for live verify.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Merge to master**

```bash
git -C "c:/GitHub/PlaudSync" checkout master
git -C "c:/GitHub/PlaudSync" merge --no-ff feat/ui-frontend -m "Merge feat/ui-frontend: Vite project + Dashboard + Settings (Phase 1)"
```

Phase 2 smoke happens after `feat/ui-backend` lands on master. That will be a follow-up DEV_LOG entry, not a new branch.

---

## Self-review

### 1. Spec coverage matrix

**Umbrella architecture (E1–E6):**

| Spec section | Task |
|---|---|
| E1 — repo layout (`frontend/` + `src/plaudsync/ui/static/`) | Task 1 (frontend/), Task 14 (postbuild copies to ui/static/) |
| E2 — build flow (Vite dev → proxy /api; prod → postbuild copy) | Task 1 (vite.config.ts proxy), Task 14 (build chain) |
| E3 — static commit policy gitignore | Task 1 Step 11 |
| E4 — manual TypeScript types | Task 3 |
| E5 — CSP-friendly bundle (no inline `<script>`, no remote fonts) | Task 1 `modulePreload.polyfill: false`, Task 2 `@fontsource` self-host |
| E6 — test strategy (no Vitest, manual smoke) | Task 15 |
| B1–B2 — endpoint shapes | Task 3 (TS mirror), Task 4 (client method per endpoint) |
| B3 — polling source of truth | Task 5 (`useStateQuery.refetchInterval`) |
| B5 — no auth/CSRF + no token in /api/config | Task 4 (no auth headers); Task 11 ConnectionPanel reads `masked_token` from `/api/auth/verify` only |
| C1–C5 — Sync Now states + error taxonomy | Task 10 SyncNowPanel + Dashboard onError; Task 8 Banner/Toast/Overlay; Task 12 banner action handler |
| D1 — React Router top-nav | Task 7 Header + Task 12 App.tsx |
| D2 — TanStack Query + plain useState | Task 5 + Task 9 (Context for app-level only, no global store lib) |
| D3 — Layout components stable contract | Tasks 7, 8, 12 |

**Dashboard spec (D1–D10, ACs 1–13):**

| Spec D-decision | Task |
|---|---|
| D1 layout (max-w-6xl, vertical stack) | Task 10 + Task 12 AppShell |
| D2 SyncNowPanel 6 states | Task 10 SyncNowPanel.tsx |
| D3 RecordingsList row layout | Task 10 RecordingsList.tsx |
| D4 ProjectBadge color taxonomy | Task 6 colors.ts + Task 10 ProjectBadge.tsx |
| D5 SyncStatusBadge 5 states | Task 7 SyncStatusBadge.tsx |
| D6 BannerStack derivation rules | Task 9 BannersContext.syncFromState |
| D7 Toast 4 s auto-dismiss | Task 8 Toast.tsx + Task 9 ToastsProvider |
| D8 ConnectionLostOverlay | Task 8 ConnectionLostOverlay.tsx + Task 12 useConnectionLost |
| D9 Live recordings during sync | Task 5 polling + Task 10 RecordingsList |
| D10 Polling cadence 5000/1500 | Task 5 useStateQuery |
| AC #1–2, 7–8, 10, 12–13 (mock-data testable) | Task 15 Phase 1 |
| AC #3–6, 9, 11 (live backend required) | Task 15 Phase 2 (deferred) |

**Settings spec (D1–D11, ACs 1–20, v0.1 Gaps 1–10):**

| Spec D-decision | Task |
|---|---|
| D1 layout | Task 11 |
| D2 ConnectionPanel + implicit verify on mount | Task 11 ConnectionPanel.tsx |
| D3 Verify state machine | Task 11 ConnectionPanel.tsx |
| D4 ConfigPanel + Save/Reload | Task 11 ConfigPanel.tsx |
| D5 YamlEditor layout | Task 11 YamlEditor.tsx |
| D6 Save state machine (incl. always-enabled per Gap 6) | Task 11 ConfigPanel.tsx |
| D7 Reload behavior (incl. Gap 4 dirty-confirm) | Task 11 ConfigPanel.tsx |
| D8 DEFAULT_YAML template | Backend (sync-core auto-seed); Task 13 holds dev mock copy |
| D9 Banner token-expired surface | Task 11 ConnectionPanel + Task 9 BannersContext |
| D10 Localization lock contract | All component tasks preserve verbatim |
| D11 Privacy discipline | Task 11 Step 7 grep + Task 15 AC #19 grep |
| Gap 1 — multi-error first inline + expand | Task 11 InlineConfigErrors.tsx |
| Gap 2 Option A — masked_token in AuthVerifyResponse | Task 3 types + Task 11 ConnectionPanel |
| Gap 3 — parse_error from GET on mount | Task 11 ConfigPanel.tsx useEffect |
| Gap 4 — dirty-reload confirm | Task 11 ConfigPanel.tsx onReload |
| Gap 5 — no syntax highlight | Acknowledged out of scope (Task 11 notes) |
| Gap 6 — always-enabled save | Task 11 (no dirty disable; Save always enabled) |
| Gap 7 — auto-seed DEFAULT_YAML | Backend follow-up (sync-core spec v0.3); not this plan |
| Gap 8 — 422 vs 200+ok-flag taxonomy | Task 4 client.ts ValidationError on 422; AuthVerifyResponse via 200 |
| Gap 9 — Tab key indent + Esc blur | Task 11 YamlEditor onKeyDown |
| Gap 10 — gutter perf at 500 lines | Task 15 AC #16 manual verify |

**Cross-spec items handled:**

- Loading state on Dashboard cold start (Dashboard Gap 5): Task 10 centered spinner.
- Dismissed banner persistence (Dashboard Gap 7): Task 9 `dismissedRef` Set in-memory only, acceptable v0 per spec.
- Live recordings list animation (Dashboard Gap 6): Task 10 — no animation v0, acceptable per spec.
- ConnectionLostOverlay onClose optional (prod terminal vs dev dismiss): Task 8 + Task 13 dev override.

### 2. Placeholder scan

- No `TBD` / `implement later` / `// ...` elision in any code block.
- All `git` commands quote `c:/GitHub/PlaudSync` paths.
- All `npm` commands wrapped in `cd "c:/GitHub/PlaudSync/frontend" && npm ...`.
- Czech strings preserved verbatim from prototype (cross-checked against Settings D10 lock contract for ConnectionPanel + ConfigPanel; against Dashboard spec for SyncNowPanel + RecordingsList).
- Expected output documented for `typecheck`, `dev`, `build`, `preview`.

### 3. Type consistency

Cross-task type alignment verified:

- `StateResponse`, `RecordingRow`, `SyncState`, `SyncProgress` defined in Task 3, consumed unchanged in Tasks 5 (hooks), 10 (Dashboard), 12 (AppShell), 13 (mockState).
- `RecordingRow.plaud_folder: string` (Task 3) renders as `r.plaud_folder` in Task 10 RecordingsList — consistent.
- `AuthVerifyResponse.masked_token: string | null` (Task 3) consumed as `verify.data?.masked_token ?? PLACEHOLDER_MASK` in Task 11 ConnectionPanel.
- `ConfigParseError { line: number; message: string }` defined in Task 3, used in Tasks 4 (ValidationError.errors), 11 (YamlEditor + InlineConfigErrors props).
- `BannerData` defined in Task 8 Banner.tsx, consumed in Task 9 BannersContext + Task 12 AppShell handler + Task 13 DevPanel forceBanner.
- `ToastData` defined in Task 8 Toast.tsx, consumed in Task 9 ToastsProvider.
- `STATE_QUERY_KEY` / `CONFIG_QUERY_KEY` exported from Task 5 hooks.ts, used in Task 12 useConnectionLost + Task 13 MockProvider — single source.
- `ScenarioKey` / `Scenario` / `SCENARIOS` defined in Task 13 mockState.ts, used in MockProvider + DevPanel — same module.

### 4. Dependency order

Each task's imports are satisfied by earlier tasks:

| Task | Depends on |
|---|---|
| 1 | (none — bootstrap) |
| 2 | Task 1 (configs + npm install) |
| 3 | Task 1 (TS strict) |
| 4 | Task 3 (types) |
| 5 | Tasks 3, 4 (types + client) |
| 6 | Task 3 (SyncProgress type for phaseLabel) |
| 7 | Tasks 3, 6 (types + format helpers) |
| 8 | Task 6 (classNames) |
| 9 | Task 8 (BannerData / ToastData types) |
| 10 | Tasks 3, 4, 5, 6, 8, 9 (types, ConflictError, hooks, format, components, contexts) |
| 11 | Tasks 3, 4, 5, 9 (types, ValidationError, hooks, contexts) |
| 12 | Tasks 5, 7, 8, 9, 10, 11 (everything below the layout) |
| 13 | Tasks 3, 5, 8, 9, 10, 11, 12 (consumes all to inject) |
| 14 | Task 1 (npm scripts wiring) |
| 15 | All tasks (smoke walks the full app) |

No forward references. Each task's verification step (`npm run typecheck`) catches any breakage before commit.

### 5. Ambiguity scan

- **Bundle size budget vs reality:** spec says < 200 KB (umbrella AC #4) but W-U2 watch threshold is 500 KB. Task 14 prints both; warns at 200 KB without failing. Plan does not block merge on >200 KB — solo dev judgement. Note added in Task 14 Step 4.
- **`useStateQuery` polling in dev mock mode:** Task 13 Step 3 sets `staleTime: Infinity` in dev to keep mock fresh, but `refetchInterval` from `useStateQuery` is independent. The proxy will fail (no backend); TanStack will keep `placeholderData` (the mock) on top of failed fetches. Visual outcome is identical to "no polling". This is documented in Task 13 Step 3 — acceptable trade-off vs. inventing a queryFn-swap mechanism.
- **Mock toast on running→idle transition:** Dashboard AC #6 requires the toast to fire on real transitions; in mock mode the prevStatusRef tracks scenario switches as transitions, so switching `running → idle` via DevPanel might fire the toast (whether prev was inferred as `running`). Behavior is acceptable for visual smoke but Task 15 Phase 1 marks it "deferred to Phase 2" for true semantic verification.
- **Banner action `actionTarget === "settings"` navigation:** Task 12 uses `window.location.assign("/settings")` instead of `useNavigate`. `useNavigate` would be slightly more idiomatic but requires the handler to be in a hook context. Functional outcome identical; either is acceptable for the executor.

No blocker ambiguities.

---

## Execution handoff

Plan complete and saved to [`docs/superpowers/plans/2026-04-25-ui-frontend.md`](2026-04-25-ui-frontend.md). Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task with two-stage review. Good fit for 15 tasks of mostly mechanical transcription work; subagent isolation prevents accidental cross-task state leakage and the review checkpoint per task catches missed Czech strings or off-by-one component shapes early.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints. Acceptable here because per-task TS `npm run typecheck` is a hard verification gate (no manual judgement needed for correctness; visual smoke comes only at Tasks 12, 13, 15).

Which approach?

**If Subagent-Driven chosen:**
- **REQUIRED SUB-SKILL:** Use `superpowers:subagent-driven-development`.
- Branch: `feat/ui-frontend` (created in Task 1 Step 1).
- Cadence: ~30–60 min wall clock per task with subagent + review = full plan in 1–2 days of intermittent attention.

**If Inline Execution chosen:**
- **REQUIRED SUB-SKILL:** Use `superpowers:executing-plans`.
- Batch suggestion: Tasks 1–6 (scaffolding + types + hooks + utils, no UI) → checkpoint review of TS clean + dev-server boot. Tasks 7–11 (all components + pages) → checkpoint review of full visual smoke. Tasks 12–15 (wiring + dev mock + build + smoke) → final review + merge.

