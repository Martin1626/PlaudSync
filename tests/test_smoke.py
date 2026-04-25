"""Smoke test that exercises the PostToolUse pytest hook.

The hook in `.claude/hooks/pytest_on_edit.py` runs `pytest tests/ -x --lf -q`
after any Edit/Write to `src/**/*.py` or `tests/**/*.py`. This file gives
pytest something to discover so the hook returns success (not "no tests
collected", which is technically pass but uninformative).

Validates kill criterion H-10 (hook avg runtime > 10 s → disable hook).
"""


def test_smoke_sanity() -> None:
    """Trivially true — exists only so pytest collects something."""
    assert True


def test_smoke_observability_imports() -> None:
    """Sanity: observability module imports without side effects."""
    from plaudsync import observability  # noqa: F401


def test_observability_redacts_plaud_folder_key() -> None:
    """plaud_folder is a known business label (Plaud-side folder name like
    'Klienti'); must be scrubbed from Sentry tags/contexts.
    """
    from plaudsync.observability import scrub_event

    event = {
        "tags": {"plaud_folder": "Klienti"},
        "contexts": {"recording": {"plaud_folder": "Inbox"}},
    }
    scrubbed = scrub_event(event, hint={})
    assert scrubbed is not None
    assert scrubbed["tags"]["plaud_folder"] == "<redacted-label>"
    assert scrubbed["contexts"]["recording"]["plaud_folder"] == "<redacted-label>"
