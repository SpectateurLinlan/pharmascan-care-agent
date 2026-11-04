"""Closed record queries: collection data never carries patient/write authority."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .assistant_workflows import WorkflowDTO


class RecordPageFields(WorkflowDTO):
    page: int = Field(default=0, strict=True, ge=0, le=100000)


class TodayRecordFields(RecordPageFields):
    medication_id: UUID | None = None


class StatusRecordFields(TodayRecordFields):
    day: date | None = None
    cursor: str | None = Field(default=None, min_length=1, max_length=4096)


class SourceRecordFields(TodayRecordFields):
    regimen_id: UUID | None = None


class HistoryRecordFields(WorkflowDTO):
    medication_id: UUID | None = None
    regimen_id: UUID | None = None
    range_kind: Literal["7", "30", "90", "custom", "all", "plan"] = "30"
    start: date | None = None
    end: date | None = None
    cursor: str | None = Field(default=None, min_length=1, max_length=4096)
    limit: int = Field(default=5, strict=True, ge=1, le=50)

    @model_validator(mode="after")
    def paired_range(self):
        if self.range_kind == "custom":
            if self.start is None or self.end is None or self.end < self.start or self.end == date.max:
                raise ValueError("Choose a valid paired start and end date")
        elif self.start is not None or self.end is not None:
            raise ValueError("Dates require the custom range")
        if self.range_kind == "plan" and self.regimen_id is None:
            raise ValueError("Choose the plan for a course history range")
        return self


class SummaryRecordFields(RecordPageFields):
    period: Literal["week", "month", "course"] = "week"
    regimen_id: UUID | None = None


RECORD_READ_SCHEMAS = {
    "medication.today": TodayRecordFields,
    "medication.due": TodayRecordFields,
    "medication.status": StatusRecordFields,
    "medication.history": HistoryRecordFields,
    "medication.source.view": SourceRecordFields,
    "medication.instructions": TodayRecordFields,
    "record.catalogue": RecordPageFields,
    "record.history": HistoryRecordFields,
    "record.summary": SummaryRecordFields,
    "record.visit.prepare": SummaryRecordFields,
}
