import json
from unittest.mock import MagicMock

import pytest

from plaudsync.plaud_client import ContentItem
from plaudsync.speakers.writeback import apply_renames, fix_summary


def _seg(speaker, text="x"):
    return {"speaker": speaker, "original_speaker": speaker, "content": text}


def _item(data_type, data_id, status=1):
    return ContentItem(data_id=data_id, data_type=data_type, task_status=status,
                       data_link="https://example.invalid/x", err_code="")


def _client(segments, notes, items=()):
    c = MagicMock()
    c.fetch_trans_result.return_value = segments
    c.fetch_notes.return_value = notes
    c.fetch_detail.return_value.content_list = list(items)
    c.download_content_text.side_effect = lambda item: json.dumps(segments)
    return c


def _note(content, data_type="auto_sum_note"):
    return {"data_type": data_type, "data_id": "n1", "data_title": "t", "data_content": content}


SEGS = [_seg("Speaker 1"), _seg("Speaker 2")]
EXPECTED = {"Speaker 1": "Speaker 1", "Speaker 2": "Speaker 2"}


def test_conflict_when_labels_changed_writes_nothing():
    c = _client([_seg("Alice"), _seg("Speaker 2")], [_note("Speaker 1 spoke")],
                [_item("transaction", "a")])
    assert apply_renames(c, "p", {"Speaker 1": "Bob"}, EXPECTED) == "conflict"
    c.patch_trans_result.assert_not_called()
    c.update_transcript_source.assert_not_called()
    c.update_note.assert_not_called()


def test_conflict_when_reread_returns_none():
    c = _client(None, [])
    assert apply_renames(c, "p", {"Speaker 1": "Bob"}, EXPECTED) == "conflict"
    c.patch_trans_result.assert_not_called()


def test_no_renamable_clusters_raises():
    c = _client(SEGS, [])
    with pytest.raises(ValueError):
        apply_renames(c, "p", {"Speaker 9": "Bob"}, EXPECTED)


def test_written_updates_three_surfaces_and_summary():
    items = [_item("transaction", "a"), _item("transaction_polish", "b"),
             _item("transaction", "c", status=0), _item("outline", "d")]
    c = _client(SEGS, [_note("Speaker 1 said hi. Speaker 10 left.")], items)
    assert apply_renames(c, "p", {"Speaker 1": "Bob"}, EXPECTED) == "written"
    patched = c.patch_trans_result.call_args.args[1]
    assert [s["speaker"] for s in patched] == ["Bob", "Speaker 2"]
    calls = c.update_transcript_source.call_args_list
    assert [(x.args[1], x.args[2]) for x in calls] == [("transaction", "a"), ("transaction_polish", "b")]
    assert calls[0].args[3][0]["speaker"] == "Bob"
    c.update_note.assert_called_once()
    assert c.update_note.call_args.args[2] == "Bob said hi. Speaker 10 left."


def test_summary_old_name_still_used_by_other_cluster_not_replaced():
    c = _client([], [_note("Anna and Anna")])
    wrote = fix_summary(c, "p", [("Anna", "Bob")], {"Anna"})
    assert wrote is False
    c.update_note.assert_not_called()


def test_summary_already_updated_by_plaud_no_write():
    c = _client([], [_note("Bob said hi")])
    assert fix_summary(c, "p", [("Speaker 1", "Bob")], set()) is False
    c.update_note.assert_not_called()


def test_json_wrapped_note_skipped():
    c = _client([], [_note('  {"ops": "Speaker 1"}')])
    assert fix_summary(c, "p", [("Speaker 1", "Bob")], set()) is False
    c.update_note.assert_not_called()


def test_no_summary_note_returns_false():
    c = _client([], [_note("Speaker 1", data_type="other")])
    assert fix_summary(c, "p", [("Speaker 1", "Bob")], set()) is False
