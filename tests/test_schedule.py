"""Unit tests for plaudsync.schedule — work-hours gating + interval logic.

Pure logic, no network, no filesystem (except the load/save helpers, which
use tmp_path). Time inputs are explicit datetimes so the tests are
deterministic across timezones.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plaudsync.schedule import (
    DEFAULT_OFF_INTERVAL_MIN,
    DEFAULT_WORK_INTERVAL_MIN,
    Schedule,
    ScheduleValidationError,
    applicable_interval_minutes,
    is_within_work_hours,
    load_schedule,
    parse_schedule,
    save_schedule,
    schedule_path,
    should_run_now,
)


# Mon = 2026-04-27, Sat = 2026-05-02. Use UTC datetimes so test math is
# deterministic; the schedule logic operates on whichever tz is passed in.
def _dt(weekday_offset: int, hh: int, mm: int = 0) -> datetime:
    base = datetime(2026, 4, 27, tzinfo=timezone.utc)  # a Monday
    return (base + timedelta(days=weekday_offset)).replace(hour=hh, minute=mm)


# ---------------------------------------------------------------------------
# parse_schedule
# ---------------------------------------------------------------------------


def test_parse_none_returns_defaults() -> None:
    s = parse_schedule(None)
    assert s.work_hours_interval_minutes == DEFAULT_WORK_INTERVAL_MIN
    assert s.off_hours_interval_minutes == DEFAULT_OFF_INTERVAL_MIN
    assert s.work_days == (1, 2, 3, 4, 5)
    assert s.work_from == "08:00"
    assert s.work_to == "16:00"


def test_parse_full_payload_round_trips() -> None:
    payload = {
        "work_hours_interval_minutes": 10,
        "off_hours_interval_minutes": 90,
        "work_days": [1, 3, 5],
        "work_from": "09:30",
        "work_to": "17:45",
    }
    s = parse_schedule(payload)
    assert s.work_hours_interval_minutes == 10
    assert s.off_hours_interval_minutes == 90
    assert s.work_days == (1, 3, 5)
    assert s.work_from == "09:30"
    assert s.work_to == "17:45"
    assert s.to_dict() == {**payload, "work_days": [1, 3, 5]}


def test_parse_negative_interval_rejected() -> None:
    with pytest.raises(ScheduleValidationError) as exc:
        parse_schedule({"work_hours_interval_minutes": 0})
    assert any("work_hours_interval_minutes" in m for m in exc.value.args[0])


def test_parse_invalid_weekday_rejected() -> None:
    with pytest.raises(ScheduleValidationError):
        parse_schedule({"work_days": [0, 8, "Mon"]})


def test_parse_inverted_window_rejected() -> None:
    with pytest.raises(ScheduleValidationError) as exc:
        parse_schedule({"work_from": "18:00", "work_to": "09:00"})
    assert any("earlier" in m for m in exc.value.args[0])


def test_parse_malformed_hhmm_rejected() -> None:
    with pytest.raises(ScheduleValidationError):
        parse_schedule({"work_from": "8:00am"})


# ---------------------------------------------------------------------------
# is_within_work_hours / applicable_interval
# ---------------------------------------------------------------------------


def test_work_day_inside_hours_uses_work_interval() -> None:
    s = Schedule()
    monday_10am = _dt(0, 10)
    assert is_within_work_hours(s, monday_10am)
    assert applicable_interval_minutes(s, monday_10am) == 15


def test_work_day_outside_hours_uses_off_interval() -> None:
    s = Schedule()
    monday_7am = _dt(0, 7)
    monday_8pm = _dt(0, 20)
    assert not is_within_work_hours(s, monday_7am)
    assert not is_within_work_hours(s, monday_8pm)
    assert applicable_interval_minutes(s, monday_7am) == 60
    assert applicable_interval_minutes(s, monday_8pm) == 60


def test_weekend_always_off_hours() -> None:
    s = Schedule()
    saturday_10am = _dt(5, 10)
    assert not is_within_work_hours(s, saturday_10am)
    assert applicable_interval_minutes(s, saturday_10am) == 60


def test_boundary_at_work_to_is_off_hours() -> None:
    """work_to is exclusive — exactly 16:00 falls into off-hours."""
    s = Schedule()
    monday_4pm = _dt(0, 16)
    assert not is_within_work_hours(s, monday_4pm)


# ---------------------------------------------------------------------------
# should_run_now
# ---------------------------------------------------------------------------


def test_no_prior_success_runs() -> None:
    s = Schedule()
    assert should_run_now(s, now=_dt(0, 10), last_success_iso=None) is True


def test_run_when_elapsed_exceeds_work_interval() -> None:
    s = Schedule()
    now = _dt(0, 10)
    last = (now - timedelta(minutes=20)).isoformat()
    assert should_run_now(s, now=now, last_success_iso=last) is True


def test_skip_when_within_work_interval() -> None:
    s = Schedule()
    now = _dt(0, 10)
    last = (now - timedelta(minutes=5)).isoformat()
    assert should_run_now(s, now=now, last_success_iso=last) is False


def test_skip_when_within_off_interval() -> None:
    s = Schedule()
    saturday_noon = _dt(5, 12)
    last = (saturday_noon - timedelta(minutes=30)).isoformat()
    assert should_run_now(s, now=saturday_noon, last_success_iso=last) is False


def test_run_when_off_interval_exceeded() -> None:
    s = Schedule()
    saturday_noon = _dt(5, 12)
    last = (saturday_noon - timedelta(minutes=70)).isoformat()
    assert should_run_now(s, now=saturday_noon, last_success_iso=last) is True


def test_grace_window_allows_slight_early_tick() -> None:
    """Task Scheduler ticks may arrive a few seconds early — must still fire."""
    s = Schedule()
    now = _dt(0, 10)
    # 14 min 50 s elapsed against 15 min interval → grace covers the gap.
    last = (now - timedelta(minutes=14, seconds=50)).isoformat()
    assert should_run_now(s, now=now, last_success_iso=last) is True


def test_invalid_iso_treated_as_no_prior_run() -> None:
    s = Schedule()
    assert should_run_now(s, now=_dt(0, 10), last_success_iso="not-iso") is True


def test_naive_timestamps_skip_safety_check() -> None:
    """Naive last_success_iso can't be compared safely → run rather than skip."""
    s = Schedule()
    naive_last = datetime(2026, 4, 27, 9, 50).isoformat()  # no tz
    assert (
        should_run_now(s, now=_dt(0, 10), last_success_iso=naive_last) is True
    )


# ---------------------------------------------------------------------------
# load/save round-trip
# ---------------------------------------------------------------------------


def test_load_returns_defaults_on_missing_file(tmp_path: Path) -> None:
    s = load_schedule(tmp_path)
    assert s == Schedule()


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    save_schedule(tmp_path, Schedule(work_hours_interval_minutes=20))
    assert schedule_path(tmp_path).exists()
    loaded = load_schedule(tmp_path)
    assert loaded.work_hours_interval_minutes == 20


def test_load_falls_back_to_defaults_on_garbage_json(tmp_path: Path) -> None:
    p = schedule_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert load_schedule(tmp_path) == Schedule()


def test_load_falls_back_to_defaults_on_invalid_payload(tmp_path: Path) -> None:
    p = schedule_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"work_days": [0, 99]}', encoding="utf-8")
    assert load_schedule(tmp_path) == Schedule()
