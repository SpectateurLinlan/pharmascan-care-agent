"""Authenticated reminder preferences; app active/reopen delivery only."""

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ...application.calendar_export import calendar_export
from ...application.push_test import PushTestLimited
from ...application.reminder_alerts import DoseReminderAlert
from ...application.reminder_plan import PlannedReminder
from ...contracts.notifications import DeliveryResult
from ...contracts.push import PushConfiguration, PushSubscriptionInput, PushSubscriptionRecord
from ...contracts.reminders import ReminderDTO, ReminderStatusDTO
from ...domain.errors import ProviderUnavailableError
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal

router = APIRouter(prefix="/api/reminders", tags=["reminders"])


@router.get("/alerts", response_model=list[DoseReminderAlert])
def alerts(
    principal: AuthenticatedPrincipal = Depends(get_principal), container: ApplicationContainer = Depends(get_container)
):
    if container.reminder_alerts is None or container.preferences is None:
        raise ProviderUnavailableError("Scheduled reminder alerts unavailable")
    preference = container.preferences.get(principal.patient_id)
    if not preference.reminders_enabled:
        return []
    return container.reminder_alerts.current(
        principal.patient_id, lead_minutes=preference.reminder_lead_minutes, timezone=preference.timezone
    )


class SnoozeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    occurrence_id: UUID
    minutes: int = Field(ge=1, le=1440)


@router.post("", response_model=ReminderDTO)
def snooze(
    payload: SnoozeRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
) -> ReminderDTO:
    if container.reminders is None:
        raise ProviderUnavailableError("Reminder preferences unavailable")
    return container.reminders.snooze(
        patient_id=principal.patient_id, occurrence_id=payload.occurrence_id, minutes=payload.minutes
    )


@router.get("", response_model=list[ReminderStatusDTO])
def current(
    principal: AuthenticatedPrincipal = Depends(get_principal), container: ApplicationContainer = Depends(get_container)
) -> list[ReminderStatusDTO]:
    if container.reminders is None:
        raise ProviderUnavailableError("Reminder preferences unavailable")
    return container.reminders.list_current(principal.patient_id)


@router.get("/plan", response_model=list[PlannedReminder])
def plan(
    principal: AuthenticatedPrincipal = Depends(get_principal), container: ApplicationContainer = Depends(get_container)
):
    if container.reminder_plan is None or container.preferences is None:
        raise ProviderUnavailableError("Reminder plan unavailable")
    preference = container.preferences.get(principal.patient_id)
    if not preference.reminders_enabled:
        return []
    return container.reminder_plan.upcoming(principal.patient_id, lead_minutes=preference.reminder_lead_minutes)


@router.get("/calendar")
def calendar(
    range_name: str | None = Query(default=None, alias="range"),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    include_medications: bool = Query(default=True),
    include_tasks: bool = Query(default=True),
    days: int | None = Query(default=None, ge=1, le=31),
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    from ...domain.errors import ValidationError

    if container.reminder_plan is None or container.preferences is None:
        raise ProviderUnavailableError("Calendar export unavailable")
    if not include_medications and not include_tasks:
        raise ValidationError("Select medication reminders, Care Task reminders, or both.")
    if range_name is not None and days is not None:
        raise ValidationError("Choose one calendar range option.")
    preference = container.preferences.get(principal.patient_id)
    now = container.clock.now()
    zone = ZoneInfo(preference.timezone)
    today = now.astimezone(zone).date()
    selected_range = range_name or ("custom_days" if days is not None else "30")
    full_remaining_course = selected_range == "remaining"
    if selected_range == "30":
        window_start, window_end = today, today + timedelta(days=29)
    elif selected_range == "90":
        window_start, window_end = today, today + timedelta(days=89)
    elif selected_range == "custom_days":
        window_start, window_end = today, today + timedelta(days=(days or 30) - 1)
    elif selected_range == "custom":
        if start_date is None or end_date is None:
            raise ValidationError("Choose a start and end date for the custom range.")
        if end_date < start_date:
            raise ValidationError("The end date must be on or after the start date.")
        if (end_date - start_date).days + 1 > 366:
            raise ValidationError("Custom calendar ranges cannot exceed 366 days.")
        if start_date < today:
            raise ValidationError("Calendar exports can only include today or future dates.")
        window_start, window_end = start_date, end_date
    elif full_remaining_course:
        window_start, window_end = today, None
    else:
        raise ValidationError("Choose a supported calendar range.")

    rows, effective_end = container.reminder_plan.calendar_export_rows(
        principal.patient_id,
        lead_minutes=preference.reminder_lead_minutes,
        start_date=window_start,
        end_date=window_end,
        full_remaining_course=full_remaining_course,
        include_medications=include_medications,
    )
    task_window_start = max(now, datetime.combine(window_start, time.min, tzinfo=zone)).astimezone(UTC)
    task_window_end = datetime.combine(effective_end + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
    tasks = (
        [
            task
            for task in container.long_term.actionable_tasks(principal.patient_id, preference.timezone)
            if task_window_start <= task.due_at < task_window_end
        ]
        if container.long_term and include_tasks
        else []
    )
    if not rows and not tasks:
        raise ValidationError("No upcoming calendar events match the selected options.")
    return Response(
        calendar_export(rows, now=container.clock.now(), lead_minutes=preference.reminder_lead_minutes, tasks=tasks),
        media_type="text/calendar",
        headers={"Content-Disposition": "attachment; filename=pharmascan-reminders.ics", "Cache-Control": "no-store"},
    )


@router.get("/push/config", response_model=PushConfiguration)
def push_config(
    principal: AuthenticatedPrincipal = Depends(get_principal), container: ApplicationContainer = Depends(get_container)
):
    return {
        "available": bool(container.push_public_key),
        "public_key": container.push_public_key,
        "test_available": container.push_test is not None,
    }


@router.post("/push/current", response_model=PushSubscriptionRecord | None)
def current_subscription(
    payload: PushSubscriptionInput,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    if container.push_subscriptions is None:
        raise ProviderUnavailableError("Push subscriptions unavailable")
    return container.push_subscriptions.current(principal.patient_id, payload.endpoint)


class PushTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subscription_id: UUID
    request_id: UUID


@router.post("/push/test", response_model=DeliveryResult)
def test_push(
    payload: PushTestRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    if not principal.authenticated or container.push_test is None or container.push_subscriptions is None:
        raise ProviderUnavailableError("Web Push test unavailable")
    try:
        return container.push_test.send(
            principal.patient_id,
            payload.subscription_id,
            payload.request_id,
            container.push_subscriptions,
            container.preferences.get(principal.patient_id).preferred_language if container.preferences else "en",
        )
    except PushTestLimited:
        return JSONResponse(
            {"code": "RATE_LIMITED", "message": "Wait one minute before another test.", "rule_id": None},
            status_code=429,
            headers={"Retry-After": "60"},
        )


@router.get("/push/subscriptions", response_model=list[PushSubscriptionRecord])
def subscriptions(
    principal: AuthenticatedPrincipal = Depends(get_principal), container: ApplicationContainer = Depends(get_container)
):
    if container.push_subscriptions is None:
        raise ProviderUnavailableError("Push subscriptions unavailable")
    return container.push_subscriptions.list_for_patient(principal.patient_id)


@router.post("/push/subscriptions", response_model=PushSubscriptionRecord)
def subscribe(
    payload: PushSubscriptionInput,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    if container.push_subscriptions is None or not container.push_public_key:
        raise ProviderUnavailableError("Web Push has not been configured")
    return container.push_subscriptions.save(principal.patient_id, payload)


@router.delete("/push/subscriptions/{subscription_id}", status_code=204)
def unsubscribe(
    subscription_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    if container.push_subscriptions is None:
        raise ProviderUnavailableError("Push subscriptions unavailable")
    container.push_subscriptions.revoke(principal.patient_id, subscription_id)
    return Response(status_code=204)


@router.post("/push/unsubscribe", status_code=204)
def unsubscribe_current(
    payload: PushSubscriptionInput,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    if container.push_subscriptions is None:
        raise ProviderUnavailableError("Push subscriptions unavailable")
    container.push_subscriptions.revoke_endpoint(principal.patient_id, payload.endpoint)
    return Response(status_code=204)
