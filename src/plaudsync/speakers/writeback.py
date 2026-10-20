import json
from typing import Literal

from loguru import logger

from plaudsync.speakers.transcript import cluster_labels, relabel, replace_in_summary

_TRANSCRIPT_TYPES = ("transaction", "transaction_polish")


def _summary_update(
    client, plaud_id: str, replacements: list[tuple[str, str]], remaining_labels: set[str]
) -> tuple[dict, str] | None:
    """Pure: (note, new_content) if the summary needs a write, else None."""
    note = next(
        (n for n in client.fetch_notes(plaud_id) if n.get("data_type") == "auto_sum_note"),
        None,
    )
    if note is None:
        return None
    content = note.get("data_content")
    if not isinstance(content, str) or content.lstrip().startswith("{"):
        return None
    hits = 0
    for old, new in replacements:
        if not old or old in remaining_labels:
            continue
        content, n = replace_in_summary(content, old, new)
        hits += n
    return (note, content) if hits else None


def fix_summary(
    client, plaud_id: str, replacements: list[tuple[str, str]], remaining_labels: set[str]
) -> bool:
    update = _summary_update(client, plaud_id, replacements, remaining_labels)
    if update is None:
        return False
    client.update_note(plaud_id, update[0], update[1])
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

    prepared = []
    for item in client.fetch_detail(plaud_id).content_list:
        if item.data_type in _TRANSCRIPT_TYPES and item.task_status == 1:
            source = json.loads(client.download_content_text(item))
            if not isinstance(source, list):
                raise ValueError("transcript source is not a list")
            prepared.append((item, relabel(source, renames)))

    remaining = {renames.get(c, label) for c, label in expected_labels.items()}
    summary = _summary_update(
        client, plaud_id, [(expected_labels[c], new) for c, new in renames.items()], remaining
    )

    # trans_result is the commit point and is written last: its old labels are what lets the
    # next run's conflict check pass, so any earlier failure is retried (all writes idempotent).
    for item, relabeled in prepared:
        client.update_transcript_source(plaud_id, item.data_type, item.data_id, relabeled)
    if summary is not None:
        client.update_note(plaud_id, summary[0], summary[1])
    client.patch_trans_result(plaud_id, relabel(segments, renames))
    return "written"
