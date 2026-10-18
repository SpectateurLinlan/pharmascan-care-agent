"""Display attention window only; never an intake or catch-up dosing decision."""

from datetime import datetime, timedelta


def attention_deadline(due: datetime, next_due: datetime | None, day_end: datetime) -> datetime:
    return min(due + timedelta(hours=2), next_due or day_end, day_end)
