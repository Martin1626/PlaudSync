"""Unit tests for plaudsync.auth.mask_token."""
from __future__ import annotations

from plaudsync.auth import mask_token


def test_long_token_renders_first_8_bullets_last_4() -> None:
    token = "secret123abcdefghijklmnXYZ9"  # 27 chars
    masked = mask_token(token)

    assert masked.startswith("secret12")
    assert masked.endswith("XYZ9")
    assert masked.count("•") == 15
    assert len(masked) == 8 + 15 + 4
    # Critical: the 12-char middle substring must NOT leak in any form
    assert "abcdefghijklm" not in masked


def test_short_token_falls_back_to_20_bullets() -> None:
    masked = mask_token("short")  # 5 chars

    assert masked == "•" * 20


def test_exact_boundary_12_chars_masks_with_no_overlap() -> None:
    token = "abcdefgh1234"  # exactly 12 chars
    masked = mask_token(token)

    assert masked.startswith("abcdefgh")
    assert masked.endswith("1234")
    assert masked.count("•") == 15
