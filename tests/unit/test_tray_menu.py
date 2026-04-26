"""menu — pystray Menu builder + title formatting."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from plaudsync.tray.menu import format_status_title
from plaudsync.tray.scheduler_loop import TrayStatus


def test_title_idle_with_recent_sync():
    now = datetime(2026, 4, 26, 12, 0, 0).astimezone()
    last = (now - timedelta(minutes=12)).isoformat(timespec="seconds")
    title = format_status_title(TrayStatus(kind="idle", last_sync_iso=last), now=now)
    assert "12 min ago" in title
    assert "PlaudSync" in title


def test_title_idle_never_synced():
    now = datetime(2026, 4, 26, 12, 0, 0).astimezone()
    title = format_status_title(TrayStatus(kind="idle", last_sync_iso=None), now=now)
    assert "never synced" in title


def test_title_running():
    now = datetime(2026, 4, 26, 12, 0, 0).astimezone()
    title = format_status_title(TrayStatus(kind="running"), now=now)
    assert "running" in title.lower()


def test_title_error_includes_kind():
    now = datetime(2026, 4, 26, 12, 0, 0).astimezone()
    title = format_status_title(TrayStatus(kind="error", error_kind="token_expired"), now=now)
    assert "error" in title.lower()
    assert "token expired" in title.lower()


def test_title_paused():
    now = datetime(2026, 4, 26, 12, 0, 0).astimezone()
    title = format_status_title(TrayStatus(kind="paused"), now=now)
    assert "paused" in title.lower()


def test_title_recent_sync_uses_seconds_grain_under_minute():
    now = datetime(2026, 4, 26, 12, 0, 0).astimezone()
    last = (now - timedelta(seconds=30)).isoformat(timespec="seconds")
    title = format_status_title(TrayStatus(kind="idle", last_sync_iso=last), now=now)
    assert "just now" in title.lower() or "30 s" in title.lower()


def test_title_old_sync_uses_hours_grain():
    now = datetime(2026, 4, 26, 12, 0, 0).astimezone()
    last = (now - timedelta(hours=3, minutes=15)).isoformat(timespec="seconds")
    title = format_status_title(TrayStatus(kind="idle", last_sync_iso=last), now=now)
    assert "h ago" in title.lower() or "hour" in title.lower()
