"""Cassette scrubbers in tests/conftest.py — speaker names + spoken content
must never reach a committed cassette, wherever the segments appear."""
from __future__ import annotations

import json

from vcr.request import Request

from tests.conftest import _redact_request, _redact_response, _scrub_trans_result


def _seg(speaker: str, original: str, content: str = "secret words") -> dict:
    return {"start_time": 0, "end_time": 1000, "speaker": speaker,
            "original_speaker": original, "content": content}


def _response(body: object, content_type: str) -> dict:
    return {
        "status": {"code": 200, "message": "OK"},
        "headers": {"Content-Type": [content_type]},
        "body": {"string": json.dumps(body, ensure_ascii=False).encode("utf-8")},
    }


def test_trans_result_names_and_content_scrubbed() -> None:
    body = json.dumps({"status": 0, "data_file_list": [{"id": "x", "trans_result": [
        _seg("Jan Novák", "Speaker 1"),
        _seg("Speaker 3", "Petra Svobodová"),
        _seg("PlaudSync Test A", "Speaker 2"),
        {"start_time": 5, "end_time": 6, "content": "no speaker key here"},
    ]}]}, ensure_ascii=False)

    out = json.loads(_scrub_trans_result(body))
    segs = out["data_file_list"][0]["trans_result"]

    assert [s["content"] for s in segs] == ["<redacted>"] * 4
    assert [(s.get("speaker"), s.get("original_speaker")) for s in segs] == [
        ("<redacted-name>", "Speaker 1"),
        ("Speaker 3", "<redacted-name>"),
        ("PlaudSync Test A", "Speaker 2"),
        (None, None),
    ]
    assert segs[0]["start_time"] == 0 and segs[0]["end_time"] == 1000


def test_scrub_trans_result_keeps_bytes_type() -> None:
    body = json.dumps([_seg("Jan Novák", "Speaker 1")]).encode("utf-8")
    out = _scrub_trans_result(body)
    assert isinstance(out, bytes)
    assert b"Nov" not in out and b"secret" not in out


def test_list_summary_and_outline_scrubbed() -> None:
    body = {"status": 0, "data_file_list": [{
        "id": "x", "filename": "Meeting with ACME",
        "ai_content": "## Summary of the secret deal",
        "outline_result": [{"start_time": 0, "end_time": 1, "topic": "secret topic"}],
        "trans_result": [_seg("Jan Novák", "Speaker 1")],
    }]}
    out = _redact_response(_response(body, "application/json"))
    text = out["body"]["string"].decode("utf-8")
    assert "secret" not in text
    assert "ACME" not in text
    assert "Nov" not in text
    file0 = json.loads(text)["data_file_list"][0]
    assert file0["trans_result"][0]["original_speaker"] == "Speaker 1"


def test_transcript_source_body_scrubbed_but_still_json() -> None:
    """S3 transcript source = top-level JSON list of segments, served as
    application/json or text/plain. Replay needs it to stay parseable."""
    for ct in ("application/json", "text/plain", "application/octet-stream"):
        segs = [_seg("Jan Novák", "Speaker 1"), _seg("Speaker 2", "Speaker 2")] * 5
        out = _redact_response(_response(segs, ct))
        parsed = json.loads(out["body"]["string"])
        assert [s["speaker"] for s in parsed[:2]] == ["<redacted-name>", "Speaker 2"], ct
        assert all(s["content"] == "<redacted>" for s in parsed), ct


def test_non_segment_text_body_still_redacted() -> None:
    out = _redact_response(_response("## a long markdown summary " * 5, "text/plain"))
    assert out["body"]["string"] in (b"<redacted-content>", "<redacted-content>")


def test_note_content_scrubbed() -> None:
    body = {"status": 0, "data": [{"data_id": "n1", "data_type": "auto_sum_note",
                                   "data_title": "Summary", "data_content": "secret summary",
                                   "data_link": ""}]}
    out = _redact_response(_response(body, "application/json"))
    assert b"secret" not in out["body"]["string"]
    note = json.loads(out["body"]["string"])["data"][0]
    assert note["data_type"] == "auto_sum_note"


def test_large_request_body_redacted_small_kept() -> None:
    big = Request("PATCH", "https://api-euc1.plaud.ai/file/abc",
                  json.dumps({"trans_result": [_seg("Jan Novák", "Speaker 1")] * 5}).encode(), {})
    small = Request("POST", "https://api-euc1.plaud.ai/file/list", b'["abc"]', {})
    assert _redact_request(big).body == b"<redacted-request-body>"
    assert _redact_request(small).body == b'["abc"]'


def test_signed_content_url_and_data_link_share_placeholder() -> None:
    """The signed S3 URL (credentials in the query) is replaced on the request
    and the data_link in /file/detail gets the same placeholder, so replay of
    download_content_text matches the recorded request."""
    s3 = Request("GET", "https://bucket.s3.amazonaws.com/a/b.json"
                        "?X-Amz-Credential=AKIA123&X-Amz-Signature=deadbeef", None, {})
    redacted = _redact_request(s3)
    assert "AKIA" not in redacted.uri and "deadbeef" not in redacted.uri
    assert redacted.uri.startswith("https://")

    api = Request("GET", "https://api-euc1.plaud.ai/file/detail/abc", None, {})
    assert _redact_request(api).uri == api.uri

    detail = {"status": 0, "data": {"content_list": [
        {"data_id": "t1", "data_type": "transaction", "task_status": 1,
         "data_link": "https://bucket.s3.amazonaws.com/a/b.json?X-Amz-Signature=deadbeef"},
    ]}}
    out = _redact_response(_response(detail, "application/json"))
    link = json.loads(out["body"]["string"])["data"]["content_list"][0]["data_link"]
    assert link == redacted.uri
