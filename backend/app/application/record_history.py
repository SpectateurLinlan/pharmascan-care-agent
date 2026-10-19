"""Read-only, bounded two-stream history. No schedule materialisation or dose writes."""

import base64
import hashlib
import json
import unicodedata
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import ValidationError as SchemaError

from ..contracts.dto import FrequencyRuleDTO
from ..contracts.ports import Clock
from ..contracts.record_history import (
    HistoryAnchor,
    HistoryCatalogue,
    HistoryCursor,
    HistoryMedication,
    HistoryPlan,
    MedicationHistoryEntry,
    MedicationHistoryPage,
    RecordHistoryReader,
)
from ..domain.errors import NotFoundError, ProviderUnavailableError, ValidationError
from .enrollment import MedicationEnrollmentService
from .preferences import PreferenceService

HistoryRange = Literal["7", "30", "90", "custom", "all", "plan"]
CONFIRMED_HISTORY_STATES = frozenset({"active", "ended", "superseded"})


class RecordHistoryService:
    def __init__(
        self,
        reader: RecordHistoryReader,
        enrollment: MedicationEnrollmentService,
        preferences: PreferenceService,
        clock: Clock,
    ):
        self._reader, self._enrollment, self._preferences, self._clock = reader, enrollment, preferences, clock

    def catalogue(self, owner: UUID) -> HistoryCatalogue:
        plans = [row for row in self._reader.plans(owner) if row.state in CONFIRMED_HISTORY_STATES]
        medication_ids = {row.patient_medication_id for row in plans}
        medications = [row for row in self._reader.medications(owner) if row.id in medication_ids]
        owned = {row.id for row in medications}
        if any(row.patient_medication_id not in owned for row in plans):
            raise ProviderUnavailableError("Record relationships could not be verified.")
        sources = {}
        result = []
        for row in plans:
            try:
                frequency = FrequencyRuleDTO.model_validate(row.frequency_rule) if row.frequency_rule else None
            except SchemaError as error:
                raise ProviderUnavailableError("The recorded plan frequency could not be read.") from error
            if row.source_id and row.source_id not in sources:
                sources[row.source_id] = self._enrollment.get_source(owner, row.source_id)
            source = sources.get(row.source_id)
            strength = (
                source.dose_basis.strength_text
                if (
                    source
                    and source.dose_basis
                    and str(source.review_status) in ("user_reviewed", "professional_verified")
                )
                else None
            )
            result.append(
                HistoryPlan(
                    id=row.id,
                    medication_id=row.patient_medication_id,
                    supersedes_id=row.supersedes_id,
                    patient_edited=row.patient_edited,
                    effective_from=row.effective_from,
                    effective_to=row.effective_to,
                    state=str(row.state),
                    dose_amount=row.dose_amount,
                    dose_unit=row.dose_unit,
                    strength_text=strength,
                    dosage_form=source.dose_basis.form if source and source.dose_basis and strength else None,
                    frequency=frequency,
                    is_prn=row.is_prn,
                )
            )
        return HistoryCatalogue(
            medications=[
                HistoryMedication(
                    id=row.id,
                    display_name=row.display_name,
                    product_id=row.product_id,
                    identity_status=str(row.identity_status),
                )
                for row in medications
            ],
            plans=sorted(
                result, key=lambda row: (row.effective_from or datetime.min.replace(tzinfo=UTC), row.id), reverse=True
            ),
        )

    def page(
        self,
        owner: UUID,
        *,
        medication_id: UUID | None = None,
        medication_name: str | None = None,
        regimen_id: UUID | None = None,
        range_kind: HistoryRange = "30",
        start: date | None = None,
        end: date | None = None,
        cursor: str | None = None,
        limit: int = 5,
    ) -> MedicationHistoryPage:
        if not 1 <= limit <= 50:
            raise ValidationError("Choose a valid history page size.")
        query_key = hashlib.sha256(
            json.dumps(
                [str(owner), str(medication_id), medication_name, str(regimen_id), range_kind, str(start), str(end)]
            ).encode()
        ).hexdigest()
        state = None
        if cursor:
            try:
                state = HistoryCursor.model_validate_json(base64.urlsafe_b64decode(cursor.encode()))
            except (ValueError, SchemaError) as error:
                raise ValidationError("Invalid history cursor.") from error
            if state.query_key != query_key or state.as_of > self._clock.now():
                raise ValidationError("History filters changed. Restart the query.")
        as_of = state.as_of if state else self._clock.now()
        zone = ZoneInfo(self._preferences.get(owner).timezone)
        local_today = as_of.astimezone(zone).date()
        plans = {row.id: row for row in self._reader.plans(owner) if row.state in CONFIRMED_HISTORY_STATES}
        medication_ids = {row.patient_medication_id for row in plans.values()}
        meds = {row.id: row for row in self._reader.medications(owner) if row.id in medication_ids}
        if medication_id and medication_id not in meds:
            raise NotFoundError("Medicine not found for this patient")
        plan = plans.get(regimen_id) if regimen_id else None
        if regimen_id and plan is None:
            raise NotFoundError("Plan not found for this patient")
        if plan and medication_id and plan.patient_medication_id != medication_id:
            raise ValidationError("The plan does not belong to the selected medicine.")
        grouped_ids = None
        if medication_name is not None:
            name = " ".join(unicodedata.normalize("NFKC", medication_name).lower().split())
            grouped_ids = {
                row.id
                for row in meds.values()
                if " ".join(unicodedata.normalize("NFKC", row.display_name).lower().split()) == name
            }
            if not name or not grouped_ids:
                raise NotFoundError("Medicine name not found for this patient")
            if medication_id and medication_id not in grouped_ids:
                raise ValidationError("Medicine filters do not match.")
            if plan and plan.patient_medication_id not in grouped_ids:
                raise ValidationError("The plan does not belong to the selected medicine name.")
        plan_ids = (
            [regimen_id]
            if regimen_id
            else (
                [row.id for row in plans.values() if row.patient_medication_id == medication_id]
                if medication_id
                else [row.id for row in plans.values() if row.patient_medication_id in grouped_ids]
                if grouped_ids is not None
                else list(plans)
            )
        )
        if plan_ids and len(plan_ids) > 100:
            raise ValidationError("Too many medication plans. Choose one plan.")
        lower = None
        upper = as_of + timedelta(microseconds=1)
        missing_start = False
        if range_kind in ("7", "30", "90"):
            lower = datetime.combine(local_today - timedelta(days=int(range_kind) - 1), time(), zone).astimezone(UTC)
        elif range_kind == "custom":
            if start is None or end is None or end < start or end == date.max:
                raise ValidationError("Choose a valid start and end date.")
            lower = datetime.combine(start, time(), zone).astimezone(UTC)
            upper = min(upper, datetime.combine(end + timedelta(days=1), time(), zone).astimezone(UTC))
            if lower > as_of:
                raise ValidationError("History cannot start in the future.")
        elif range_kind == "plan":
            if plan is None:
                raise ValidationError("Choose a medication plan first.")
            lower = plan.effective_from
            missing_start = lower is None
            if plan.effective_to:
                upper = min(upper, plan.effective_to)
        if lower and lower >= upper:
            return MedicationHistoryPage(
                entries=[],
                next_cursor=None,
                window_start=lower,
                window_end=upper,
                as_of=as_of,
                missing_plan_start=missing_start,
            )
        scheduled = self._reader.scheduled(
            owner, plan_ids, lower, upper, as_of, state.scheduled if state else None, limit + 1
        )
        unscheduled = self._reader.unscheduled(
            owner, plan_ids, lower, upper, as_of, state.unscheduled if state else None, limit + 1
        )
        reports = self._reader.reports(owner, [row.id for row in scheduled], as_of)
        by_occurrence = {row.occurrence_id: row for row in reports}
        if len(by_occurrence) != len(reports):
            raise ProviderUnavailableError("Record relationships could not be verified.")
        rows = []
        for occurrence, event in [(row, by_occurrence.get(row.id)) for row in scheduled] + [
            (None, row) for row in unscheduled
        ]:
            identity = occurrence.regimen_id if occurrence else event.regimen_id
            related = plans.get(identity)
            medication = meds.get(related.patient_medication_id) if related else None
            if not related or not medication or (event and event.regimen_id != identity):
                raise ProviderUnavailableError("Record relationships could not be verified.")
            kind = "scheduled" if occurrence else "unscheduled"
            sort_time = occurrence.due_at if occurrence else event.event_time
            rows.append(
                MedicationHistoryEntry(
                    id=f"{kind}:{occurrence.id if occurrence else event.id}",
                    medication_id=medication.id,
                    regimen_id=identity,
                    display_name=medication.display_name,
                    sort_time=sort_time,
                    due_at=occurrence.due_at if occurrence else None,
                    event_id=event.id if event else None,
                    event_time=event.event_time if event else None,
                    submitted_at=event.created_at if event else None,
                    reported_late=event.reported_late if event else False,
                    actual_administration_at=event.actual_administration_at if event else None,
                    intake_status=str(event.intake_status) if event else None,
                    reported=event is not None,
                    kind=kind,
                )
            )
        # Stable two-stream key. Each cursor advances only the emitted rows of its stream.
        rows.sort(key=lambda row: (row.sort_time, row.kind, row.id), reverse=True)
        page = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            anchors = {
                "scheduled": state.scheduled if state else None,
                "unscheduled": state.unscheduled if state else None,
            }
            for row in page:
                anchors[row.kind] = HistoryAnchor(time=row.sort_time, id=UUID(row.id.split(":")[1]))
            value = HistoryCursor(query_key=query_key, as_of=as_of, **anchors)
            next_cursor = base64.urlsafe_b64encode(value.model_dump_json().encode()).decode()
        return MedicationHistoryPage(
            entries=page,
            next_cursor=next_cursor,
            window_start=lower,
            window_end=upper,
            as_of=as_of,
            missing_plan_start=missing_start,
        )
