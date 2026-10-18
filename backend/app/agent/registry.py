"""Tool registry: allowlisted handlers that call application services only.

Each tool is a thin typed adapter: validate -> call service -> map result or
map domain error to a stable ToolResult. No SQL, no ORM, no HTTP internals.
Every invocation is recorded as a redacted tool trace.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from ..application.dosing import DoseScheduleService, SelfReportService
from ..application.enrollment import MedicationEnrollmentService
from ..application.reminders import ReminderService
from ..application.temporal_doses import TemporalDoseReader
from ..contracts.dto import (
    ConfirmationChallengeDTO,
    DoseEventInput,
    FrequencyRuleDTO,
    PatientMedicationDTO,
    RegimenDraftInput,
    SelfReportChallengeResultDTO,
)
from ..contracts.enums import (
    RegimenState,
    ToolName,
    ToolStatus,
)
from ..contracts.ports import Clock, IdGenerator, ToolTraceRepository
from ..contracts.temporal import CalendarSelection, calendar_selection, local_day_window
from ..domain.errors import DomainError, NotFoundError, ProviderUnavailableError, ValidationError
from ..domain.policy import intake_status_from_patient_choice
from .tools import (
    CheckDueDoseRequest,
    ConfirmRegimenRequest,
    CreateReminderRequest,
    EnrollMedicationRequest,
    EnrollmentResultPayload,
    GetDoseStatusRequest,
    MedicationHistoryRequest,
    RecordSelfReportRequest,
    ToolRequest,
    ToolResult,
)


class UnknownToolError(Exception):
    """Raised when a caller asks for a tool outside the allowlist."""


class ToolRegistry:
    """Allowlist registry; the ONLY way the agent reaches application logic."""

    def __init__(
        self,
        *,
        enrollment: MedicationEnrollmentService,
        schedule: DoseScheduleService,
        self_report: SelfReportService,
        traces: ToolTraceRepository,
        clock: Clock,
        ids: IdGenerator,
        max_trace_summary_bytes: int = 1024,
        reminders: ReminderService | None = None,
    ) -> None:
        self._temporal = TemporalDoseReader(enrollment=enrollment, schedule=schedule, reports=self_report, clock=clock)
        self._reminders = reminders
        self._enrollment = enrollment
        self._schedule = schedule
        self._self_report = self_report
        self._traces = traces
        self._clock = clock
        self._ids = ids
        self._max_summary = max_trace_summary_bytes
        self._handlers: dict[ToolName, Callable[[ToolRequest], ToolResult]] = {
            ToolName.CREATE_REMINDER: self._create_reminder,
            ToolName.LIST_ACTIVE_MEDICATIONS: self._list_active_medications,
            ToolName.GET_MEDICATION_HISTORY: self._get_medication_history,
            ToolName.GET_DOSE_STATUS: self._get_dose_status,
            ToolName.ENROLL_MEDICATION_DRAFT: self._enroll_medication_draft,
            ToolName.CONFIRM_REGIMEN_DRAFT: self._confirm_regimen_draft,
            ToolName.CHECK_DUE_DOSE: self._check_due_dose,
            ToolName.RECORD_SELF_REPORT: self._record_self_report,
        }

    def record_care_result(self, request: ToolRequest, result: ToolResult) -> None:
        """Audit application-only long-term tools without logging patient content."""
        if result.tool_name not in (ToolName.GET_LONG_TERM_CARE, ToolName.PREPARE_CARE_ACTION):
            raise UnknownToolError("Unsupported extension trace")
        self._record_trace(result.tool_name, request, result, 0)

    def _create_reminder(self, request: ToolRequest) -> ToolResult:
        assert isinstance(request, CreateReminderRequest)
        if self._reminders is None:
            raise ProviderUnavailableError("Reminder preferences unavailable")
        row = self._reminders.snooze(
            patient_id=request.patient_id, occurrence_id=request.occurrence_id, minutes=request.minutes
        )
        return ToolResult(
            tool_name=ToolName.CREATE_REMINDER, status=ToolStatus.SUCCESS, payload=row.model_dump(mode="json")
        )

    @property
    def allowlist(self) -> frozenset[ToolName]:
        return frozenset(self._handlers)

    def execute(self, tool_name: ToolName | str, request: ToolRequest) -> ToolResult:
        """Execute one allowlisted tool and always record a redacted trace."""
        try:
            name = ToolName(tool_name)
        except ValueError as exc:
            raise UnknownToolError(f"{tool_name!r} is not an allowlisted tool") from exc
        if name not in self._handlers:
            raise UnknownToolError(f"{name} is not registered")

        started = self._clock.now()
        try:
            result = self._handlers[name](request)
        except DomainError as exc:
            result = ToolResult(
                tool_name=name,
                status=ToolStatus.BLOCKED,
                error_code=exc.code.value,
                error_message=str(exc),
                rule_id=exc.rule_id.value if exc.rule_id else None,
                requires_confirmation=exc.code.value == "CONFIRMATION_REQUIRED",
            )
        elapsed_ms = int((self._clock.now() - started).total_seconds() * 1000)
        self._record_trace(name, request, result, elapsed_ms)
        return result

    # -- handlers ------------------------------------------------------------

    def _list_active_medications(self, request: ToolRequest) -> ToolResult:
        active: list[dict[str, object]] = []
        now = self._clock.now()
        today = now.astimezone(ZoneInfo(self.local_timezone(request.patient_id))).date()
        for medication in self._enrollment.list_medications(request.patient_id):
            regimen = self._enrollment.find_active_regimen(request.patient_id, medication.id)
            if regimen is None or medication.archived_at is not None:
                continue
            if (
                (regimen.effective_from and regimen.effective_from > now)
                or (regimen.effective_to and regimen.effective_to <= now)
                or (regimen.course_start_date and regimen.course_start_date > today)
                or (regimen.course_end_date and regimen.course_end_date < today)
            ):
                continue
            source = self._enrollment.get_source(request.patient_id, regimen.source_id)
            basis = source.dose_basis if source else None
            product = (
                source.extraction_evidence.candidates[0].product
                if source
                and source.review_status.value in {"user_reviewed", "professional_verified"}
                and source.extraction_evidence
                and len(source.extraction_evidence.candidates) == 1
                else None
            )
            active.append(
                {
                    "medication_id": str(medication.id),
                    "regimen_id": str(regimen.id),
                    "display_name": medication.display_name,
                    "is_prn": regimen.is_prn,
                    "version_no": regimen.version_no,
                    "identity_status": medication.identity_status.value,
                    "ingredients": [item.name[:100] for item in product.ingredients[:8]] if product else [],
                    "strength_text": basis.strength_text if basis and basis.patient_checked else None,
                    "dosage_form": basis.form if basis and basis.patient_checked else None,
                    "dose_amount": regimen.dose_amount,
                    "dose_unit": regimen.dose_unit,
                    "frequency_rule": regimen.frequency_rule,
                    "course_start_date": regimen.course_start_date.isoformat() if regimen.course_start_date else None,
                    "course_end_date": regimen.course_end_date.isoformat() if regimen.course_end_date else None,
                }
            )
        return ToolResult(
            tool_name=ToolName.LIST_ACTIVE_MEDICATIONS,
            status=ToolStatus.SUCCESS,
            payload={"item_count": len(active), "medications": active},
        )

    def _get_medication_history(self, request: ToolRequest) -> ToolResult:
        assert isinstance(request, MedicationHistoryRequest)
        if request.medication_name and not request.medication_id:
            medication = self._resolve_medication_by_name(
                request.patient_id, request.medication_name.casefold().strip()
            )
            if medication is None:
                raise ValidationError("Choose one specific medicine for this history query")
            request = request.model_copy(update={"medication_id": medication.id})
        now = self._clock.now()
        zone = self.local_timezone(request.patient_id)
        today = now.astimezone(ZoneInfo(zone)).date()
        if request.target_date or request.day_offset:
            day = request.target_date or today + timedelta(days=request.day_offset)
            start, end = local_day_window(day, zone)
            if day > today:
                raise ValidationError("A future date is not dose history")
            end = min(end, now)
        else:
            start, _ = local_day_window(today - timedelta(days=request.days - 1), zone)
            end = now
        if request.regimen_id:
            plan = self._enrollment.get_regimen(request.patient_id, request.regimen_id)
            if plan is None or (request.medication_id and plan.patient_medication_id != request.medication_id):
                raise NotFoundError("Plan not found for this patient")
            plans = [plan]
        else:
            medications = self._enrollment.list_medications(request.patient_id)
            if request.medication_id:
                medications = [row for row in medications if row.id == request.medication_id]
                if not medications:
                    raise NotFoundError("Medicine not found for this patient")
            plans = [
                plan
                for med in medications
                for plan in self._enrollment.list_regimens(request.patient_id, med.id)
                if plan.state in {RegimenState.ACTIVE, RegimenState.ENDED, RegimenState.SUPERSEDED}
            ]
        if len(plans) > 100:
            raise ValidationError("Too many plans for this read; choose a specific medication or plan")
        entries = [
            entry
            for plan in plans
            for entry in self._self_report.history(
                patient_id=request.patient_id, regimen_id=plan.id, window_start=start, window_end=end
            )
        ]
        entries.sort(key=lambda row: row.occurrence.due_at if row.occurrence else row.event.event_time, reverse=True)
        plan_details = {}
        for plan in plans:
            source = self._enrollment.get_source(request.patient_id, plan.source_id)
            basis = source.dose_basis if source else None
            plan_details[plan.id] = {
                "strength_text": basis.strength_text if basis and basis.patient_checked else None,
                "dosage_form": basis.form if basis and basis.patient_checked else None,
                "regimen_version": plan.version_no,
                "regimen_effective_from": plan.effective_from.isoformat() if plan.effective_from else None,
            }
        serialised = [
            {
                **plan_details[entry.regimen_id],
                "occurrence_id": str(entry.occurrence.id) if entry.occurrence else None,
                "regimen_id": str(entry.regimen_id),
                "display_name": entry.medication_display_name,
                "due_at": entry.occurrence.due_at.isoformat() if entry.occurrence else None,
                "event_time": entry.event.event_time.isoformat() if entry.event else None,
                "submitted_at": entry.event.created_at.isoformat() if entry.event else None,
                "intake_status": entry.event.intake_status.value if entry.event else None,
                "visual_status": entry.event.visual_status.value if entry.event else None,
                "reported": entry.event is not None,
            }
            for entry in entries
        ]
        return ToolResult(
            tool_name=ToolName.GET_MEDICATION_HISTORY,
            status=ToolStatus.SUCCESS,
            payload={
                "item_count": len(serialised),
                "entries": serialised[:20],
                "returned_count": min(len(serialised), 20),
                "plan_count": len(plans),
                "medication_id": str(request.medication_id) if request.medication_id else None,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "local_timezone": zone,
                # Absence of a report is explicitly NOT a missed dose.
                "note": "not_reported is not the same as missed",
            },
        )

    def local_timezone(self, patient_id: UUID) -> str:
        return self._schedule.local_timezone(patient_id)

    def current_time(self) -> datetime:
        """Public injected request clock for bounded read-state expiry."""
        return self._clock.now()

    def calendar_selection(self, patient_id: UUID, text: str) -> CalendarSelection:
        return calendar_selection(text, self._clock.now(), self.local_timezone(patient_id))

    def _get_dose_status(self, request: ToolRequest) -> ToolResult:
        assert isinstance(request, GetDoseStatusRequest)
        medication = (
            self._enrollment.get_medication(request.patient_id, request.medication_id)
            if request.medication_id
            else self._resolve_medication_by_name(request.patient_id, (request.medication_name or "").strip().lower())
        )
        if medication is None:
            return ToolResult(
                tool_name=ToolName.GET_DOSE_STATUS,
                status=ToolStatus.BLOCKED,
                error_code="NOT_FOUND",
                error_message=(
                    f"I could not find a unique registered medicine matching {request.medication_name!r}. "
                    "Please specify which medicine."
                ),
                payload={"resolution": "unknown_medication", "reported": False},
            )
        timezone = self.local_timezone(request.patient_id)
        today = self._clock.now().astimezone(ZoneInfo(timezone)).date()
        day = request.target_date or today + timedelta(days=request.day_offset)
        start, end = local_day_window(day, timezone)
        plans, entries = self._temporal.read_day(request.patient_id, medication.id, day)
        if request.occurrence_id:
            occurrence = self._schedule.get_occurrence(request.patient_id, request.occurrence_id)
            versions = self._enrollment.list_regimens(request.patient_id, medication.id)
            if occurrence is None or occurrence.regimen_id not in {plan.id for plan in versions}:
                raise NotFoundError("Referenced occurrence does not belong to this medication")
            if not start <= occurrence.due_at < end:
                raise ValidationError("Referenced occurrence is outside the requested local date")
            entries = [row for row in entries if row.occurrence and row.occurrence.id == occurrence.id]
        reported = [row for row in entries if row.event is not None]
        latest = reported[0] if reported else None
        plan_id = latest.regimen_id if latest else plans[0].id if len(plans) == 1 else None
        records = []
        for row in entries:
            moment = row.occurrence.due_at if row.occurrence else row.event.event_time
            records.append(
                {
                    "regimen_id": str(row.regimen_id),
                    "occurrence_id": str(row.occurrence.id) if row.occurrence else None,
                    "due_at": row.occurrence.due_at.isoformat() if row.occurrence else None,
                    "event_time": row.event.event_time.isoformat() if row.event else None,
                    "reported_at": row.event.event_time.isoformat() if row.event else None,
                    "created_at": row.event.created_at.isoformat() if row.event else None,
                    "intake_status": row.event.intake_status.value if row.event else "no_report",
                    "future": moment > self._clock.now(),
                }
            )
        return ToolResult(
            tool_name=ToolName.GET_DOSE_STATUS,
            status=ToolStatus.SUCCESS,
            payload={
                "resolution": "resolved" if plans or entries else "no_regimen",
                "medication_id": str(medication.id),
                "medication_name": medication.display_name,
                "regimen_id": str(plan_id) if plan_id else None,
                "occurrence_id": str(request.occurrence_id) if request.occurrence_id else None,
                "regimen_active": any(plan.state == RegimenState.ACTIVE for plan in plans),
                "local_date": day.isoformat(),
                "relative_day": (day - today).days,
                "local_timezone": timezone,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "reported": bool(reported),
                "intake_status": latest.event.intake_status.value if latest else "no_report",
                "reported_at": latest.event.event_time.isoformat() if latest else None,
                "ingestion_proven": False,
                "self_report_count": len(reported),
                "occurrence_count": len(entries),
                "records": records,
                "coverage": "saved occurrences and reports; historical schedules are not reconstructed",
                "note": "No confirmed dose record is not the same as a missed dose."
                if not reported
                else "Patient report only",
            },
        )

    def _resolve_medication_by_name(self, patient_id: UUID, needle: str) -> PatientMedicationDTO | None:
        """Match a free-text name against the patient's own medications.

        Exact (case-insensitive) match wins over substring candidates, but
        only a unique patient-owned identity can resolve. Multiple strengths
        or independent registrations require clarification; never pick first.
        """
        candidates = [
            m for m in self._enrollment.list_medications(patient_id) if needle and needle in m.display_name.lower()
        ]
        if not candidates:
            return None
        exact = [m for m in candidates if m.display_name.lower() == needle]
        pool = exact or candidates
        # Deterministic ordering: shortest (most specific prefix) then name.
        return pool[0] if len(pool) == 1 else None

    def _enroll_medication_draft(self, request: ToolRequest) -> ToolResult:
        assert isinstance(request, EnrollMedicationRequest)
        frequency = None
        if request.frequency_kind is not None:
            frequency = FrequencyRuleDTO(
                kind=request.frequency_kind,  # type: ignore[arg-type]
                local_times=list(request.frequency_local_times),
                days_of_week=list(request.frequency_days_of_week),
                every_hours=request.frequency_every_hours,
            )
        result = self._enrollment.enroll_draft(
            patient_id=request.patient_id,
            draft=RegimenDraftInput(
                medication_name=request.medication_name,
                dose_amount=request.dose_amount,
                dose_unit=request.dose_unit,
                frequency_rule=frequency,
                is_prn=request.is_prn,
                route=request.route,
                food_instruction=request.food_instruction,
            ),
        )
        payload = EnrollmentResultPayload(
            medication_id=result.medication.id,
            regimen_id=result.regimen.id,
            state=result.regimen.state.value,
            missing_instructions=[m.field.value for m in result.missing_instructions],
        )
        return ToolResult(
            tool_name=ToolName.ENROLL_MEDICATION_DRAFT,
            status=ToolStatus.SUCCESS,
            payload=payload.model_dump(mode="json"),
            clarification_question=(
                "I still need: " + ", ".join(payload.missing_instructions) if payload.missing_instructions else None
            ),
        )

    def _confirm_regimen_draft(self, request: ToolRequest) -> ToolResult:
        assert isinstance(request, ConfirmRegimenRequest)
        # An explicit user confirmation is required before any state change.
        self._enrollment.confirm_challenge(patient_id=request.patient_id, challenge_id=request.challenge_id)
        activated = self._enrollment.activate_regimen(
            patient_id=request.patient_id,
            regimen_id=request.regimen_id,
            challenge_id=request.challenge_id,
            session_state=request.session_state,
            session_state_version=request.session_state_version,
        )
        return ToolResult(
            tool_name=ToolName.CONFIRM_REGIMEN_DRAFT,
            status=ToolStatus.SUCCESS,
            payload={
                "regimen_id": str(activated.regimen.id),
                "state": activated.regimen.state.value,
                "superseded_count": len(activated.superseded_regimen_ids),
            },
        )

    def _check_due_dose(self, request: ToolRequest) -> ToolResult:
        assert isinstance(request, CheckDueDoseRequest)
        timezone = self._schedule.local_timezone(request.patient_id)
        if request.window in {"tonight", "today"} or request.target_date or request.day_offset:
            today = self._clock.now().astimezone(ZoneInfo(timezone)).date()
            day = request.target_date or today + timedelta(days=request.day_offset)
            start, end = local_day_window(day, timezone)
            if request.window == "tonight":
                start = datetime.combine(day, datetime.min.time(), ZoneInfo(timezone)).replace(hour=18).astimezone(UTC)
            rows = []
            for medication in self._enrollment.list_medications(request.patient_id):
                plans, entries = self._temporal.read_day(request.patient_id, medication.id, day)
                for plan in plans:
                    if request.regimen_id is not None and request.regimen_id != plan.id:
                        continue
                    for instant in self._schedule.planned_instants(
                        patient_id=request.patient_id,
                        regimen_id=plan.id,
                        start=start,
                        end=end,
                    ):
                        record = next(
                            (
                                row
                                for row in entries
                                if row.regimen_id == plan.id and row.occurrence and row.occurrence.due_at == instant
                            ),
                            None,
                        )
                        rows.append(
                            {
                                "medication_name": medication.display_name,
                                "medication_id": str(medication.id),
                                "regimen_id": str(plan.id),
                                "occurrence_id": str(record.occurrence.id) if record else None,
                                "dose_amount": plan.dose_amount,
                                "dose_unit": plan.dose_unit,
                                "due_at": instant.isoformat(),
                                "local_time": instant.astimezone(ZoneInfo(timezone)).strftime("%H:%M"),
                                "intake_status": record.event.intake_status.value
                                if record and record.event
                                else "not_reported",
                                "future": instant > self._clock.now(),
                                "food_instruction": plan.food_instruction,
                            }
                        )
            rows.sort(key=lambda row: (row["due_at"], row["regimen_id"]))
            return ToolResult(
                tool_name=ToolName.CHECK_DUE_DOSE,
                status=ToolStatus.SUCCESS,
                payload={
                    "window": "tonight" if request.window == "tonight" else "today",
                    "local_timezone": timezone,
                    "local_date": day.isoformat(),
                    "relative_day": (day - today).days,
                    "window_start": start.isoformat(),
                    "window_end": end.isoformat(),
                    "schedule": rows,
                    "item_count": len(rows),
                },
            )
        candidates: list[dict[str, object]] = []
        regimens = []
        if request.regimen_id is not None:
            regimen = self._enrollment.get_regimen(request.patient_id, request.regimen_id)
            if regimen is not None:
                regimens.append(regimen)
        else:
            for medication in self._enrollment.list_medications(request.patient_id):
                regimen = self._enrollment.find_active_regimen(request.patient_id, medication.id)
                if regimen is not None:
                    regimens.append(regimen)

        for regimen in regimens:
            if regimen.is_prn:
                # PRN has no scheduled dose to check.
                continue
            self._schedule.materialize(patient_id=request.patient_id, regimen_id=regimen.id, days=2)
            due = self._schedule.find_due(patient_id=request.patient_id, regimen_id=regimen.id)
            if due.occurrence is not None:
                medication = self._enrollment.get_medication(request.patient_id, regimen.patient_medication_id)
                if medication is None:
                    raise ValidationError("The scheduled medication record is unavailable.")
                candidates.append(
                    {
                        "regimen_id": str(regimen.id),
                        "medication_id": str(regimen.patient_medication_id),
                        "occurrence_id": str(due.occurrence.id),
                        "due_at": due.occurrence.due_at.isoformat(),
                        "medication_name": medication.display_name,
                        "dose_amount": regimen.dose_amount,
                        "dose_unit": regimen.dose_unit,
                        "local_time": due.occurrence.due_at.astimezone(ZoneInfo(timezone)).strftime("%H:%M"),
                        "food_instruction": regimen.food_instruction,
                        "intake_status": "not_reported",
                    }
                )
        return ToolResult(
            tool_name=ToolName.CHECK_DUE_DOSE,
            status=ToolStatus.SUCCESS,
            payload={
                "window": "due",
                "local_timezone": timezone,
                "item_count": len(candidates),
                "due_doses": candidates,
            },
            clarification_question=None if candidates else "No dose is due right now.",
        )

    def _record_self_report(self, request: ToolRequest) -> ToolResult:
        assert isinstance(request, RecordSelfReportRequest)
        # Accept the patient-facing labels ('Taken', 'Not now', 'Unsure') as
        # well as the canonical snake_case values; invalid input is rejected
        # by the deterministic mapper rather than silently defaulted.
        intake = intake_status_from_patient_choice(request.intake_status)
        occurrence_id = request.occurrence_id
        if request.confirmed_challenge_id is not None:
            prior = self._self_report.find_confirmation(
                patient_id=request.patient_id, idempotency_key=request.idempotency_key
            )
            if prior is None or prior.id != request.confirmed_challenge_id or prior.session_id != request.session_id:
                raise ValidationError("Confirmation does not belong to the current Agent session")
            if occurrence_id is None:
                occurrence_id = prior.occurrence_id
        if occurrence_id is not None:
            occurrence = self._schedule.get_occurrence(request.patient_id, occurrence_id)
            zone = ZoneInfo(self.local_timezone(request.patient_id))
            if occurrence is None or occurrence.regimen_id != request.regimen_id:
                raise NotFoundError("Dose occurrence does not belong to this regimen")
            if occurrence.due_at.astimezone(zone).date() != self._clock.now().astimezone(zone).date():
                raise ValidationError("Historical dose backfill is not supported by the Agent; no record was saved")
        # The database requires a confirmed 'record_self_report' challenge. When
        # the caller has not supplied one, the service raises
        # CONFIRMATION_REQUIRED, which the registry turns into
        # requires_confirmation=True so the orchestrator gates the write instead
        # of failing it. Nothing is ever fabricated to satisfy the constraint.
        outcome = self._self_report.report(
            patient_id=request.patient_id,
            payload=DoseEventInput(
                regimen_id=request.regimen_id,
                occurrence_id=occurrence_id,
                intake_status=intake,
                event_time=self._clock.now(),
                idempotency_key=request.idempotency_key,
            ),
            challenge_id=request.confirmed_challenge_id,
        )
        event_id = outcome.event.id if outcome.event else outcome.existing_event_id
        return ToolResult(
            tool_name=ToolName.RECORD_SELF_REPORT,
            status=ToolStatus.SUCCESS,
            payload={
                "event_id": str(event_id) if event_id else None,
                "intake_status": intake.value,
                "visual_status": "not_checked",
                "already_recorded": outcome.already_recorded,
                "ingestion_proven": False,
                "state": "recorded",
            },
        )

    def find_self_report_confirmation(self, patient_id: UUID, key: str) -> ConfirmationChallengeDTO | None:
        return self._self_report.find_confirmation(patient_id=patient_id, idempotency_key=key)

    def prepare_self_report_confirmation(
        self,
        request: RecordSelfReportRequest,
        *,
        session_state_version: int,
    ) -> SelfReportChallengeResultDTO:
        """Typed application operation; issuing consent never records a dose."""
        if request.occurrence_id is not None:
            occurrence = self._schedule.get_occurrence(request.patient_id, request.occurrence_id)
            zone = ZoneInfo(self.local_timezone(request.patient_id))
            if occurrence is None or occurrence.regimen_id != request.regimen_id:
                raise NotFoundError("Dose occurrence does not belong to this regimen")
            if occurrence.due_at.astimezone(zone).date() != self._clock.now().astimezone(zone).date():
                raise ValidationError("Historical dose backfill is not supported by the Agent")
        return self._self_report.request_confirmation(
            patient_id=request.patient_id,
            regimen_id=request.regimen_id,
            occurrence_id=request.occurrence_id,
            intake_status=intake_status_from_patient_choice(request.intake_status),
            idempotency_key=request.idempotency_key,
            session_id=request.session_id,
            session_state_version=session_state_version,
        )

    # -- tracing -------------------------------------------------------------

    def _record_trace(self, name: ToolName, request: ToolRequest, result: ToolResult, elapsed_ms: int) -> None:
        """Persist a redacted trace. Summaries are allowlist-checked by size
        and by key, mirroring core_trace_summary_is_safe."""
        allowed_keys = {
            "item_count",
            "demo_only",
            "decision",
            "error_code",
            "state",
            "intake_status",
            "visual_status",
            "already_recorded",
            "missing_count",
        }
        raw_request = {
            "state": getattr(request, "session_state", None),
            "demo_only": True,
        }
        raw_response = {
            "item_count": result.payload.get("item_count"),
            "state": result.payload.get("state"),
            "intake_status": result.payload.get("intake_status"),
            "visual_status": result.payload.get("visual_status"),
            "already_recorded": result.payload.get("already_recorded"),
            "error_code": result.error_code,
            "demo_only": True,
        }
        from ..contracts.dto import ToolTraceDTO

        self._traces.add(
            ToolTraceDTO(
                id=self._ids.new_id(),
                patient_id=request.patient_id,
                session_id=request.session_id,
                correlation_id=request.correlation_id,
                tool_name=name.value,
                tool_status=result.status.value,
                request_summary=_sanitize(raw_request, allowed_keys, self._max_summary),
                response_summary=_sanitize(raw_response, allowed_keys, self._max_summary),
                called_at=self._clock.now(),
                duration_ms=elapsed_ms,
            )
        )


def _sanitize(summary: dict[str, object], allowed: set[str], max_bytes: int) -> dict[str, object]:
    """Keep only allowlisted, non-identifying scalar keys."""
    cleaned: dict[str, object] = {}
    for key, value in summary.items():
        if key not in allowed or value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
    encoded = str(cleaned).encode("utf-8")
    if len(encoded) > max_bytes:
        return {"demo_only": True}
    return cleaned
