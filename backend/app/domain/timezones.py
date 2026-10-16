"""The one fixed IST offset (UTC+5:30). India has no DST; a fixed offset needs no tzdata dependency."""

from datetime import timedelta, timezone

IST_OFFSET = timedelta(hours=5, minutes=30)
IST = timezone(IST_OFFSET)
