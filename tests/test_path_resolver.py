"""Unit tests for src/plaudsync/path_resolver.py."""
from __future__ import annotations

import pytest

from plaudsync.path_resolver import _sanitize_folder_name


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Klienti", "Klienti"),                      # safe ASCII
        ("Inbox/Misc", "Inbox_Misc"),                # path separator
        ('a<b>c"d:e\\f|g?h*i', "a_b_c_d_e_f_g_h_i"),  # all Windows-illegal chars
        ("Projekt Česká Alfa", "Projekt Česká Alfa"), # Unicode preserved
        ("", "_unknown"),                            # empty
        ("   ", "_unknown"),                         # whitespace only
        ("!!!", "_unknown"),                         # all-punctuation reduces to empty
        ("emoji_🎉_test", "emoji__test"),            # emoji stripped
    ],
    ids=["safe", "slash", "all_illegal", "unicode", "empty", "whitespace", "punct_only", "emoji"],
)
def test_sanitize_folder_name(raw: str, expected: str) -> None:
    assert _sanitize_folder_name(raw) == expected
