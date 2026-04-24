---
name: sync-debug
description: Systematic 4-step debug procedure when PlaudSync sync run fails (Task Scheduler job non-zero exit, Sentry alert, or missing/miscategorized recordings). Invoke before ad-hoc debugging to avoid tunnel vision.
---

# Sync debug workflow

When PlaudSync fails, the symptom (Sentry alert, missing files, wrong category) can come from four distinct layers. Diagnose in order — skipping layers wastes time.

## When to invoke this skill

- Sentry alert fires for the sync job.
- Expected recording did not appear in `{PLAUDSYNC_LOCAL_ROOT}/{project}/`.
- Recording ended up in wrong project folder.
- Task Scheduler history shows non-zero exit code.
- Manual invocation `python -m plaudsync` fails.

## Procedure

Work through layers in order. Do not skip — symptoms often mask the real root cause.

### Layer 1: Environment / credentials

- Is `.env` present and populated? `cat .env` (on dev box; never on shared terminal).
- Are Plaud credentials still valid? Try `curl -H "Authorization: Bearer $PLAUD_API_TOKEN" <plaud-api-me-endpoint>`.
- Are M365 credentials still valid? MSAL token may have expired; refresh flow may be broken.
- Is `PLAUDSYNC_LOCAL_ROOT` set to an existing writable directory? `ls -la "$PLAUDSYNC_LOCAL_ROOT"`.
- **If any answer is no → fix env first, re-run. Do not touch code until env is green.**

### Layer 2: Network / API availability

- Can you reach the Plaud API? `curl -v <plaud-api-health-endpoint>`.
- Is Microsoft Graph up? Check `https://status.office.com`.
- Is Anthropic API up (for LLM classifier fallback)? Check `https://status.anthropic.com`.
- Does the Sentry alert include a network-level exception (DNS, connection refused, TLS handshake)?
- **If a provider is down → wait or disable the layer (e.g., skip LLM fallback, use regex-only) and document in DEV_LOG.**

### Layer 3: Cassette / test drift

- When was the test suite last green? `git log --oneline -- tests/`.
- Run the full integration test suite: `python -m pytest tests/ -v`. If cassettes replay but production fails, the cassette has drifted from real API — invoke `cassette-refresh` skill.
- Compare cassette response schema with actual API response (capture one real response manually and diff).
- **If cassettes are stale → refresh (see `cassette-refresh` skill), re-run, root-cause the contract drift.**

### Layer 4: Categorization / business logic

- Only reach this layer after layers 1–3 are clean.
- Which waterfall rung categorized the failing recording? Check log for "categorized via: M365|regex|LLM".
- If M365: did the participant lookup return empty? Is the user in the expected Graph group?
- If regex: does the title/transcript match the pattern? `grep -iE "<pattern>" <transcript>`.
- If LLM: run DeepEval suite on the current golden set: `python -m pytest tests/evals/ -v`. Has accuracy dropped below 70 %? (Kill criterion #5.)
- **Fix classifier only when layers 1–3 are confirmed not at fault.**

## After resolution

Record in `DEV_LOG.md`:
- Symptom (what was broken).
- Which layer the root cause was in.
- Fix applied.
- Whether any kill criterion triggered or came close.

This log compounds — patterns emerge after 5–10 incidents that no single debug session surfaces.
