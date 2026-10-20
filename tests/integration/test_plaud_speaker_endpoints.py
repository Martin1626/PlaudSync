"""Cassette tests for the speaker write-back endpoints of PlaudClient.

Recorded once against a real recording lent by the user. Every write test
writes back EXACTLY what it read in the same test, so recording leaves the
recording unchanged. To re-record (follow .claude/skills/cassette-refresh):
    VCR_RECORD_MODE=once .venv/Scripts/python.exe -m pytest tests/integration/test_plaud_speaker_endpoints.py

Auto-scrubbed (tests/conftest.py): Authorization, titles, summary/outline
text, note content, segment content + non-default speaker names, signed S3
URLs (request + data_link), request bodies > 200 bytes.
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock

import pytest
from dotenv import load_dotenv

from plaudsync.auth import PlaudTokenExpired, load_token
from plaudsync.plaud_client import PlaudClient, PlaudWriteRejected

FILE_ID = "dcab87413de199472cdd0524b151f601"
VCR = pytest.mark.vcr(
    cassette_library_dir="tests/cassettes/test_plaud_speaker_endpoints",
    decode_compressed_response=True,
)


def _token() -> str:
    load_dotenv()
    if os.getenv("VCR_RECORD_MODE"):
        return load_token()
    return "test-token"


def _guard_live_write(payload: object) -> None:
    """While recording, refuse to write anything that looks scrubbed — the
    write would land on the user's real recording."""
    if os.getenv("VCR_RECORD_MODE"):
        text = json.dumps(payload, ensure_ascii=False)
        assert payload and "<redacted" not in text


@VCR
def test_fetch_trans_result_returns_segments() -> None:
    with PlaudClient(_token()) as client:
        segments = client.fetch_trans_result(FILE_ID)

    assert isinstance(segments, list) and segments
    for seg in segments:
        assert "start_time" in seg and "end_time" in seg and "speaker" in seg


@VCR
def test_patch_trans_result_accepts() -> None:
    with PlaudClient(_token()) as client:
        segments = client.fetch_trans_result(FILE_ID)
        assert segments
        _guard_live_write(segments)
        client.patch_trans_result(FILE_ID, segments)


@VCR
def test_update_transcript_source_accepts() -> None:
    with PlaudClient(_token()) as client:
        item = next(
            i for i in client.fetch_detail(FILE_ID).content_list
            if i.data_type == "transaction" and i.task_status == 1
        )
        segments = json.loads(client.download_content_text(item))
        assert isinstance(segments, list) and segments
        _guard_live_write(segments)
        client.update_transcript_source(FILE_ID, item.data_type, item.data_id, segments)


@VCR
def test_fetch_notes_contains_auto_sum_note() -> None:
    with PlaudClient(_token()) as client:
        notes = client.fetch_notes(FILE_ID)

    assert any(n.get("data_type") == "auto_sum_note" for n in notes)


@VCR
def test_update_note_accepts() -> None:
    with PlaudClient(_token()) as client:
        note = next(n for n in client.fetch_notes(FILE_ID) if n.get("data_type") == "auto_sum_note")
        content = note["data_content"]
        assert isinstance(content, str) and content
        _guard_live_write(content)
        client.update_note(FILE_ID, note, content)


def _offline_client(status_code: int, body: object) -> PlaudClient:
    client = object.__new__(PlaudClient)
    client._base_url = "https://api.example.invalid"
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    client._session = MagicMock()
    client._session.request.return_value = resp
    return client


_WRITES = {
    "patch_trans_result": lambda c: c.patch_trans_result("p", [{"speaker": "Speaker 1"}]),
    "update_transcript_source": lambda c: c.update_transcript_source(
        "p", "transaction", "d", [{"speaker": "Speaker 1"}]),
    "update_note": lambda c: c.update_note(
        "p", {"data_type": "auto_sum_note", "data_id": "n", "data_title": "t"}, "x"),
}
_READS = {
    "fetch_trans_result": lambda c: c.fetch_trans_result("p"),
    "fetch_notes": lambda c: c.fetch_notes("p"),
}


def test_write_rejected_raises() -> None:
    client = _offline_client(200, {"status": -1})
    with pytest.raises(PlaudWriteRejected):
        client.patch_trans_result("p", [{"speaker": "Speaker 1"}])


@pytest.mark.parametrize("name", sorted(_WRITES))
def test_every_write_rejected_raises(name: str) -> None:
    client = _offline_client(200, {"status": -1, "msg": "nope"})
    with pytest.raises(PlaudWriteRejected) as exc:
        _WRITES[name](client)
    assert "Speaker" not in str(exc.value)
    kwargs = client._session.request.call_args.kwargs
    assert kwargs["timeout"] == 60


@pytest.mark.parametrize("name", sorted({**_WRITES, **_READS}))
def test_every_method_raises_token_expired_on_401(name: str) -> None:
    client = _offline_client(401, {})
    with pytest.raises(PlaudTokenExpired):
        {**_WRITES, **_READS}[name](client)


def test_update_note_payload_matches_web_app() -> None:
    client = _offline_client(200, {"status": 0})
    client.update_note("p", {"data_type": "auto_sum_note", "data_id": "n1",
                             "data_title": "Summary", "data_tab_name": "ignored"}, "body")
    assert client._session.request.call_args.kwargs["json"] == {
        "file_id": "p", "note_type": "auto_sum_note", "note_title": "Summary",
        "note_content": "body", "note_id": "n1",
    }

    client.update_note("p", {"data_type": "custom_note", "data_id": "n2",
                             "data_title": "T", "data_tab_name": "Tab"}, "body")
    assert client._session.request.call_args.kwargs["json"]["note_tab_name"] == "Tab"
