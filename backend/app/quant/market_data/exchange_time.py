"""Exchange-local calendar dates from an instant and a fixed UTC offset. Pure; no clock, no timezone database."""

from datetime import date, datetime, timedelta, timezone


def local_date(instant: datetime, offset: timedelta) -> date:
    """The calendar date at `instant` in a zone `offset` ahead of UTC (negative = behind)."""
    if not isinstance(offset, timedelta):
        raise TypeError("offset must be a timedelta")
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("instant must be timezone-aware")
    return (instant.astimezone(timezone.utc) + offset).date()
