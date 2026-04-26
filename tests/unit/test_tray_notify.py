"""notify — error notification dispatcher s 30 min sliding-window debounce."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from plaudsync.tray.notify import ErrorNotifier, exit_code_to_notification


def test_exit_code_2_maps_to_token_expired():
    title, msg = exit_code_to_notification(2)
    assert "token expired" in title.lower()
    assert "settings" in msg.lower()


def test_exit_code_3_maps_to_token_missing():
    title, msg = exit_code_to_notification(3)
    assert "token missing" in title.lower()


def test_exit_code_5_returns_none_skip_notification():
    """Exit 5 = skipped per schedule, not an error."""
    assert exit_code_to_notification(5) is None


def test_exit_code_0_returns_none():
    assert exit_code_to_notification(0) is None


def test_exit_code_unknown_maps_to_generic_failed():
    title, msg = exit_code_to_notification(99)
    assert "failed" in title.lower()


def test_notifier_calls_dispatcher_on_first_error():
    sent: list[tuple[str, str]] = []
    n = ErrorNotifier(dispatcher=lambda t, m: sent.append((t, m)))
    now = datetime(2026, 4, 26, 10, 0, 0)
    n.notify(2, now=now)
    assert len(sent) == 1


def test_notifier_debounces_same_kind_within_30min():
    sent: list[tuple[str, str]] = []
    n = ErrorNotifier(dispatcher=lambda t, m: sent.append((t, m)))
    n.notify(2, now=datetime(2026, 4, 26, 10, 0, 0))
    n.notify(2, now=datetime(2026, 4, 26, 10, 25, 0))  # 25 min, < 30 → debounced
    assert len(sent) == 1


def test_notifier_emits_again_after_30min():
    sent: list[tuple[str, str]] = []
    n = ErrorNotifier(dispatcher=lambda t, m: sent.append((t, m)))
    n.notify(2, now=datetime(2026, 4, 26, 10, 0, 0))
    n.notify(2, now=datetime(2026, 4, 26, 10, 31, 0))  # > 30 min → emit
    assert len(sent) == 2


def test_notifier_different_kinds_independent():
    sent: list[tuple[str, str]] = []
    n = ErrorNotifier(dispatcher=lambda t, m: sent.append((t, m)))
    now = datetime(2026, 4, 26, 10, 0, 0)
    n.notify(2, now=now)
    n.notify(3, now=now)  # different kind → emit
    assert len(sent) == 2


def test_notifier_skips_non_error_codes():
    sent: list[tuple[str, str]] = []
    n = ErrorNotifier(dispatcher=lambda t, m: sent.append((t, m)))
    n.notify(0, now=datetime(2026, 4, 26, 10, 0, 0))
    n.notify(5, now=datetime(2026, 4, 26, 10, 0, 0))
    assert sent == []
