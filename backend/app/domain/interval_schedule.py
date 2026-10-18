"""Elapsed-hour schedules use a reviewed local calendar anchor, never a read-time guess."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from .errors import ValidationError


def interval_moments(frequency: dict, start: datetime, end: datetime, timezone: str) -> list[datetime]:
    anchor = frequency.get("interval_anchor")
    hours = frequency.get("every_hours")
    if not anchor or not isinstance(hours, int) or not 1 <= hours <= 720:
        raise ValidationError("Review the interval and first-dose date/time before scheduling")
    day = date.fromisoformat(anchor["local_date"])
    hour, minute = map(int, anchor["local_time"].split(":"))
    zone = ZoneInfo(timezone)
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
    first = local.astimezone(UTC)
    if first.astimezone(zone).replace(tzinfo=None) != local.replace(tzinfo=None):
        raise ValidationError("The first-dose time does not exist in the patient timezone")
    if local.replace(fold=0).utcoffset() != local.replace(fold=1).utcoffset():
        raise ValidationError("The first-dose time is ambiguous in the patient timezone; choose another time")
    step = timedelta(hours=hours)
    count = max(0, (start - first) // step)
    moment = first + count * step
    if moment < start:
        moment += step
    moments = []
    while moment < end:
        moments.append(moment)
        moment += step
    return moments
