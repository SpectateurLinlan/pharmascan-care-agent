"""Audited late reporting is separate from Agent backfill and never creates doses."""

import hashlib
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from ..contracts.dto import (
    ConfirmationChallengeDTO,
    DoseEventDTO,
    DoseOccurrenceDTO,
    PatientMedicationDTO,
    RegimenVersionDTO,
    SourceDocumentDTO,
)
from ..contracts.enums import IntakeStatus
from ..contracts.late_reports import DoseFollowUp, LateReportChallenge, LateReportRecord, LateReportRepository
from ..contracts.ports import Clock, ConfirmationChallengeRepository, DoseEventRepository, IdGenerator
from ..contracts.temporal import local_day_window
from ..domain.dose_attention import attention_deadline
from ..domain.errors import ConfirmationRequiredError, NotFoundError, ValidationError
from .dosing import DoseScheduleService
from .enrollment import MedicationEnrollmentService


class LateReportService:
    def __init__(
        self,
        *,
        enrollment: MedicationEnrollmentService,
        schedule: DoseScheduleService,
        events: DoseEventRepository,
        repository: LateReportRepository,
        challenges: ConfirmationChallengeRepository,
        clock: Clock,
        ids: IdGenerator,
    ):
        self.enrollment, self.schedule, self.events = enrollment, schedule, events
        self.repository, self.challenges, self.clock, self.ids = repository, challenges, clock, ids

    def occurrence(self, patient_id: UUID, occurrence_id: UUID) -> DoseFollowUp:
        occurrence = self.schedule.get_occurrence(patient_id, occurrence_id)
        if occurrence is None:
            raise NotFoundError("Scheduled occurrence not found for this patient")
        plan = self.enrollment.get_regimen(patient_id, occurrence.regimen_id)
        medicine = self.enrollment.get_medication(patient_id, plan.patient_medication_id) if plan else None
        source = self.enrollment.get_source(patient_id, plan.source_id) if plan and plan.source_id else None
        return self._describe_occurrence(
            occurrence=occurrence,
            plan=plan,
            medicine=medicine,
            source=source,
            now=self.clock.now(),
            zone=ZoneInfo(self.schedule.local_timezone(patient_id)),
            event=self.events.find_by_occurrence(patient_id, occurrence_id),
            entries=self.repository.history(patient_id, occurrence_id),
        )

    @staticmethod
    def _describe_occurrence(
        *,
        occurrence: DoseOccurrenceDTO,
        plan: RegimenVersionDTO | None,
        medicine: PatientMedicationDTO | None,
        source: SourceDocumentDTO | None,
        now: datetime,
        zone: ZoneInfo,
        event: DoseEventDTO | None,
        entries: list[LateReportRecord],
    ) -> DoseFollowUp:
        """Shared eligibility/projection over owned records; no retained cache.

        List reads reuse their already-read version/medicine/event. Confirmation
        still calls occurrence() to read current records independently.
        """
        if (
            not plan
            or not medicine
            or plan.is_prn
            or plan.state.value in {"draft", "pending_clarification"}
            or not plan.effective_from
            or not plan.effective_from <= occurrence.due_at
            or (plan.effective_to and occurrence.due_at >= plan.effective_to)
            or not now - timedelta(days=7) <= occurrence.due_at <= now
        ):
            raise ValidationError("Choose an existing scheduled occurrence from the past seven days")
        local_date = occurrence.due_at.astimezone(zone).date()
        if (
            medicine.identity_status.value not in {"user_reviewed_document", "professional_verified"}
            or (plan.course_start_date and local_date < plan.course_start_date)
            or (plan.course_end_date and local_date > plan.course_end_date)
        ):
            raise ValidationError("A reviewed medication and applicable course are required")
        if not source or source.review_status.value not in {"user_reviewed", "professional_verified"}:
            raise ValidationError("Reviewed instructions are required")
        latest = entries[-1] if entries else None
        return DoseFollowUp(
            occurrence_id=occurrence.id,
            regimen_id=plan.id,
            medication_id=medicine.id,
            medication_name=medicine.display_name,
            strength_text=source.dose_basis.strength_text if source.dose_basis else None,
            form=source.dose_basis.form if source.dose_basis else None,
            version_no=plan.version_no,
            due_at=occurrence.due_at,
            dose_amount=plan.dose_amount,
            dose_unit=plan.dose_unit,
            report_id=event.id if event else None,
            intake_status=event.intake_status.value if event else None,
            actual_administration_at=latest.actual_administration_at if latest else None,
            recorded_at=latest.recorded_at if latest else event.created_at if event else None,
            reason=latest.reason if latest else None,
            notes=latest.notes if latest else "",
        )

    def recent(self, patient_id: UUID, include_reported: bool = False) -> dict:
        now, zone = self.clock.now(), self.schedule.local_timezone(patient_id)
        candidates = []
        context = self.enrollment.read_context(patient_id)
        zone_info = ZoneInfo(zone)
        for medicine in context.medications:
            for plan in context.by_medication[medicine.id]:
                if plan.is_prn or plan.state.value in {"draft", "pending_clarification"}:
                    continue
                if plan.state.value == "active":
                    self.schedule.materialize(patient_id=patient_id, regimen_id=plan.id, days=1)
                rows = self.enrollment_occurrences(patient_id, plan.id, now)
                events = {
                    event.occurrence_id: event
                    for event in self.events.list_for_occurrences(patient_id, [row.id for row in rows])
                }
                for index, entry in enumerate(rows):
                    event = events.get(entry.id)
                    if event and not include_reported:
                        continue
                    _, day_end = local_day_window(entry.due_at.astimezone(zone_info).date(), zone)
                    following = rows[index + 1].due_at if index + 1 < len(rows) else None
                    if not event and now < attention_deadline(entry.due_at, following, day_end):
                        continue
                    candidates.append((entry, plan, medicine, event))
        # Eligibility and ordering do not depend on correction-history contents.
        # Fetch histories only for the page returned, never every historical row.
        candidates.sort(key=lambda row: row[0].due_at, reverse=True)
        page = candidates[:50]
        histories = {}
        for report in self.repository.histories(patient_id, [row[0].id for row in page]):
            histories.setdefault(report.occurrence_id, []).append(report)
        items = []
        for entry, plan, medicine, event in page:
            try:
                items.append(self._describe_occurrence(
                    occurrence=entry, plan=plan, medicine=medicine, source=context.sources.get(plan.source_id),
                    now=now, zone=zone_info, event=event, entries=histories.get(entry.id, []),
                ))
            except ValidationError:
                items.append(DoseFollowUp(
                    occurrence_id=entry.id, regimen_id=plan.id, medication_id=medicine.id,
                    medication_name=medicine.display_name, due_at=entry.due_at, dose_amount=plan.dose_amount,
                    dose_unit=plan.dose_unit, version_no=plan.version_no,
                    report_id=event.id if event else None, intake_status=event.intake_status.value if event else None,
                    recorded_at=event.created_at if event else None, can_report=False,
                    unavailable_reason="review_required",
                ))
        return {"items": items, "has_more": len(candidates) > 50, "as_of": now, "timezone": zone}

    def enrollment_occurrences(self, patient_id, regimen_id, now):
        return self.schedule.existing_occurrences(
            patient_id, regimen_id, now - timedelta(days=7), now + timedelta(microseconds=1)
        )

    def validate(self, patient_id, occurrence_id, values):
        item = self.occurrence(patient_id, occurrence_id)
        if item.report_id != values.expected_report_id:
            raise ValidationError("This report changed. Reload it before confirming a correction")
        if values.actual_administration_at:
            plan = self.enrollment.get_regimen(patient_id, item.regimen_id)
            local_date = values.actual_administration_at.astimezone(
                ZoneInfo(self.schedule.local_timezone(patient_id))
            ).date()
            if (
                values.actual_administration_at > self.clock.now()
                or values.actual_administration_at < self.clock.now() - timedelta(days=7)
                or values.actual_administration_at < plan.effective_from
                or (plan.effective_to and values.actual_administration_at >= plan.effective_to)
                or (plan.course_start_date and local_date < plan.course_start_date)
                or (plan.course_end_date and local_date > plan.course_end_date)
            ):
                raise ValidationError("Actual administration time must be in the past and within this plan version")
        return item

    def prepare(self, patient_id, occurrence_id, values, session):
        item = self.validate(patient_id, occurrence_id, values)
        now = self.clock.now()
        prior = self.challenges.find_by_idempotency_key(patient_id, values.binding_key(occurrence_id))
        if prior:
            if prior.expires_at <= now or prior.consumed_at:
                raise ConfirmationRequiredError("This confirmation expired; start a new report")
            return LateReportChallenge(
                challenge_id=prior.id,
                session_id=prior.session_id,
                expires_at=prior.expires_at,
                occurrence=item,
                proposed=values,
                timezone=self.schedule.local_timezone(patient_id),
            )
        challenge = ConfirmationChallengeDTO(
            id=self.ids.new_id(),
            patient_id=patient_id,
            session_id=session.id,
            session_state_version=session.state_version,
            action="record_self_report",
            regimen_id=item.regimen_id,
            occurrence_id=occurrence_id,
            intended_intake_status=IntakeStatus(values.intake_status),
            idempotency_key=values.binding_key(occurrence_id),
            token_hash=hashlib.sha256(self.ids.new_id().bytes).hexdigest(),
            issued_at=now,
            expires_at=now + timedelta(minutes=10),
        )
        self.challenges.add(challenge)
        return LateReportChallenge(
            challenge_id=challenge.id,
            session_id=session.id,
            expires_at=challenge.expires_at,
            occurrence=item,
            proposed=values,
            timezone=self.schedule.local_timezone(patient_id),
        )

    def confirm(self, patient_id, occurrence_id, values, challenge_id):
        existing = next(
            (row for row in self.repository.history(patient_id, occurrence_id) if row.id == values.id), None
        )
        if existing:
            if existing.idempotency_key != values.binding_key(occurrence_id):
                raise ValidationError("Report key was already used for different details")
            return existing
        item = self.validate(patient_id, occurrence_id, values)
        challenge = self.challenges.get(patient_id, challenge_id)
        now = self.clock.now()
        if (
            not challenge
            or challenge.action != "record_self_report"
            or challenge.regimen_id != item.regimen_id
            or challenge.occurrence_id != occurrence_id
            or challenge.idempotency_key != values.binding_key(occurrence_id)
            or challenge.intended_intake_status.value != values.intake_status
            or challenge.consumed_at
            or challenge.expires_at <= now
        ):
            raise ConfirmationRequiredError("Review and confirm this exact report again")
        self.challenges.update(challenge.model_copy(update={"confirmed_at": challenge.confirmed_at or now}))
        return self.repository.save(patient_id, occurrence_id, values, challenge_id, now)
