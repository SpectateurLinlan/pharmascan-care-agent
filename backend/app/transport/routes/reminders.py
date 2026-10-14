"""Authenticated reminder preferences; app active/reopen delivery only."""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ...application.reminder_alerts import DoseReminderAlert
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
