---
name: sync-debug
description: Systematic 4-step debug procedure when PlaudSync sync run fails (Task Scheduler job non-zero exit, Sentry alert, or missing/miscategorized recordings). Invoke before ad-hoc debugging to avoid tunnel vision.
---

# Sync debug workflow

When PlaudSync fails, the symptom (Sentry alert, missing files, wrong category) can come from four distinct layers. Diagnose in order — skipping layers wastes time.

## When to invoke this skill

- Sentry alert fires for the sync job.
- Expected recording did not appear in the configured project directory.
- Recording ended up in wrong project folder.
- Task Scheduler history shows non-zero exit code.
- Manual invocation `python -m plaudsync` fails.

## Procedure

Work through layers in order. Do not skip — symptoms often mask the real root cause.

### Layer 1: Environment / credentials

- Is `.env` present and populated? `cat .env` (on dev box; never on shared terminal).
- Are Plaud credentials still valid? Try `curl -H "Authorization: Bearer $PLAUD_API_TOKEN" <plaud-api-me-endpoint>`.
- Is `PLAUDSYNC_STATE_ROOT` set to an existing writable directory (state DB location)? `ls -la "$PLAUDSYNC_STATE_ROOT"`.
- Does `$PLAUDSYNC_STATE_ROOT/config.yaml` exist and contain valid `unclassified_dir` + `projects` mapping (per-project absolute paths)?
- **If any answer is no → fix env first, re-run. Do not touch code until env is green.**

### Layer 2: Network / API availability

- Can you reach the Plaud API? `curl -v <plaud-api-health-endpoint>`.
- Does the Sentry alert include a network-level exception (DNS, connection refused, TLS handshake)?
- **If the Plaud API is down → wait and document in DEV_LOG.**

### Layer 3: Cassette / test drift

- When was the test suite last green? `git log --oneline -- tests/`.
- Run the full integration test suite: `python -m pytest tests/ -v`. If cassettes replay but production fails, the cassette has drifted from real API — invoke `cassette-refresh` skill.
- Compare cassette response schema with actual API response (capture one real response manually and diff).
- **If cassettes are stale → refresh (see `cassette-refresh` skill), re-run, root-cause the contract drift.**

### Layer 4: Categorization / business logic

- Only reach this layer after layers 1–3 are clean.
- Check the log for the `classify()` result for the failing recording (logged at DEBUG level with structured bind fields — never inline message text).
- Does the title match the expected format `(YYYY-)?MM-DD <Project>: <rest>`? Quick manual check:
  ```
  python -c "from plaudsync.categorization import classify; from datetime import datetime; print(classify('<title>', datetime.now()))"
  ```
- The fallback path layout below depends on `path_resolver.py` from the sync-core spec — these locations exist only after sync-core ships. Until then, the categorization layer only emits `status='matched' | 'unclassified'`; the sync engine handles physical placement.
- If `status='matched'` but project is not in config → (sync-core dependent) soft fallback to `_unmapped_<project>/` under `unclassified_dir`. Add the project to `config.yaml`.
- If `status='unclassified'` → (sync-core dependent) title did not match format; recording goes to `_unclassified/<plaud_folder>/`. Fix the recording title in Plaud app or add a regex alias if pattern is new but valid.
- If coverage rate is trending below 90 % over the sliding 30-day window → kill criterion #5 triggers; revise title format discipline or add a second classification layer.
- **Fix classifier or config only when layers 1–3 are confirmed not at fault.**

## After resolution

Record in `DEV_LOG.md`:
- Symptom (what was broken).
- Which layer the root cause was in.
- Fix applied.
- Whether any kill criterion triggered or came close.

This log compounds — patterns emerge after 5–10 incidents that no single debug session surfaces.
