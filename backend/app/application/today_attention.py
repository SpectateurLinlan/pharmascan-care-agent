"""Current local-day attention read; creates no occurrences, reports or reminders."""

from datetime import timedelta
from uuid import UUID

from ..contracts.ports import Clock
from ..contracts.temporal import local_day_window
from ..contracts.today_attention import TodayAttention, TodayPlan
from ..domain.dose_attention import attention_deadline
from .dosing import DoseScheduleService, SelfReportService
from .enrollment import MedicationEnrollmentService


def read_today_attention(
    *,
    owner: UUID,
    enrollment: MedicationEnrollmentService,
    schedule: DoseScheduleService,
    reports: SelfReportService,
    clock: Clock,
) -> TodayAttention:
    now = clock.now()
    timezone = schedule.local_timezone(owner)
    from zoneinfo import ZoneInfo

    day = now.astimezone(ZoneInfo(timezone)).date()
    start, end = local_day_window(day, timezone)
    plans = []
    context = enrollment.read_context(owner, include_sources=False, active_only=True)
    for medication in context.medications:
        plan = next(iter(context.by_medication[medication.id]), None)
        if not plan or medication.archived_at or (plan.effective_from and plan.effective_from > now):
            continue
        if (
            (plan.effective_to and plan.effective_to <= now)
            or (plan.course_start_date and plan.course_start_date > day + timedelta(days=1))
            or (plan.course_end_date and plan.course_end_date < day)
        ):
            continue
        if plan.is_prn:
            plans.append(TodayPlan(regimen_id=plan.id, state="as_needed", unrecorded_times=[]))
            continue
        frequency = plan.frequency_rule or {}
        if (
            frequency.get("kind") not in {"daily", "weekly", "interval"}
            or not frequency.get("local_times")
            or (frequency.get("kind") == "interval" and not frequency.get("interval_anchor"))
        ):
            # Do not treat a legacy/default anchor as a verified interval plan.
            plans.append(TodayPlan(regimen_id=plan.id, state="unavailable", unrecorded_times=[]))
            continue
        moments, future_moments = schedule.planned_windows_for_plan(
            patient_id=owner, regimen=plan,
            windows=[(start, end), (now, now + timedelta(days=2))],
        )
        history = reports.history_for_plan(
            patient_id=owner, regimen=plan, medication=medication, window_start=start, window_end=min(end, now)
        )
        future = next(
            (
                moment
                for moment in future_moments
                if moment > now
            ),
            None,
        )
        recorded = {row.occurrence.due_at for row in history if row.event is not None and row.occurrence is not None}
        pending, unrecorded = [], []
        for index, moment in enumerate(moments):
            if moment > now or moment in recorded:
                continue
            following = moments[index + 1] if index + 1 < len(moments) else None
            (pending if now < attention_deadline(moment, following, end) else unrecorded).append(moment)
        state = (
            "pending"
            if pending
            else "upcoming"
            if any(moment > now for moment in moments)
            else "unrecorded"
            if unrecorded
            else "recorded"
            if recorded
            else "upcoming"
            if future is not None
            else "not_scheduled"
        )
        plans.append(TodayPlan(regimen_id=plan.id, state=state, unrecorded_times=unrecorded, next_due_at=future))
    return TodayAttention(as_of=now, local_date=day.isoformat(), timezone=timezone, plans=plans)
