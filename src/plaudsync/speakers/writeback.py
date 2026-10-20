import json
from typing import Literal

from loguru import logger

from plaudsync.speakers.transcript import cluster_labels, relabel, replace_in_summary

_TRANSCRIPT_TYPES = ("transaction", "transaction_polish")


def fix_summary(
    client, plaud_id: str, replacements: list[tuple[str, str]], remaining_labels: set[str]
) -> bool:
    note = next(
        (n for n in client.fetch_notes(plaud_id) if n.get("data_type") == "auto_sum_note"),
        None,
    )
    if note is None:
        return False
    content = note.get("data_content")
    if not isinstance(content, str) or content.lstrip().startswith("{"):
        return False
    hits = 0
    for old, new in replacements:
        if not old or old in remaining_labels:
            continue
        content, n = replace_in_summary(content, old, new)
        hits += n
    if hits == 0:
        return False
    client.update_note(plaud_id, note, content)
    return True


def apply_renames(
    client, plaud_id: str, renames: dict[str, str], expected_labels: dict[str, str]
) -> Literal["written", "conflict"]:
    renames = {c: n for c, n in renames.items() if c in expected_labels}
    if not renames:
        raise ValueError("no renamable clusters")

    segments = client.fetch_trans_result(plaud_id)
    if segments is None or cluster_labels(segments) != expected_labels:
        logger.bind(plaud_id=plaud_id).info("speaker labels changed in Plaud; skipping write")
        return "conflict"

    client.patch_trans_result(plaud_id, relabel(segments, renames))
    for item in client.fetch_detail(plaud_id).content_list:
        if item.data_type in _TRANSCRIPT_TYPES and item.task_status == 1:
            source = json.loads(client.download_content_text(item))
            client.update_transcript_source(
                plaud_id, item.data_type, item.data_id, relabel(source, renames)
            )

    remaining = {renames.get(c, label) for c, label in expected_labels.items()}
    fix_summary(
        client, plaud_id, [(expected_labels[c], new) for c, new in renames.items()], remaining
    )
    return "written"
