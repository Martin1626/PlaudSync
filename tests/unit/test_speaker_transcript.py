from plaudsync.speakers.transcript import (
    cluster_labels,
    is_default_label,
    relabel,
    replace_in_summary,
)


def _seg(speaker, original="Speaker 1"):
    return {"speaker": speaker, "original_speaker": original, "content": "x"}


def test_is_default_label():
    assert is_default_label("Speaker 12")
    assert not is_default_label("Jan")
    assert not is_default_label("Speaker 1 a")


def test_cluster_labels_majority():
    segs = [_seg("Jan"), _seg("Speaker 1"), _seg("Jan")]
    assert cluster_labels(segs) == {"Speaker 1": "Jan"}


def test_relabel_only_target_cluster_and_inputs_untouched():
    segs = [_seg("Speaker 1", "Speaker 1"), _seg("Speaker 2", "Speaker 2")]
    out = relabel(segs, {"Speaker 1": "Jan"})
    assert [s["speaker"] for s in segs] == ["Speaker 1", "Speaker 2"]
    assert [s["speaker"] for s in out] == ["Jan", "Speaker 2"]
    assert out[0] is not segs[0]


def test_replace_speaker_1_not_speaker_10():
    assert replace_in_summary("Speaker 1 a Speaker 10", "Speaker 1", "Eva") == (
        "Eva a Speaker 10",
        1,
    )


def test_replace_handles_wrappers():
    for text, expected in [
        ("[Speaker 2]", "[Eva]"),
        ("*Speaker 2*", "*Eva*"),
        ("**Speaker 2:**", "**Eva:**"),
    ]:
        assert replace_in_summary(text, "Speaker 2", "Eva") == (expected, 1)


def test_replace_escapes_regex_and_diacritics():
    assert replace_in_summary("Jiří (PM) řekl", "Jiří (PM)", "Jiří Novák") == (
        "Jiří Novák řekl",
        1,
    )


def test_replace_no_match_returns_zero():
    assert replace_in_summary("nothing", "Speaker 3", "Eva") == ("nothing", 0)
