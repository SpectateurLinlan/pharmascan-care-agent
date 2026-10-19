"""Patient-owned read-only history; never creates occurrences or reports."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from .dto import DoseEventDTO, DoseOccurrenceDTO, FrequencyRuleDTO, PatientMedicationDTO, RegimenVersionDTO


class ReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HistoryMedication(ReadModel):
    id: UUID
    display_name: str
    product_id: UUID | None
    identity_status: str


class HistoryPlan(ReadModel):
    id: UUID
    medication_id: UUID
    supersedes_id: UUID | None
    effective_from: datetime | None
    effective_to: datetime | None
    state: str
    dose_amount: float | None
    dose_unit: str | None
    patient_edited: bool = False
    strength_text: str | None = None
    dosage_form: str | None = None
    frequency: FrequencyRuleDTO | None = None
    is_prn: bool = False


class HistoryCatalogue(ReadModel):
    medications: list[HistoryMedication]
    plans: list[HistoryPlan]


class HistoryAnchor(ReadModel):
    time: AwareDatetime
    id: UUID


class HistoryCursor(ReadModel):
    query_key: str
    as_of: AwareDatetime
    scheduled: HistoryAnchor | None = None
    unscheduled: HistoryAnchor | None = None


class MedicationHistoryEntry(ReadModel):
    id: str
    medication_id: UUID
    regimen_id: UUID
    display_name: str
    sort_time: datetime
    due_at: datetime | None
    event_id: UUID | None
    event_time: datetime | None
    submitted_at: datetime | None
    reported_late: bool = False
    actual_administration_at: datetime | None = None
    intake_status: str | None
    reported: bool
    kind: Literal["scheduled", "unscheduled"]


class MedicationHistoryPage(ReadModel):
    entries: list[MedicationHistoryEntry]
    next_cursor: str | None
    window_start: datetime | None
    window_end: datetime
    as_of: datetime
    scope: Literal["stored_records_only"] = "stored_records_only"
    missing_plan_start: bool = False


class RecordHistoryReader(Protocol):
    def medications(self, owner: UUID) -> list[PatientMedicationDTO]: ...
    def plans(self, owner: UUID) -> list[RegimenVersionDTO]: ...
    def scheduled(
        self,
        owner: UUID,
        plans: list[UUID] | None,
        start: datetime | None,
        end: datetime,
        as_of: datetime,
        before: HistoryAnchor | None,
        limit: int,
    ) -> list[DoseOccurrenceDTO]: ...
    def unscheduled(
        self,
        owner: UUID,
        plans: list[UUID] | None,
        start: datetime | None,
        end: datetime,
        as_of: datetime,
        before: HistoryAnchor | None,
        limit: int,
    ) -> list[DoseEventDTO]: ...
    def reports(self, owner: UUID, occurrences: list[UUID], as_of: datetime) -> list[DoseEventDTO]: ...
