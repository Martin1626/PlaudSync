"""State transition matrix for recordings.status UPSERT logic.

Audit triggered by Hotfix L 2026-04-30 — `skipped` → `downloaded` upgrade
was a TDD blind spot ("untested round-trip" pattern). This test covers
the full 4×4 transition matrix to prevent similar gaps for any future
status enum addition.

Design intent (from sync-core spec Decision #5 + BL-X amendments):
- INSERT on first sight (regardless of incoming status).
- UPDATE only for upgrade-able transitions to 'downloaded':
    failed                  → downloaded
    skipped_unknown_project → downloaded   (BL-3 retry)
    skipped                 → downloaded   (BL-X audio gate re-enable; Hotfix L)
- All other transitions are noop:
  - downloaded → anything: immutable (file already on disk).
  - skipped/failed → skipped/failed/skipped_unknown_project: stays as
    originally recorded (avoid losing original failure reason).
  - any → unsupported value: rejected at SQL CHECK constraint (no test
    needed — DB enforces schema).
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from plaudsync.state import open_state, record_recording, start_sync_run


@dataclass
class _Meta:
    plaud_id: str
    title: str
    created_at: str
    file_size: int = 1024


_STATUSES = ("downloaded", "failed", "skipped", "skipped_unknown_project")


def _seed(conn, status: str) -> str:
    """Insert a row with the given starting status, return its plaud_id."""
    plaud_id = f"rec-{status}"
    run_id = start_sync_run(conn, "manual")
    record_recording(
        conn,
        _Meta(plaud_id=plaud_id, title="04-30 X: y", created_at="2026-04-30T00:00:00+00:00"),
        status=status,
        local_path=f"/data/{plaud_id}.mp3" if status == "downloaded" else "",
        run_id=run_id,
        classifier_label="X" if status != "skipped_unknown_project" else "UNKNOWN_PROJ",
    )
    return plaud_id


def _row_status(conn, plaud_id: str) -> str:
    return conn.execute(
        "SELECT status FROM recordings WHERE plaud_id = ?", (plaud_id,),
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# Upgrade transitions: should produce 'downloaded' final state.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("starting_status", ["failed", "skipped", "skipped_unknown_project"])
def test_upgrade_to_downloaded_succeeds(tmp_path, starting_status):
    conn = open_state(tmp_path)
    plaud_id = _seed(conn, starting_status)
    run_id = start_sync_run(conn, "manual")
    record_recording(
        conn,
        _Meta(plaud_id=plaud_id, title="04-30 X: y",
              created_at="2026-04-30T00:00:00+00:00"),
        status="downloaded",
        local_path="/data/upgraded.mp3",
        run_id=run_id,
        classifier_label="X",
    )
    assert _row_status(conn, plaud_id) == "downloaded"
    # local_path also updated (verifies UPDATE branch was taken, not just status)
    row = conn.execute(
        "SELECT local_path FROM recordings WHERE plaud_id = ?", (plaud_id,),
    ).fetchone()
    assert row[0] == "/data/upgraded.mp3"
    conn.close()


# ---------------------------------------------------------------------------
# Immutability: downloaded → anything must be noop.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("attempted_status", _STATUSES)
def test_downloaded_is_sticky_against_all_incoming(tmp_path, attempted_status):
    """Downloaded rows can never be downgraded — the local file is on
    disk, DB row must reflect that. Even attempting to mark as 'downloaded'
    again is a noop (sync.py uses recording_exists_and_downloaded as a
    pre-filter, so this case shouldn't occur in production flow)."""
    conn = open_state(tmp_path)
    plaud_id = _seed(conn, "downloaded")
    run_id = start_sync_run(conn, "manual")
    original_path = "/data/" + plaud_id + ".mp3"

    record_recording(
        conn,
        _Meta(plaud_id=plaud_id, title="modified",
              created_at="2026-04-30T00:00:00+00:00"),
        status=attempted_status,
        local_path="/different/path.mp3",
        run_id=run_id,
        classifier_label="DIFFERENT",
    )

    row = conn.execute(
        "SELECT status, local_path, classifier_label FROM recordings "
        "WHERE plaud_id = ?", (plaud_id,),
    ).fetchone()
    assert row[0] == "downloaded"  # status preserved
    assert row[1] == original_path  # local_path preserved
    assert row[2] == "X"  # label preserved
    conn.close()


# ---------------------------------------------------------------------------
# Non-upgrade transitions: must be noop (preserve original failure reason).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("starting", ["failed", "skipped", "skipped_unknown_project"])
@pytest.mark.parametrize("incoming", ["failed", "skipped", "skipped_unknown_project"])
def test_failure_to_failure_is_noop(tmp_path, starting, incoming):
    """Once a row is in a non-downloaded state, retries that produce
    another non-downloaded state must NOT overwrite the original. The
    original failure reason has diagnostic value (Sentry tagging, retry
    pass behavior); recovering writes the success state via the upgrade
    path tested above."""
    conn = open_state(tmp_path)
    plaud_id = _seed(conn, starting)
    run_id = start_sync_run(conn, "manual")
    record_recording(
        conn,
        _Meta(plaud_id=plaud_id, title="modified",
              created_at="2026-04-30T00:00:00+00:00"),
        status=incoming,
        local_path="",
        run_id=run_id,
        classifier_label="MODIFIED",
    )
    # Status preserved as the ORIGINAL starting value — incoming non-
    # downloaded transitions are rejected.
    assert _row_status(conn, plaud_id) == starting
    conn.close()


# ---------------------------------------------------------------------------
# Idempotency: re-INSERT against same row in same state is noop.
# ---------------------------------------------------------------------------

def test_idempotent_reinsert_skipped(tmp_path):
    """Same status twice in a row → no error, no change."""
    conn = open_state(tmp_path)
    plaud_id = _seed(conn, "skipped")
    run_id = start_sync_run(conn, "manual")
    record_recording(
        conn,
        _Meta(plaud_id=plaud_id, title="04-30 X: y",
              created_at="2026-04-30T00:00:00+00:00"),
        status="skipped",
        local_path="",
        run_id=run_id,
        classifier_label="X",
    )
    assert _row_status(conn, plaud_id) == "skipped"
    conn.close()


# ---------------------------------------------------------------------------
# Same-status metadata refresh: title rename / classification update on
# Plaud's side must propagate to DB even when the status stays the same.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("starting_status", ["skipped", "skipped_unknown_project"])
def test_same_status_refreshes_title_and_classification(tmp_path, starting_status):
    """Bug fix 2026-05-04: when Plaud generates a transcript and renames a
    recording (default '2026-05-04 09:19:03' → 'ALZA: kickoff') and the new
    title now hits a different classifier branch, DB row should reflect the
    new title + label + source + folder. Pre-fix UPSERT was a noop on
    same-status retries → UI displayed stale title forever.

    Stays-as-skipped scenario: user has audio off + classify_by_name_require_folder
    so even a name match downgrades to skip-source. Status doesn't transition
    but the user-visible metadata (title, project label) does."""
    conn = open_state(tmp_path)
    plaud_id = "rec-renamed"
    run_id_1 = start_sync_run(conn, "manual")
    record_recording(
        conn,
        _Meta(plaud_id=plaud_id, title="2026-05-04 09:19:03",
              created_at="2026-05-04T07:30:00+00:00"),
        status=starting_status,
        local_path="",
        run_id=run_id_1,
        classifier_label="_unclassified" if starting_status == "skipped" else "OldProj",
        classification_source="skip" if starting_status == "skipped" else "name",
    )
    # Plaud rename + new classification on next sync
    run_id_2 = start_sync_run(conn, "manual")
    record_recording(
        conn,
        _Meta(plaud_id=plaud_id, title="2026-05-04 ALZA: kickoff sync s týmem",
              created_at="2026-05-04T07:30:00+00:00"),
        status=starting_status,  # still same status (e.g. audio off blocks transition)
        local_path="",
        run_id=run_id_2,
        classifier_label="ALZA",
        classification_source="name",
        plaud_folder_id="folder-alza-abc",
    )
    row = conn.execute(
        "SELECT title, classifier_label, classification_source, plaud_folder_id "
        "FROM recordings WHERE plaud_id = ?", (plaud_id,)
    ).fetchone()
    assert row[0] == "2026-05-04 ALZA: kickoff sync s týmem", \
        f"title must refresh on same-status retry, got {row[0]!r}"
    assert row[1] == "ALZA"
    assert row[2] == "name"
    assert row[3] == "folder-alza-abc"
    # status preserved
    assert _row_status(conn, plaud_id) == starting_status
    conn.close()


def test_failed_to_failed_preserves_metadata(tmp_path):
    """Counter-case: 'failed' rows preserve original failure metadata across
    retries — the original error context (Sentry tag fingerprint) has
    diagnostic value. Refresh only fires for skipped/skipped_unknown_project."""
    conn = open_state(tmp_path)
    plaud_id = _seed(conn, "failed")
    run_id = start_sync_run(conn, "manual")
    record_recording(
        conn,
        _Meta(plaud_id=plaud_id, title="modified-after-failure",
              created_at="2026-04-30T00:00:00+00:00"),
        status="failed",
        local_path="",
        run_id=run_id,
        classifier_label="DIFFERENT",
    )
    row = conn.execute(
        "SELECT title, classifier_label FROM recordings WHERE plaud_id = ?",
        (plaud_id,),
    ).fetchone()
    # failed → failed is full noop (preserve original failure reason)
    assert row[0] == "04-30 X: y", "failed→failed must preserve original title"
    assert row[1] == "X", "failed→failed must preserve original classifier_label"
    conn.close()
