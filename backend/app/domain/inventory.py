"""Pure stock rules; no strength conversion and no inferred consumption."""

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from ..contracts.dto import RegimenVersionDTO
from ..contracts.long_term import StockInput
from .errors import ValidationError


def ledger_balance(previous: float | None, unit: str | None, values: StockInput) -> float:
    if unit is not None and unit != values.unit:
        raise ValidationError("Stock unit differs from this medication's existing ledger")
    if values.kind == "count":
        return values.quantity
    if previous is None:
        raise ValidationError("Confirm a physical stock count before recording changes")
    delta = -values.quantity if values.kind in ("lost", "discarded", "damaged") else values.quantity
    result = previous + delta
    if result < 0:
        raise ValidationError("Adjustment exceeds recorded stock; please count your stock again")
    return result


def count_unit(value: str | None) -> str | None:
    return {"tablet": "tablet", "tablets": "tablet", "capsule": "capsule", "capsules": "capsule"}.get(
        (value or "").lower().strip()
    )


def scheduled_daily_requirement(
    regimens: list[RegimenVersionDTO],
    unit: str,
    now: datetime,
    timezone: str,
    rule_timezones: dict[UUID, str] | None = None,
) -> float | None:
    """Average scheduled count demand, never a prescription or run-out date."""
    active = []
    for row in regimens:
        today = now.astimezone(ZoneInfo((rule_timezones or {}).get(row.id, timezone))).date()
        if (
            row.state.value == "active"
            and (row.course_start_date is None or row.course_start_date <= today)
            and (row.course_end_date is None or row.course_end_date >= today)
            and (row.effective_to is None or row.effective_to > now)
        ):
            active.append(row)
    if len(active) != 1:
        return None
    row = active[0]
    rule = row.frequency_rule or {}
    times = rule.get("local_times", [])
    if row.is_prn or not row.dose_amount or count_unit(row.dose_unit) != unit or not times:
        return None
    if rule.get("kind") == "daily":
        return row.dose_amount * len(times)
    if rule.get("kind") == "weekly" and rule.get("days_of_week"):
        return row.dose_amount * len(times) * len(set(rule["days_of_week"])) / 7
    return None
