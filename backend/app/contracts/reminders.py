"""Reminder preferences are separate from clinical schedules and intake."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ReminderDTO(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    patient_id: UUID
    occurrence_id: UUID
    remind_at: datetime
    demo_only: bool = True


class ReminderRepository(Protocol):
    def save(self, reminder: ReminderDTO) -> ReminderDTO: ...
    def list_for_patient(self, patient_id: UUID) -> list[ReminderDTO]: ...


class ReminderStatusDTO(ReminderDTO):
    is_due: bool
