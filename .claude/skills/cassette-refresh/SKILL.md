---
name: cassette-refresh
description: How to re-record a VCR cassette against a real Plaud/M365/Anthropic API endpoint safely, with auth token and PII scrubbing. Invoke when a cassette breaks, a new endpoint is tested, or weekly freshness check fires.
---

# Cassette refresh workflow

Re-recording a VCR cassette means hitting the **real external API** and persisting the response for replay. Two failure modes matter: (1) auth tokens leak into the cassette, (2) cassette drifts silently and replay no longer matches production behavior.

## When to invoke this skill

- A cassette fails to replay (response structure changed, new fields, renamed endpoint).
- A new integration test is being added for an endpoint that has no cassette yet.
- Weekly freshness check flags a divergence between recorded cassette and current API response.
- Kill criterion `#T-5` (cassette re-record > 1×/month) is near trigger — investigate root cause, not just refresh.

## Preconditions

- `.env` is populated with real API credentials (`PLAUD_API_TOKEN`, `M365_CLIENT_ID/SECRET`, `ANTHROPIC_API_KEY`).
- `tests/conftest.py` has `pytest-recording` configured with scrubbing filters (`filter_headers`, `filter_query_parameters`, `before_record_response` callback).
- Internet connectivity to the target API.
- Clean git working tree (so cassette diff is reviewable as a single commit).

## Procedure

1. **Verify scrubbing config before recording.** Open `tests/conftest.py` and confirm:
   - `filter_headers` includes `Authorization`, `X-Api-Key`, `Cookie`, `Set-Cookie`, and any provider-specific auth header.
   - `filter_query_parameters` includes `access_token`, `token`, `api_key`.
   - `before_record_response` callback strips PII from response bodies if any endpoint returns user emails, meeting titles, or recording filenames that could leak business content.
   - If config is missing any of these, **stop and fix conftest first**.

2. **Delete the stale cassette.** `rm tests/cassettes/<test_name>.yaml`. Without deletion, `pytest-recording` replays instead of re-recording.

3. **Run the test in recording mode.** From repo root:
   ```
   python -m pytest tests/path/to/test.py::test_name --record-mode=new_episodes -v
   ```
   For a full suite refresh: `python -m pytest tests/ --record-mode=new_episodes -v` (use sparingly — hits real APIs).

4. **Audit the recorded cassette.** Open the YAML file manually:
   - Search for leaked secrets: `grep -iE "(authorization|bearer|token|secret|key)" tests/cassettes/<file>.yaml`. Any hit that isn't scrubbed → fix conftest, re-record, do not proceed.
   - Search for PII: real names, emails, meeting titles, file paths. If present, extend `before_record_response` to scrub, re-record.
   - Confirm response bodies are human-readable (not base64-bloated). If a response is binary (audio), either configure VCR to skip body recording for that endpoint or store the body separately out-of-cassette.

5. **Run the test in replay mode to confirm.**
   ```
   python -m pytest tests/path/to/test.py::test_name -v
   ```
   Must pass without network access (pytest is configured with `--block-network` by default).

6. **Commit the cassette as a separate commit.** Message: `test: refresh cassette for <endpoint>`. Review the diff one last time. If anything looks like a secret, `git reset HEAD~1` and return to step 1.

## Kill criterion reminder

If cassette re-record becomes routine (> 1×/month per cassette) → the API contract is unstable, not the test. Document in DEV_LOG; consider whether programmatic mocks (respx) are a better fit than recorded fixtures for that specific endpoint.
