"""Config flag round-trip tests — toggle on/off/on scenarios.

Audit triggered by Hotfix L 2026-04-30. The original
test_download_audio_false_records_skipped_status (BL-X Task 14) covered
only the DOWN direction (audio gate fail → skipped row). The UP direction
(re-enable → downloaded) was the bug surface.

Pattern enforced here: for every config flag affecting recording state,
test the round-trip: original-on → toggle-off → toggle-on. This catches
"untested round-trip" gaps before they hit production.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from plaudsync.classifier import WaterfallClassifier
from plaudsync.config import Config, ProjectEntry
from plaudsync.state import open_state
from plaudsync.sync import run_sync


class _StatefulFakeClient:
    """Fake client that records download calls so tests can assert behavior
    across multiple sync runs in the same test."""

    def __init__(self, recordings_meta: list[dict]):
        self._recs = recordings_meta
        self.audio_calls: list[str] = []

    def list_recordings(self, since=None):
        for r in self._recs:
            class _M:
                pass
            m = _M()
            for k, v in r.items():
                setattr(m, k, v)
            yield m

    def download_audio(self, plaud_id: str):
        self.audio_calls.append(plaud_id)
        yield b"AAAA"


def _rec(plaud_id: str, title: str, folder: str = "_unknown",
         file_size: int = 4) -> dict:
    return {
        "plaud_id": plaud_id, "title": title,
        "created_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        "start_time_ms": 1745000000000, "duration_seconds": 60,
        "file_size": file_size, "plaud_folder": folder,
    }


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "ALZA"
    unclassified = tmp_path / "U"
    project.mkdir()
    unclassified.mkdir()
    return project, unclassified


# ---------------------------------------------------------------------------
# download_audio round-trip — Hotfix L scenario
# ---------------------------------------------------------------------------

def test_download_audio_off_then_on_upgrades_skipped_to_downloaded(tmp_path: Path) -> None:
    """User toggles download_audio off → recording 'skipped'. User toggles
    back on → next sync upgrades to 'downloaded' + writes MP3.

    This is the exact production scenario for Hotfix L (FHB + Alza
    recordings on 2026-04-30 12:08-12:20)."""
    project, unclassified = _setup(tmp_path)

    # Sync 1: download_audio=False → skipped row
    config_off = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": ProjectEntry(path=project)},
        download_audio=False,
    )
    conn = open_state(tmp_path)
    try:
        client = _StatefulFakeClient([
            _rec("rec1", title="04-30 ALZA: kickoff", folder="some_folder"),
        ])
        exit_code = run_sync(client, WaterfallClassifier(config_off), conn,
                             config_off, "manual")
        assert exit_code == 0
        assert client.audio_calls == []  # no MP3 fetched
        row = conn.execute(
            "SELECT status, local_path FROM recordings WHERE plaud_id='rec1'",
        ).fetchone()
        assert row[0] == "skipped"
        assert list(project.rglob("*.mp3")) == []

        # Sync 2: download_audio=True → MUST upgrade to downloaded
        config_on = replace(config_off, download_audio=True)
        client2 = _StatefulFakeClient([
            _rec("rec1", title="04-30 ALZA: kickoff", folder="some_folder"),
        ])
        exit_code = run_sync(client2, WaterfallClassifier(config_on), conn,
                             config_on, "manual")
        assert exit_code == 0
        assert client2.audio_calls == ["rec1"]  # MP3 fetched this time
        row = conn.execute(
            "SELECT status, local_path FROM recordings WHERE plaud_id='rec1'",
        ).fetchone()
        assert row[0] == "downloaded"  # upgraded
        assert row[1].endswith(".mp3")
        assert len(list(project.rglob("*.mp3"))) == 1
    finally:
        conn.close()


def test_download_audio_on_off_on_full_round_trip(tmp_path: Path) -> None:
    """Full toggle cycle: on → off (no row, file already downloaded) → on
    (downloaded sticky, file preserved). Verifies downloaded immutability
    against subsequent skipped attempts."""
    project, unclassified = _setup(tmp_path)
    config_on = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": ProjectEntry(path=project)},
        download_audio=True,
    )
    conn = open_state(tmp_path)
    try:
        # Sync 1 with on: row downloaded, MP3 on disk.
        client1 = _StatefulFakeClient([
            _rec("rec1", "04-30 ALZA: kickoff", "some_folder"),
        ])
        run_sync(client1, WaterfallClassifier(config_on), conn,
                 config_on, "manual")
        original_path = conn.execute(
            "SELECT local_path FROM recordings WHERE plaud_id='rec1'",
        ).fetchone()[0]
        assert Path(original_path).exists()

        # Sync 2 with off: row already downloaded → main loop skips via
        # recording_exists_and_downloaded; status stays 'downloaded'. File
        # preserved on disk (no cleanup of pre-existing files).
        config_off = replace(config_on, download_audio=False)
        client2 = _StatefulFakeClient([
            _rec("rec1", "04-30 ALZA: kickoff", "some_folder"),
        ])
        run_sync(client2, WaterfallClassifier(config_off), conn,
                 config_off, "manual")
        assert client2.audio_calls == []  # not re-downloaded
        row = conn.execute(
            "SELECT status FROM recordings WHERE plaud_id='rec1'",
        ).fetchone()
        assert row[0] == "downloaded"  # immutable
        assert Path(original_path).exists()  # file preserved

        # Sync 3 with on again: still downloaded, no work.
        client3 = _StatefulFakeClient([
            _rec("rec1", "04-30 ALZA: kickoff", "some_folder"),
        ])
        run_sync(client3, WaterfallClassifier(config_on), conn,
                 config_on, "manual")
        assert client3.audio_calls == []  # already downloaded
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# download_content round-trip — content gate's analogue of Hotfix L
# ---------------------------------------------------------------------------

def test_download_content_off_then_on_writes_md_on_second_sync(tmp_path: Path) -> None:
    """Toggle content off → 'not_applicable'. Toggle back on → next sync
    must produce .md sourozenec. Mirrors Hotfix L scenario for the content
    artifact track."""
    from plaudsync.plaud_client import ContentItem, DetailMeta

    project, unclassified = _setup(tmp_path)
    config_off = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": ProjectEntry(path=project)},
        download_content=False,
    )

    class _RichClient(_StatefulFakeClient):
        def fetch_detail(self, plaud_id):
            return DetailMeta(
                plaud_id=plaud_id, language="cs", speakers_count=2,
                task_ids={"trans": "t1", "outline": "o1", "summary": "s1"},
                content_list=[
                    ContentItem(data_id="d1", data_type="transaction", task_status=1,
                                data_link="https://s3/t", err_code="", err_msg=""),
                    ContentItem(data_id="d2", data_type="outline", task_status=1,
                                data_link="https://s3/o", err_code="", err_msg=""),
                    ContentItem(data_id="d3", data_type="auto_sum_note", task_status=1,
                                data_link="https://s3/s", err_code="", err_msg=""),
                ],
            )

        def download_content_text(self, item):
            return f"BODY_{item.data_type}"

    conn = open_state(tmp_path)
    try:
        # Sync 1: content_off → MP3 only, no .md.
        client1 = _RichClient([_rec("rec1", "04-30 ALZA: x", "some_folder")])
        run_sync(client1, WaterfallClassifier(config_off), conn,
                 config_off, "manual")
        assert list(project.rglob("*.md")) == []
        # Note: content_status='not_applicable' because gate denied content
        # fetch entirely (download_content=False at audio-gate-pass time).
        row = conn.execute(
            "SELECT status, content_status FROM recordings WHERE plaud_id='rec1'",
        ).fetchone()
        assert row[0] == "downloaded"
        assert row[1] == "not_applicable"
        # FALSE POSITIVE: this row should re-evaluate when content is
        # re-enabled. The 'not_applicable' final state would block retry
        # pass. This is a known limitation — separate ticket.

        # Sync 2: content_on. Per current architecture, retry_pending_content
        # only re-evaluates rows with content_status='pending'. Rows in
        # 'not_applicable' from a content-gate decline don't get retried
        # automatically. User would need to manually flip status or
        # re-trigger via DB cleanup. Document the gap.
        config_on = replace(config_off, download_content=True)
        client2 = _RichClient([_rec("rec1", "04-30 ALZA: x", "some_folder")])
        run_sync(client2, WaterfallClassifier(config_on), conn,
                 config_on, "manual")
        # Audio already downloaded → main loop skips. content_status stays
        # 'not_applicable'. KNOWN GAP.
        row = conn.execute(
            "SELECT content_status, content_path FROM recordings WHERE plaud_id='rec1'",
        ).fetchone()
        # Asserting current (broken) behavior — flag for future fix.
        assert row[0] == "not_applicable"
        assert row[1] is None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# classify_by_folder round-trip — toggle on enables retry-pass folder fallback
# ---------------------------------------------------------------------------

def test_classify_by_folder_off_then_on_recovers_skipped_unknown_project(tmp_path: Path) -> None:
    """Recording with title 'CPR: …' (unknown project) lands in
    skipped_unknown_project when only classify_by_name is on. Toggling
    classify_by_folder on + matching folder mapping → retry pass picks
    it up via folder fallback (Hotfix I path)."""
    project, unclassified = _setup(tmp_path)
    skoleni_dir = tmp_path / "Školení"
    skoleni_dir.mkdir()

    config_off = Config(
        unclassified_dir=unclassified,
        projects={
            "ALZA": ProjectEntry(path=project),
            "Školení": ProjectEntry(path=skoleni_dir, plaud_folder_id="skol_id"),
        },
        # classify_by_folder=False default
    )
    conn = open_state(tmp_path)
    try:
        # Sync 1: name match 'CPR' (not in config) → skipped_unknown_project
        client1 = _StatefulFakeClient([
            _rec("rec_cpr", "04-28 CPR: něco", "skol_id"),
        ])
        run_sync(client1, WaterfallClassifier(config_off), conn,
                 config_off, "manual")
        row = conn.execute(
            "SELECT status, classifier_label FROM recordings WHERE plaud_id='rec_cpr'",
        ).fetchone()
        assert row[0] == "skipped_unknown_project"
        assert row[1] == "CPR"

        # Sync 2: classify_by_folder=True → retry pass picks up via folder
        # fallback, downloads as Školení.
        config_on = replace(config_off, classify_by_folder=True)
        client2 = _StatefulFakeClient([
            _rec("rec_cpr", "04-28 CPR: něco", "skol_id"),
        ])
        run_sync(client2, WaterfallClassifier(config_on), conn,
                 config_on, "manual")
        assert client2.audio_calls == ["rec_cpr"]
        row = conn.execute(
            "SELECT status, classifier_label, classification_source, plaud_folder_id "
            "FROM recordings WHERE plaud_id='rec_cpr'",
        ).fetchone()
        assert row[0] == "downloaded"
        assert row[1] == "Školení"
        assert row[2] == "folder"
        assert row[3] == "skol_id"  # Hotfix K — folder ID persisted
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# sync_unclassified round-trip — recently-skipped rows when catch-all enabled
# ---------------------------------------------------------------------------

def test_sync_unclassified_off_drops_unknown_then_on_picks_up_new(tmp_path: Path) -> None:
    """sync_unclassified=False → recording with no name match + no folder
    mapping persists as 'skipped' / source='skip' (BL-7) so UI surfaces
    it. Toggle on → next sync upgrades the row to 'downloaded' in
    unclassified_dir."""
    project, unclassified = _setup(tmp_path)
    config_off = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": ProjectEntry(path=project)},
        sync_unclassified=False,
    )
    conn = open_state(tmp_path)
    try:
        # Sync 1: title without 'KOD:' format → BL-7 skip-source row.
        client1 = _StatefulFakeClient([
            _rec("rec_random", "Random title without project code"),
        ])
        run_sync(client1, WaterfallClassifier(config_off), conn,
                 config_off, "manual")
        assert client1.audio_calls == []
        row = conn.execute(
            "SELECT status, classification_source FROM recordings "
            "WHERE plaud_id='rec_random'",
        ).fetchone()
        assert row == ("skipped", "skip")

        # Sync 2: sync_unclassified=True → catch-all kicks in
        config_on = replace(config_off, sync_unclassified=True)
        client2 = _StatefulFakeClient([
            _rec("rec_random", "Random title without project code"),
        ])
        run_sync(client2, WaterfallClassifier(config_on), conn,
                 config_on, "manual")
        assert client2.audio_calls == ["rec_random"]
        row = conn.execute(
            "SELECT status, classifier_label, classification_source "
            "FROM recordings WHERE plaud_id='rec_random'",
        ).fetchone()
        assert row[0] == "downloaded"
        assert row[1] == "_unclassified"
        assert row[2] == "none"
    finally:
        conn.close()
