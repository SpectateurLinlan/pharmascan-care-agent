"""Read-only calendar projection contract. Source records remain authoritative.

No persistence, calendar write API, scheduling or AI-created event is introduced.
Date-only course bounds are intentionally not coerced to UTC timestamps.
"""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, computed_field, model_validator


class CareCalendarEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_type: Literal["dose_occurrence", "care_task", "regimen_version"]
    source_id: UUID
    kind: Literal["planned_dose", "care_task", "course_start", "course_end", "effective_start", "effective_end"]
    title: str
    timezone: str
    at: AwareDatetime | None = None
    on_date: date | None = None
    medication_id: UUID | None = None
    regimen_id: UUID | None = None
    report_status: Literal["reported_taken", "reported_not_taken", "unsure", "unrecorded", "future"] | None = None
    task_status: Literal["pending", "overdue", "completed", "cancelled"] | None = None

    @computed_field
    @property
    def event_id(self) -> str:
        return f"{self.source_type}:{self.source_id}:{self.kind}"

    @model_validator(mode="after")
    def consistent_source(self):
        if (self.at is None) == (self.on_date is None):
            raise ValueError("Use exactly one instant or calendar date")
        allowed = {
            "dose_occurrence": {"planned_dose"},
            "care_task": {"care_task"},
            "regimen_version": {"course_start", "course_end", "effective_start", "effective_end"},
        }
        if self.kind not in allowed[self.source_type]:
            raise ValueError("Calendar kind must retain its source entity type")
        if self.kind in {"course_start", "course_end"} and self.on_date is None:
            raise ValueError("Course bounds retain calendar-date semantics")
        if self.kind not in {"course_start", "course_end"} and self.at is None:
            raise ValueError("Dose, task and effective-version events require an instant")
        return self
