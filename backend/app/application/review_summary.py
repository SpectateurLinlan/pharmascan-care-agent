"""Read only actual regimen versions, generated occurrences, reports and feelings."""

from datetime import UTC, datetime, time, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from ..contracts.ports import Clock, DoseEventRepository, DoseOccurrenceRepository
from ..contracts.review_summary import ReviewSummary, SummaryMedication
from ..domain.errors import NotFoundError, ValidationError
from .enrollment import MedicationEnrollmentService
from .observations import ObservationService


class ReviewSummaryService:
    def __init__(
        self,
        enrollment: MedicationEnrollmentService,
        occurrences: DoseOccurrenceRepository,
        events: DoseEventRepository,
        observations: ObservationService,
        clock: Clock,
    ):
        self._enrollment, self._occurrences, self._events = enrollment, occurrences, events
        self._observations, self._clock = observations, clock

    def generate(
        self,
        patient_id: UUID,
        period: Literal["week", "month", "course"],
        regimen_id: UUID | None = None,
        timezone: str = "Asia/Singapore",
    ) -> ReviewSummary:
        now, zone = self._clock.now(), ZoneInfo(timezone)
        local = now.astimezone(zone)
        start_date = local.date() - timedelta(days=local.weekday()) if period == "week" else local.date().replace(day=1)
        end = now
        selected = None
        if period == "course":
            if not regimen_id:
                raise ValidationError("Choose a medication course")
            selected = self._enrollment.get_regimen(patient_id, regimen_id)
            if not selected:
                raise NotFoundError("Course not found for this patient")
            if not selected.course_start_date and not selected.effective_from:
                raise ValidationError("This course has no reviewed start date")
            start_date = selected.course_start_date or selected.effective_from.astimezone(zone).date()
            if selected.course_end_date:
                end = min(now, datetime.combine(selected.course_end_date + timedelta(days=1), time.min, zone))
        start = datetime.combine(start_date, time.min, zone).astimezone(UTC)
        end = end.astimezone(UTC)
        if start > end:
            raise ValidationError("This course has not started")
        if end - start > timedelta(days=366):
            raise ValidationError("Choose a week or month for courses longer than one year")
        # One bounded patient-time query also sees reports saved after an ended
        # course. Avoid a network call per occurrence and false missing reports.
        all_reports = self._events.list_for_patient(patient_id, start, now + timedelta(microseconds=1))
        reported_occurrences = {row.occurrence_id for row in all_reports if row.occurrence_id is not None}
        medications = []
        for medication in self._enrollment.list_medications(patient_id):
            for regimen in self._enrollment.list_regimens(patient_id, medication.id):
                if selected and regimen.id != selected.id:
                    continue
                if not regimen.effective_from or regimen.effective_from > end:
                    continue
                if regimen.effective_to and regimen.effective_to < start:
                    continue
                if regimen.course_end_date and regimen.course_end_date < start_date:
                    continue
                if regimen.course_start_date and regimen.course_start_date > end.astimezone(zone).date():
                    continue
                occurrences = self._occurrences.list_for_regimen(patient_id, regimen.id, start, end)
                # An occurrence may be reported outside the summary window.
                missing = sum(row.id not in reported_occurrences for row in occurrences)
                medications.append(
                    SummaryMedication(
                        medication_id=medication.id,
                        regimen_id=regimen.id,
                        name=medication.display_name,
                        version=regimen.version_no,
                        state=str(regimen.state),
                        is_prn=regimen.is_prn,
                        dose_amount=regimen.dose_amount,
                        dose_unit=regimen.dose_unit,
                        food_instruction=regimen.food_instruction,
                        course_start=str(regimen.course_start_date) if regimen.course_start_date else None,
                        course_end=str(regimen.course_end_date) if regimen.course_end_date else None,
                        local_times=(regimen.frequency_rule or {}).get("local_times", []),
                        recorded_occurrences=len(occurrences),
                        without_report=missing,
                    )
                )
        events = [row for row in all_reports if start <= row.event_time < end]
        if selected:
            events = [row for row in events if row.regimen_id == selected.id]
        observations = self._observations.list(patient_id, start, end)
        if selected:
            observations = [row for row in observations if row.medication_id in (None, selected.patient_medication_id)]
        questions = (
            ["Which scheduled doses still need a patient report?"]
            if any(row.without_report for row in medications)
            else []
        )
        if observations:
            questions.append("Are there feelings or symptoms you would like to discuss with a healthcare professional?")
        if any(row.course_end is None for row in medications):
            questions.append("Is the intended course end date documented in your reviewed instructions?")
        return ReviewSummary(
            period=period,
            window_start=start,
            window_end=end,
            generated_at=now,
            timezone=timezone,
            medications=medications,
            observations=observations,
            questions=questions,
            reported_taken=sum(row.intake_status.value == "reported_taken" for row in events),
            reported_not_taken=sum(row.intake_status.value == "reported_not_taken" for row in events),
            unsure=sum(row.intake_status.value == "unsure" for row in events),
            coverage_note="Only stored generated occurrences are counted; ungenerated schedules are not reconstructed. "
            "Reports are counted by report time. No report is not a missed dose; "
            "no health note is not absence of symptoms. Feelings are patient descriptions, "
            "not diagnoses or established drug effects. Health notes are limited to 500 per window.",
        )
