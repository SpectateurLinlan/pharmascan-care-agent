"""Dose schedule generation, due-dose lookup and self-report recording.

Critical invariants (AGENTS.md rules 10, 22-23):
- a self report NEVER proves ingestion (`ingestion_proven` stays false);
- visual_status stays `not_checked` in the P0 slice (no photo path);
- `not_reported` is distinct from "missed" — absence of a report is not a miss;
- repeated writes are idempotent through the idempotency key;
- patient ownership is enforced by scoping every repository call by patient_id.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from ..contracts.dto import (
    DoseEventDTO,
    DoseEventInput,
    DoseHistoryEntryDTO,
    DoseOccurrenceDTO,
    DoseRuleDTO,
    DueDoseResultDTO,
    PatientMedicationDTO,
    RegimenVersionDTO,
    SelfReportResultDTO,
)
from ..contracts.enums import IntakeStatus, OccurrenceStatus, RegimenState, RuleKind, VisualStatus
from ..contracts.ports import (
    Clock,
    DoseEventRepository,
    DoseOccurrenceRepository,
    DoseRuleRepository,
    IdGenerator,
    PatientMedicationRepository,
    RegimenVersionRepository,
)
from ..domain import policy
from ..domain.errors import NotFoundError, ValidationError
from .timezone import LOCAL_TZ_PROVIDER, LocalTzProvider, to_utc


class DoseScheduleService:
    """Materialise dose occurrences deterministically from a regimen rule."""

    def __init__(
        self,
        *,
        regimens: RegimenVersionRepository,
        rules: DoseRuleRepository,
        occurrences: DoseOccurrenceRepository,
        clock: Clock,
        ids: IdGenerator,
        tz_provider: LocalTzProvider | None = None,
    ) -> None:
        self._regimens = regimens
        self._rules = rules
        self._occurrences = occurrences
        self._clock = clock
        self._ids = ids
        self._tz = tz_provider or LOCAL_TZ_PROVIDER

    def add_rule(
        self, *, patient_id: UUID, regimen_id: UUID, rule: DoseRuleDTO
    ) -> DoseRuleDTO:
        regimen = self._require_regimen(patient_id, regimen_id)
        if regimen.state != RegimenState.ACTIVE:
            raise ValidationError("Dose rules can only be added to an active regimen")
        if (rule.rule_kind == RuleKind.PRN) != regimen.is_prn:
            raise ValidationError(
                "rule kind must match the regimen: PRN regimen takes a PRN rule"
            )
        self._rules.add(rule)
        return rule

    def materialize(
        self, *, patient_id: UUID, regimen_id: UUID, days: int = 7
    ) -> list[DoseOccurrenceDTO]:
        """Generate occurrences for the next `days` local days.

        PRN regimens generate NO scheduled occurrence — a PRN dose only exists
        when the patient reports taking it (no inferred occurrence).
        """
        regimen = self._require_regimen(patient_id, regimen_id)
        if regimen.state != RegimenState.ACTIVE:
            raise ValidationError("Occurrences are generated only for an active regimen")
        if regimen.is_prn:
            return []

        tz = self._tz.local_tz(patient_id)
        now = self._clock.now()
        horizon_end = now + timedelta(days=days)
        generated: list[DoseOccurrenceDTO] = []

        for rule in self._rules.list_for_regimen(patient_id, regimen_id):
            if rule.rule_kind != RuleKind.SCHEDULED or not rule.enabled:
                continue
            for due_at in self._expand(rule, now, horizon_end, tz):
                if due_at < (regimen.effective_from or now):
                    continue
                key = f"{regimen_id}:{rule.id}:{due_at.astimezone(UTC).isoformat()}"
                existing = self._occurrences.find_by_generation_key(patient_id, key)
                if existing is not None:
                    generated.append(existing)
                    continue
                occurrence = DoseOccurrenceDTO(
                    id=self._ids.new_id(),
                    patient_id=patient_id,
                    regimen_id=regimen_id,
                    rule_id=rule.id,
                    due_at=due_at,
                    status=OccurrenceStatus.SCHEDULED,
                    generation_key=key,
                )
                self._occurrences.add(occurrence)
                generated.append(occurrence)
        return sorted(generated, key=lambda o: o.due_at)

    @staticmethod
    def _expand(
        rule: DoseRuleDTO, start: datetime, end: datetime, tz: ZoneInfo
    ) -> list[datetime]:
        """Expand a rule into absolute UTC instants within [start, end).

        Supports the same three kinds the SQL CHECK allows: daily / weekly /
        interval. DST is handled by constructing local wall-clock times in the
        patient timezone and converting to UTC.
        """
        moments: list[datetime] = []
        start_local = start.astimezone(tz)
        end_local = end.astimezone(tz)

        def _at(local_day, hh: int, mm: int) -> datetime:
            return datetime(
                local_day.year, local_day.month, local_day.day, hh, mm, tzinfo=tz
            ).astimezone(UTC)

        if rule.rule_kind == RuleKind.SCHEDULED:
            times = [tuple(int(p) for p in t.split(":")) for t in rule.local_times]
            day = start_local.date()
            while day <= end_local.date():
                if rule.days_of_week and day.isoweekday() not in rule.days_of_week:
                    day = day + timedelta(days=1)
                    continue
                for hh, mm in times:
                    moment = _at(day, hh, mm)
                    if start <= moment < end:
                        moments.append(moment)
                day = day + timedelta(days=1)
        return sorted(moments)

    def find_due(
        self, *, patient_id: UUID, regimen_id: UUID, at: datetime | None = None
    ) -> DueDoseResultDTO:
        """Return the earliest un-reported occurrence up to `at`, if any."""
        regimen = self._require_regimen(patient_id, regimen_id)
        moment = at or self._clock.now()
        if regimen.is_prn:
            return DueDoseResultDTO(
                occurrence=None,
                medication_display_name="",
                is_prn=True,
            )
        window = self._occurrences.list_for_regimen(
            patient_id, regimen_id, moment - timedelta(days=1), moment + timedelta(seconds=1)
        )
        for occurrence in window:
            if occurrence.status == OccurrenceStatus.CLOSED:
                continue
            return DueDoseResultDTO(
                occurrence=occurrence,
                medication_display_name="",
                is_prn=False,
            )
        return DueDoseResultDTO(occurrence=None, medication_display_name="", is_prn=False)

    def _require_regimen(self, patient_id: UUID, regimen_id: UUID) -> RegimenVersionDTO:
        regimen = self._regimens.get(patient_id, regimen_id)
        if regimen is None:
            raise NotFoundError(f"Regimen {regimen_id} not found for this patient")
        return regimen


class SelfReportService:
    """Record the patient's own report of taking / not taking a dose."""

    def __init__(
        self,
        *,
        regimens: RegimenVersionRepository,
        medications: PatientMedicationRepository,
        occurrences: DoseOccurrenceRepository,
        events: DoseEventRepository,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._regimens = regimens
        self._medications = medications
        self._occurrences = occurrences
        self._events = events
        self._clock = clock
        self._ids = ids

    def report(self, *, patient_id: UUID, payload: DoseEventInput) -> SelfReportResultDTO:
        """Idempotent self report.

        Replaying the same idempotency key returns the existing event instead
        of creating a second one (repeat writes must be idempotent).
        """
        regimen = self._regimens.get(patient_id, payload.regimen_id)
        if regimen is None:
            raise NotFoundError(f"Regimen {payload.regimen_id} not found for this patient")

        existing = self._events.find_by_idempotency_key(patient_id, payload.idempotency_key)
        if existing is not None:
            return SelfReportResultDTO(
                event=None, existing_event_id=existing.id, already_recorded=True
            )

        medication = self._medications.get(patient_id, regimen.patient_medication_id)
        occurrence = (
            self._occurrences.get(patient_id, payload.occurrence_id)
            if payload.occurrence_id is not None
            else None
        )
        occurrence_has_event = (
            occurrence is not None
            and self._events.find_by_occurrence(patient_id, occurrence.id) is not None
        )
        event_time = to_utc(payload.event_time)

        policy.check_dose_write_preconditions(
            regimen=regimen,
            medication=medication,
            occurrence=occurrence,
            occurrence_has_event=occurrence_has_event,
            intake_status=payload.intake_status,
            event_time=event_time,
        )
        policy.self_report_is_not_ingestion(payload.intake_status, VisualStatus.NOT_CHECKED)

        event = DoseEventDTO(
            id=self._ids.new_id(),
            patient_id=patient_id,
            regimen_id=regimen.id,
            occurrence_id=occurrence.id if occurrence is not None else None,
            event_time=event_time,
            intake_status=payload.intake_status,
            visual_status=VisualStatus.NOT_CHECKED,
            ingestion_proven=False,
            idempotency_key=payload.idempotency_key,
            created_at=self._clock.now(),
        )
        self._events.add(event)

        if occurrence is not None:
            self._occurrences.update(
                occurrence.model_copy(update={"status": OccurrenceStatus.CLOSED})
            )
        return SelfReportResultDTO(event=event, already_recorded=False)

    def history(
        self,
        *,
        patient_id: UUID,
        regimen_id: UUID,
        window_start: datetime,
        window_end: datetime,
    ) -> list[DoseHistoryEntryDTO]:
        """State-aware history: not_reported is NOT missed."""
        regimen = self._regimens.get(patient_id, regimen_id)
        if regimen is None:
            raise NotFoundError(f"Regimen {regimen_id} not found for this patient")
        medication = self._medications.get(patient_id, regimen.patient_medication_id)
        name = medication.display_name if medication else ""

        events = {
            e.occurrence_id: e
            for e in self._events.list_for_patient(patient_id, window_start, window_end)
            if e.occurrence_id is not None
        }
        occurrences = self._occurrences.list_for_regimen(
            patient_id, regimen_id, window_start, window_end
        )

        entries: list[DoseHistoryEntryDTO] = []
        for occurrence in occurrences:
            entries.append(
                DoseHistoryEntryDTO(
                    event=events.get(occurrence.id),
                    occurrence=occurrence,
                    regimen_id=regimen_id,
                    medication_display_name=name,
                )
            )
        return entries


def patient_local_now(clock: Clock, tz: ZoneInfo | None = None) -> datetime:
    """Local wall-clock now for display only; storage always uses UTC."""
    zone = tz or ZoneInfo("Asia/Singapore")
    return clock.now().astimezone(zone)
