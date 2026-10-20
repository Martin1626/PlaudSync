import re
from collections import Counter

DEFAULT_LABEL = re.compile(r"^Speaker \d+$")


def is_default_label(label: str) -> bool:
    return bool(DEFAULT_LABEL.match(label))


def cluster_key(seg: dict) -> str:
    return str(seg.get("original_speaker") or seg.get("speaker") or "").strip()


def cluster_labels(segments: list[dict]) -> dict[str, str]:
    counts: dict[str, Counter] = {}
    for seg in segments:
        key = cluster_key(seg)
        label = str(seg.get("speaker") or "").strip()
        if key and label:
            counts.setdefault(key, Counter())[label] += 1
    # Counter.most_common keeps first-seen order among ties (insertion-ordered sort).
    return {key: c.most_common(1)[0][0] for key, c in counts.items()}


def relabel(segments: list[dict], renames: dict[str, str]) -> list[dict]:
    out = []
    for seg in segments:
        copy = dict(seg)
        key = cluster_key(seg)
        if key in renames:
            copy["speaker"] = renames[key]
        out.append(copy)
    return out


def replace_in_summary(text: str, old: str, new: str) -> tuple[str, int]:
    # (?!\d) keeps "Speaker 1" from rewriting "Speaker 10".
    pattern = re.compile(rf"(?<!\w){re.escape(old)}(?!\d)")
    return pattern.subn(lambda _m: new, text)
