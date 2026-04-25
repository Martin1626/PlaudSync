# PlaudSync — Claude Code Workflow

> Short, human-readable, per Anthropic best practices. If Claude keeps breaking a rule, the file is too long — prune.

## Project

Periodic sync of Plaud AI recordings → local disk, categorized via single-layer regex on title. See [SPEC.md](./SPEC.md). Track decisions/issues in [DEV_LOG.md](./DEV_LOG.md).

## Stack

- **Python 3.11+**, deps v `pyproject.toml`.
- **Testing:** pytest + pytest-recording (VCR.py cassettes).
- **Observability:** Loguru (rotating file) + Sentry SDK (scrubbed, `send_default_pii=False`).
- **Secrets:** `.env` (never commit), `.env.example` is template.
- **Platform:** Windows 11 + Git Bash. Never assume POSIX paths — use `pathlib.Path`.

## Workflow

**Before coding non-trivial feature:**
- Invoke Superpowers `brainstorming` skill (bundled) for Socratic requirements refinement before Plan Mode. For small fixes (< 1-sentence diff), skip.

**Planning phase:**
- Use Plan Mode (`Shift+Tab` or `/plan`) for anything touching multiple files, auth, or external APIs. Review the plan before switching to implementation.
- For small scope (typo, rename, one-line fix): skip plan, implement directly.

**Implementation phase — TDD integration-first:**
- **Write FAILING integration test first, commit it, then implement until green.** Do not modify the test to make it pass.
- Default to **integration tests with VCR cassettes** (`@pytest.mark.vcr()`) for any code touching Plaud API or filesystem. Mock-only unit tests only for pure logic (regex, classification rules).
- Cassettes live in `tests/cassettes/`. Scrub auth tokens via `pytest-recording` config in `tests/conftest.py`.

**Review gates (before commit / merge):**
- **Before every commit:** run `/review` (native slash command).
- **Before merging to main:** run `/security-review` + verify `bandit -r src/` is clean.
- **Architecturally significant change** (> 200 LoC, auth flow, external API contract, token handling): use Writer/Reviewer pattern — finish in current session, then start a **fresh session as reviewer** on the diff.

**Commits:** new commits over amend. Never skip hooks (`--no-verify`) or bypass signing. If a pre-commit hook fails, fix the root cause.

## Testing rules

- `pytest tests/` is the single entry — unit + integration + evals all run via pytest.
- PostToolUse hook auto-runs `pytest tests/ -x --lf -q` after Edit/Write in `src/**/*.py` or `tests/**/*.py`. If the hook is > 10 s avg, kill it (kill criterion `harness #10`).
- Cassettes must be **human-readable YAML**. If first recorded cassette for a Plaud endpoint is base64-bloated (audio response body), decide: scrub body or store separately.

## Conventions

- Package layout: `src/plaudsync/`. Entry point: `python -m plaudsync`.
- Use `pathlib.Path`, not string paths. Never `os.path.join` on user-provided input.
- Logging: `from loguru import logger`; never `print` in production paths.
- Type hints on public functions; `mypy --strict` is not required (solo dev, don't gold-plate).
- Docstrings only when the *why* is non-obvious. Skip self-evident `"""Return the user."""`.

## Windows / Git Bash quirks

- Hook scripts run in Git Bash by default. Use bash-compatible commands or invoke Python helper (preferred for portability): `.claude/hooks/pytest_on_edit.py`.
- Paths from Claude tool inputs may contain `\\`; normalize with `Path(raw_path.replace("\\", "/"))` or `PureWindowsPath`.
- Task Scheduler: use absolute paths in action definitions. Relative paths fail silently from Task Scheduler context.

## Privacy / observability rules

- **Never inline business labels in exception messages or log strings.** Bad: `raise RuntimeError(f"failure for project={name}")`. Good: `sentry_sdk.set_tag("project", name); raise RuntimeError("failure")` (or `logger.bind(project=name).error("failure")`).
- Reason: scrubbing in `observability.py` reliably scrubs structured fields (tags/contexts) and known patterns (paths, recording filenames, `key=value`). Free-form text inside messages is best-effort regex — easy to miss novel formats.
- Same applies to any business identifier: project name, category, meeting title, participant email, recording filename. Always pass via `set_tag`/`set_context`/`logger.bind`, never f-string into the message.

## Do not

- Do not add features, abstractions, or error handling beyond what the task requires.
- Do not create new docs/README files unless explicitly requested.
- Do not commit `.env`, Plaud audio files, cassettes with unscrubbed credentials, or Sentry DSN.
- Do not use `os.system` or shell=True with user/API input.

## Links

- `SPEC.md` — current scope + success criteria.
- `DEV_LOG.md` — dev journal + kill criteria tracking.
- `.claude/skills/cassette-refresh/SKILL.md` — how to re-record VCR cassettes safely.
- `.claude/skills/sync-debug/SKILL.md` — systematic debug postup when sync fails.
