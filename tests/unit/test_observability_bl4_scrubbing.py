"""BL-4/BL-X scrubbing rules — signed S3 URLs + long string truncation.

Defense-in-depth tests on top of existing scrubbing patterns (paths, labels,
bearer tokens). Per spec §7 these defend against accidental f-string leak
of transcript content or signed URLs into Sentry events.
"""
from __future__ import annotations

from plaudsync.observability import _scrub_string, scrub_event


def test_scrub_signed_s3_url_in_message() -> None:
    text = (
        "fetched https://prod.plaud-content-storage.s3.amazonaws.com/"
        "abc?X-Amz-Signature=xyz&X-Amz-Credential=AKIA..."
    )
    out = _scrub_string(text)
    assert "amazonaws.com" not in out
    assert "<S3_URL_REDACTED>" in out


def test_scrub_signed_s3_url_in_dict_value() -> None:
    """Recursive scrub via scrub_event."""
    event = {
        "extra": {
            "data_link": "https://euc1-prod.s3.amazonaws.com/file?signed=xyz",
        }
    }
    out = scrub_event(event, hint={})
    assert out is not None
    assert "amazonaws.com" not in str(out)


def test_scrub_truncates_long_strings() -> None:
    long_text = "x" * 600
    out = _scrub_string(long_text)
    assert len(out) <= 600  # has truncation marker added
    assert "<TRUNCATED>" in out


def test_scrub_does_not_truncate_short_strings() -> None:
    short = "this is a normal log message"
    out = _scrub_string(short)
    assert "<TRUNCATED>" not in out
    assert out == short


def test_scrub_truncate_at_500_char_boundary() -> None:
    text = "a" * 500
    out = _scrub_string(text)
    assert "<TRUNCATED>" not in out
    text501 = "a" * 501
    out501 = _scrub_string(text501)
    assert "<TRUNCATED>" in out501


def test_scrub_s3_url_runs_before_truncation() -> None:
    """A signed URL longer than 500 chars must still scrub the host pattern,
    not just truncate (truncation alone could leak the host prefix)."""
    long_url = (
        "https://" + ("a" * 50) + ".amazonaws.com/" + ("b" * 600)
        + "?X-Amz-Signature=xyz"
    )
    out = _scrub_string(long_url)
    assert "amazonaws.com" not in out
    assert "<S3_URL_REDACTED>" in out
