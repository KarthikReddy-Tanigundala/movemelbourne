"""GTFS time handling: service days, >24:00 times and Melbourne daylight saving.

GTFS ``stop_times`` values are *not* clock times. They are elapsed time since a reference point
on the service day, and may exceed 24:00:00 for after-midnight trips. The GTFS reference rule is
"noon minus 12 hours" in the agency timezone: on a normal day that is midnight, but on the two DST
change days it is 23:00 or 01:00 local, which keeps every scheduled instant correct.

Realtime timestamps are POSIX epoch seconds (UTC). We keep raw epochs everywhere and only
convert to local time for display and for bucketing (hour, time band, day of week).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MELBOURNE = ZoneInfo("Australia/Melbourne")
_TWELVE_HOURS = 12 * 3600


def parse_gtfs_time(value: str | None) -> int | None:
    """Parse ``HH:MM:SS`` (hours may exceed 23, may be space-padded) into seconds.

    >>> parse_gtfs_time("25:12:00")
    90720
    """
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    if not (0 <= minutes < 60 and 0 <= seconds < 60) or hours < 0:
        raise ValueError(f"Invalid GTFS time: {value!r}")
    return hours * 3600 + minutes * 60 + seconds


def parse_service_date(value: str | date) -> date:
    """Parse a GTFS ``YYYYMMDD`` service date (``TripDescriptor.start_date``, calendar dates)."""
    if isinstance(value, date):
        return value
    return datetime.strptime(value.strip(), "%Y%m%d").date()


def service_day_reference_epoch(service_date: str | date, tz: ZoneInfo = MELBOURNE) -> int:
    """Epoch seconds of the GTFS reference point ("noon minus 12h") for a service date."""
    d = parse_service_date(service_date)
    noon = datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=tz)
    return int(noon.timestamp()) - _TWELVE_HOURS


def scheduled_epoch(service_date: str | date, gtfs_time: str | int | None) -> int | None:
    """Scheduled instant (epoch seconds) of a ``stop_times`` value on a given service date."""
    secs = (
        gtfs_time if isinstance(gtfs_time, int) or gtfs_time is None else parse_gtfs_time(gtfs_time)
    )
    if secs is None:
        return None
    return service_day_reference_epoch(service_date) + secs


def epoch_to_local(epoch: int | float) -> datetime:
    """Convert POSIX epoch seconds to an aware Melbourne datetime."""
    return datetime.fromtimestamp(epoch, tz=MELBOURNE)


def local_date(epoch: int | float) -> date:
    """Melbourne calendar date of an epoch."""
    return epoch_to_local(epoch).date()


def candidate_service_dates(epoch: int | float) -> tuple[date, date]:
    """Service dates a realtime event could belong to when ``start_date`` is missing.

    An event at 00:40 local may belong to the previous service day's after-midnight trip, so the
    matcher tries the local date and the day before and keeps the closer scheduled time.
    """
    today = local_date(epoch)
    return today, today - timedelta(days=1)


def service_date_range(start: date, end: date) -> list[date]:
    """Inclusive list of dates from ``start`` to ``end``."""
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]
