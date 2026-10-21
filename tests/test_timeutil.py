"""GTFS time rules: >24:00 times, service-day reference, Melbourne DST transitions."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from movemelbourne.utils.timeutil import (
    MELBOURNE,
    candidate_service_dates,
    epoch_to_local,
    parse_gtfs_time,
    scheduled_epoch,
    service_day_reference_epoch,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("00:00:00", 0), ("04:57:00", 17_820), ("25:12:00", 90_720), (" 5:00:00", 18_000),
     ("", None), (None, None)],
)
def test_parse_gtfs_time(raw, expected):
    assert parse_gtfs_time(raw) == expected


def test_parse_gtfs_time_rejects_garbage():
    with pytest.raises(ValueError):
        parse_gtfs_time("12:61:00")


def test_ordinary_day_reference_is_local_midnight():
    ref = service_day_reference_epoch("20261020")
    assert epoch_to_local(ref) == datetime(2026, 10, 20, 0, 0, tzinfo=MELBOURNE)


def test_after_midnight_trip_lands_on_next_calendar_day():
    # A 25:12 stop on service date Tue 20 Oct happens at 01:12 on Wed 21 Oct.
    local = epoch_to_local(scheduled_epoch("20261020", "25:12:00"))
    assert (local.date(), local.hour, local.minute) == (date(2026, 10, 21), 1, 12)


def test_dst_start_day_reference_is_eleven_pm_previous_day():
    # Clocks go forward at 02:00 AEST on Sun 4 Oct 2026. Noon is AEDT (+11), so noon minus 12h is
    # 23:00 AEST on Saturday: the GTFS reference is NOT local midnight on this day.
    ref = epoch_to_local(service_day_reference_epoch("20261004"))
    assert (ref.day, ref.hour) == (3, 23)
    # Elapsed time stays monotonic across the skipped hour: 01:59 -> 03:00 is 61 real minutes,
    # and 03:00 elapsed lands exactly on the 03:00 AEDT wall clock just after the change.
    a = scheduled_epoch("20261004", "01:59:00")
    b = scheduled_epoch("20261004", "03:00:00")
    assert b - a == 61 * 60
    assert epoch_to_local(b).hour == 3
    assert epoch_to_local(b).utcoffset().total_seconds() == 11 * 3600


def test_dst_end_day_reference_is_one_am_local():
    # Clocks go back at 03:00 AEDT on Sun 5 Apr 2026. Noon is AEST (+10); noon minus 12h is
    # 01:00 AEDT, so the reference is not local midnight on this day (GTFS spec rule).
    ref = epoch_to_local(service_day_reference_epoch("20260405"))
    assert (ref.day, ref.hour) == (5, 1)
    # A trip timetabled across the change still has the elapsed time the timetable says.
    assert scheduled_epoch("20260405", "04:00:00") - scheduled_epoch("20260405", "01:00:00") == 3 * 3600


def test_service_day_spanning_dst_change_has_25_hour_span():
    # Service date Sat 4 Apr 2026 runs into the Sunday change; "26:30" is still +26.5h of elapsed time.
    ref = service_day_reference_epoch("20260404")
    assert scheduled_epoch("20260404", "26:30:00") - ref == 26.5 * 3600


def test_candidate_service_dates_for_early_morning_event():
    epoch = scheduled_epoch("20261020", "24:40:00")  # 00:40 on 21 Oct
    assert candidate_service_dates(epoch) == (date(2026, 10, 21), date(2026, 10, 20))
