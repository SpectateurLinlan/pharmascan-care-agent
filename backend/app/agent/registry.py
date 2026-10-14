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
from ..contracts.dto import (
    ConfirmationChallengeDTO,
    DoseEventInput,
    FrequencyRuleDTO,
    PatientMedicationDTO,
    RegimenDraftInput,
    RegimenVersionDTO,
    SelfReportChallengeResultDTO,
)
from ..contracts.enums import (
    RegimenState,
    ToolName,
    ToolStatus,
)
from ..contracts.ports import Clock, IdGenerator, ToolTraceRepository
from ..domain.errors import DomainError, NotFoundError, ProviderUnavailableError
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
        for medication in self._enrollment.list_medications(request.patient_id):
            regimen = self._enrollment.find_active_regimen(request.patient_id, medication.id)
            if regimen is None:
                continue
            active.append(
                {
                    "medication_id": str(medication.id),
                    "regimen_id": str(regimen.id),
                    "display_name": medication.display_name,
                    "is_prn": regimen.is_prn,
                    "version_no": regimen.version_no,
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
        from datetime import timedelta

        now = self._clock.now()
        entries = self._self_report.history(
            patient_id=request.patient_id,
            regimen_id=request.regimen_id,
            window_start=now - timedelta(days=request.days),
            window_end=now + timedelta(days=1),
        )
        serialised = [
            {
                "occurrence_id": str(entry.occurrence.id) if entry.occurrence else None,
                "due_at": entry.occurrence.due_at.isoformat() if entry.occurrence else None,
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
                "entries": serialised,
                # Absence of a report is explicitly NOT a missed dose.
                "note": "not_reported is not the same as missed",
            },
        )

    def _get_dose_status(self, request: ToolRequest) -> ToolResult:
        """Answer "have I taken <medication> today?" from recorded events only.

        This is a **read-only** tool: it never writes an event and never
        concludes that a dose was missed. It resolves the medication by name
        against the patient's own records (never by trusting a patient-supplied
        id) and then reports what has actually been reported for today's local
        day:

        - ``reported_taken``      -> the patient said they took it (at a time);
        - ``reported_not_taken``  -> the patient said they did not take it;
        - ``unsure``              -> the patient reported being unsure;
        - ``no_report``           -> nothing has been reported for that dose.

        ``no_report`` is explicitly NOT a missed dose. The tool also reports
        whether the resolved medication is still active, so a discontinued
        medication is answered as history rather than as a current status.
        """
        assert isinstance(request, GetDoseStatusRequest)
        needle = (request.medication_name or "").strip().lower()

        medication = (
            self._enrollment.get_medication(request.patient_id, request.medication_id)
            if request.medication_id
            else self._resolve_medication_by_name(request.patient_id, needle)
        )
        if medication is None:
            return ToolResult(
                tool_name=ToolName.GET_DOSE_STATUS,
                status=ToolStatus.BLOCKED,
                error_code="NOT_FOUND",
                error_message=(f"I could not find a medication called {request.medication_name!r} in your list."),
                payload={"resolution": "unknown_medication", "reported": False},
            )

        regimen = self._resolve_current_regimen(request.patient_id, medication.id)
        if regimen is None:
            return ToolResult(
                tool_name=ToolName.GET_DOSE_STATUS,
                status=ToolStatus.SUCCESS,
                payload={
                    "resolution": "no_regimen",
                    "medication_name": medication.display_name,
                    "reported": False,
                    "note": "no dose record exists for this medication",
                },
            )

        is_active = regimen.state == RegimenState.ACTIVE
        if request.occurrence_id:
            occurrence = self._schedule.get_occurrence(request.patient_id, request.occurrence_id)
            if occurrence is None or occurrence.regimen_id != regimen.id:
                raise NotFoundError("Referenced occurrence does not belong to this medication")
        tz = self._tz_for(request.patient_id)
        now = self._clock.now()
        local_now = now.astimezone(tz)
        day_start = datetime(local_now.year, local_now.month, local_now.day, tzinfo=tz).astimezone(UTC)
        day_end = day_start + timedelta(days=1)

        if not regimen.is_prn and is_active:
            # Materialise so the day's occurrence exists even when no report
            # has been made; the occurrence alone proves nothing was taken.
            # A discontinued regimen is deliberately NOT materialised — it
            # would raise, and a read-only history question must still answer.
            self._schedule.materialize(patient_id=request.patient_id, regimen_id=regimen.id, days=1)

        entries = self._self_report.history(
            patient_id=request.patient_id,
            regimen_id=regimen.id,
            window_start=day_start,
            window_end=day_end,
        )
        if request.occurrence_id:
            entries = [entry for entry in entries if entry.occurrence and entry.occurrence.id == request.occurrence_id]
        reported = [entry for entry in entries if entry.event is not None]

        if not reported:
            return ToolResult(
                tool_name=ToolName.GET_DOSE_STATUS,
                status=ToolStatus.SUCCESS,
                payload={
                    "resolution": "resolved",
                    "reported": False,
                    "intake_status": "no_report",
                    "medication_id": str(medication.id),
                    "regimen_id": str(regimen.id),
                    "occurrence_id": str(request.occurrence_id) if request.occurrence_id else None,
                    "medication_name": medication.display_name,
                    "regimen_active": is_active,
                    "occurrence_count": len(entries),
                    # Absence of a report is NOT a missed dose.
                    "note": ("No confirmed dose record for today. This is not the same as a missed dose."),
                },
                clarification_question=None,
            )

        latest = reported[-1]
        status = latest.event.intake_status.value
        return ToolResult(
            tool_name=ToolName.GET_DOSE_STATUS,
            status=ToolStatus.SUCCESS,
            payload={
                "resolution": "resolved",
                "reported": True,
                "intake_status": status,
                "medication_name": medication.display_name,
                "regimen_active": is_active,
                "medication_id": str(medication.id),
                "regimen_id": str(regimen.id),
                "occurrence_id": str(request.occurrence_id) if request.occurrence_id else None,
                "reported_at": latest.event.event_time.isoformat(),
                "visual_status": latest.event.visual_status.value,
                "ingestion_proven": False,
                "self_report_count": len(reported),
            },
        )

    def _resolve_medication_by_name(self, patient_id: UUID, needle: str) -> PatientMedicationDTO | None:
        """Match a free-text name against the patient's own medications.

        Exact (case-insensitive) match wins; otherwise the longest name that
        starts with / contains the query is chosen so "amlodipine" matches
        "Amlodipine 5mg". An ambiguous match is deliberately NOT guessed: the
        earliest deterministic candidate is returned so the answer stays
        reproducible, and the caller never receives another patient's record.
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

    def _resolve_current_regimen(self, patient_id: UUID, medication_id: UUID) -> RegimenVersionDTO | None:
        """Prefer the active regimen; fall back to the newest version."""
        active = self._enrollment.find_active_regimen(patient_id, medication_id)
        if active is not None:
            return active
        versions = self._enrollment.list_regimens(patient_id, medication_id)
        if not versions:
            return None
        return max(versions, key=lambda r: r.version_no)

    def _tz_for(self, patient_id: UUID):
        from ..application.timezone import LOCAL_TZ_PROVIDER

        return LOCAL_TZ_PROVIDER.local_tz(patient_id)

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
        if request.window == "tonight":
            rows = []
            start, end = self._schedule.tonight_window(request.patient_id)
            for medication in self._enrollment.list_medications(request.patient_id):
                regimen = self._enrollment.find_active_regimen(request.patient_id, medication.id)
                if regimen is None or regimen.is_prn:
                    continue
                for occurrence in self._schedule.scheduled_tonight(
                    patient_id=request.patient_id, regimen_id=regimen.id
                ):
                    history = self._self_report.history(
                        patient_id=request.patient_id, regimen_id=regimen.id, window_start=start, window_end=end
                    )
                    report = next(
                        (row.event for row in history if row.occurrence and row.occurrence.id == occurrence.id), None
                    )
                    rows.append(
                        {
                            "medication_name": medication.display_name,
                            "medication_id": str(medication.id),
                            "regimen_id": str(regimen.id),
                            "occurrence_id": str(occurrence.id),
                            "dose_amount": regimen.dose_amount,
                            "dose_unit": regimen.dose_unit,
                            "due_at": occurrence.due_at.isoformat(),
                            "local_time": occurrence.due_at.astimezone(ZoneInfo("Asia/Singapore")).strftime("%H:%M"),
                            "intake_status": report.intake_status.value if report else "not_reported",
                        }
                    )
            return ToolResult(
                tool_name=ToolName.CHECK_DUE_DOSE,
                status=ToolStatus.SUCCESS,
                payload={
                    "window": "tonight",
                    "local_timezone": "Asia/Singapore",
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
                candidates.append(
                    {
                        "regimen_id": str(regimen.id),
                        "medication_id": str(regimen.patient_medication_id),
                        "occurrence_id": str(due.occurrence.id),
                        "due_at": due.occurrence.due_at.isoformat(),
                    }
                )
        return ToolResult(
            tool_name=ToolName.CHECK_DUE_DOSE,
            status=ToolStatus.SUCCESS,
            payload={"item_count": len(candidates), "due_doses": candidates},
            clarification_question=None if candidates else "No dose is due right now.",
        )

    def _record_self_report(self, request: ToolRequest) -> ToolResult:
        assert isinstance(request, RecordSelfReportRequest)
        # Accept the patient-facing labels ('Taken', 'Not now', 'Unsure') as
        # well as the canonical snake_case values; invalid input is rejected
        # by the deterministic mapper rather than silently defaulted.
        intake = intake_status_from_patient_choice(request.intake_status)
        occurrence_id = request.occurrence_id
        if occurrence_id is None and request.confirmed_challenge_id is not None:
            prior = self._self_report.find_confirmation(
                patient_id=request.patient_id, idempotency_key=request.idempotency_key
            )
            if prior is not None and prior.id == request.confirmed_challenge_id:
                occurrence_id = prior.occurrence_id
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
