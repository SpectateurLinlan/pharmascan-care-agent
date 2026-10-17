"""Model arguments never include identity or confirmation/write credentials."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..application.enrollment import MedicationEnrollmentService
from ..application.evidence_enrollment import EvidenceEnrollmentService
from ..application.long_term import LongTermCareService
from ..application.medication_understanding import MedicationUnderstandingService
from ..application.observations import ObservationService
from ..application.visual_check import VisualCheckService
from ..contracts.chat_photo import PHOTO_READ_TOOLS
from ..contracts.enums import AgentIntent, ToolName, ToolStatus
from ..contracts.long_term import CareReview
from ..contracts.observations import HealthNoteReview
from ..contracts.ports import Clock
from ..contracts.visual_check import VisualCheckRequest
from ..domain.errors import ProviderUnavailableError, ValidationError
from .long_term_tools import CARE_SPECS, execute_care_tool
from .orchestrator import AgentOrchestrator, AgentReply, AgentTurn
from .registry import ToolRegistry
from .tools import (
    CheckDueDoseRequest,
    CreateReminderRequest,
    GetDoseStatusRequest,
    ListActiveMedicationsRequest,
    MedicationHistoryRequest,
    ToolRequest,
    ToolResult,
)


class Arguments(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Empty(Arguments):
    pass


class Schedule(Arguments):
    window: Literal["due", "tonight", "today"] = "due"
    regimen_id: UUID | None = None


class Status(Arguments):
    medication_name: str | None = Field(default=None, min_length=1, max_length=160)
    medication_id: UUID | None = None
    occurrence_id: UUID | None = None


class History(Arguments):
    regimen_id: UUID
    days: int = Field(default=7, ge=1, le=30)


class Understanding(Arguments):
    medication_id: UUID | None = None
    medication_name: str | None = Field(default=None, min_length=1, max_length=160)
    question: Literal["general_use", "personal_instructions", "personal_reason"] = "general_use"


class Prepare(Arguments):
    regimen_id: UUID | None = None
    occurrence_id: UUID | None = None
    intake_status: Literal["taken", "not_taken"] = "taken"


class Reminder(Arguments):
    occurrence_id: UUID
    minutes: int = Field(ge=1, le=1440)


class ImageCheck(Arguments):
    regimen_id: UUID | None = None


SPECS = MappingProxyType(
    {
        **CARE_SPECS,
        "get_medication_understanding": (
            Understanding,
            "Required for what is this medicine for / how should I take it / why prescribed. "
            "Read patient-reviewed identity and current instructions; general uses require reliably matched "
            "openFDA evidence. Never invent form, route, indication, citations or dose. "
            "Use personal_instructions for personal dosing; personal_reason never proves the doctor's reason.",
        ),
        "reconcile_medication_sources": (
            Empty,
            "Read the verified current enrollment task, linked product/source evidence, "
            "missing instructions and conflicts. "
            "Ask for a label or clarification. Never activate, overwrite or invent instructions.",
        ),
        "prepare_health_observation": (
            Empty,
            "Offer review of the patient's own feeling/symptom description. "
            "Never diagnose, infer a drug cause or save before explicit human confirmation.",
        ),
        "check_medication_image": (
            ImageCheck,
            "Request the consented camera/upload workflow. Requires a real image; never claim a match before Stage2.",
        ),
        "list_active_medications": (Empty, "Read reviewed active medication names and references."),
        "check_due_dose": (
            Schedule,
            "Read named medicines, amounts and times: due now, all today, or tonight. "
            "Use today for today's plan; never prescribe.",
        ),
        "get_dose_status": (
            Status,
            "Read self-reported state. Use verified session references for it; no report is not missed.",
        ),
        "get_medication_history": (History, "Read dose history for a verified medication reference."),
        "prepare_self_report": (
            Prepare,
            "Only for an explicit patient report. Create human confirmation, never a dose event. "
            "Uncertainty is a read.",
        ),
        "create_reminder": (
            Reminder,
            "Save only an explicitly requested delay for an existing occurrence; never change regimen.",
        ),
    }
)


def model_tool_schemas(*, photo_only: bool = False) -> list[dict[str, object]]:
    return [
        {"type": "function", "name": name, "description": description, "parameters": schema.model_json_schema()}
        for name, (schema, description) in SPECS.items()
        if not photo_only or name in PHOTO_READ_TOOLS
    ]


@dataclass(frozen=True)
class ExecutedTool:
    data: dict[str, object]
    intent: AgentIntent
    results: list[ToolResult]
    prepared_reply: AgentReply | None = None
    visual_request: VisualCheckRequest | None = None
    health_review: HealthNoteReview | None = None
    care_review: CareReview | None = None


class ModelTools:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        fallback: AgentOrchestrator,
        visual_check: VisualCheckService | None = None,
        enrollment: MedicationEnrollmentService | None = None,
        observations: ObservationService | None = None,
        evidence_enrollment: EvidenceEnrollmentService | None = None,
        long_term: LongTermCareService | None = None,
        medication_understanding: MedicationUnderstandingService | None = None,
        timezone: str = "Asia/Singapore",
        clock: Clock | None = None,
    ):
        self._registry, self._fallback = registry, fallback
        self._visual, self._enrollment = visual_check, enrollment
        self._observations = observations
        self._evidence = evidence_enrollment
        self._long_term, self._timezone = long_term, timezone
        self._understanding = medication_understanding
        self._clock = clock

    def context_metadata(self) -> dict[str, str | None]:
        """Injected current time and patient zone; no owner or credential data."""
        return {"timezone": self._timezone, "current_time": self._clock.now().isoformat() if self._clock else None}

    def evidence_context(self, patient_id: UUID, task_id: UUID) -> dict[str, object]:
        if self._evidence is None:
            raise ProviderUnavailableError("Evidence task unavailable")
        task = self._evidence.get(patient_id, task_id)
        sources = self._evidence.sources(patient_id, task_id)
        excerpts = []
        for source in sources[:10]:
            evidence = source.extraction_evidence
            candidates = evidence.candidates[:1] if evidence else []
            excerpts.append(
                {
                    "source_id": str(source.id),
                    "source_kind": source.source_kind.value,
                    "review_status": source.review_status.value,
                    "untrusted_printed_lines": [
                        line[:240] for candidate in candidates for line in candidate.product.source_lines[:4]
                    ],
                    "untrusted_printed_directions": [
                        candidate.regimen_evidence.directions.line[:400]
                        for candidate in candidates
                        if candidate.regimen_evidence.directions
                    ],
                    "untrusted_instruction_parts": [
                        {
                            key: value[:400] if isinstance(value, str) else value
                            for key, value in candidate.regimen_evidence.instructions.model_dump(mode="json").items()
                        }
                        for candidate in candidates
                        if candidate.regimen_evidence.instructions
                    ],
                    "label_kind": evidence.label_kind if evidence else None,
                }
            )
        return {
            "task_id": str(task.id),
            "medication_id": str(task.medication_id),
            "status": task.status,
            "source_ids": [str(key) for key in task.source_ids],
            "source_evidence": excerpts,
            "product": task.product.model_dump(mode="json"),
            "missing": task.missing,
            "product_information_missing": task.product_missing,
            "conflicts": task.conflicts,
            "reviewable_proposal": task.suggested_regimen.model_dump(mode="json") if task.suggested_regimen else None,
            "existing_product_candidates": [str(key) for key in task.possible_duplicate_ids],
        }

    def execute(
        self,
        *,
        name: str,
        arguments: dict[str, object],
        patient_id: UUID,
        session_id: UUID,
        correlation_id: UUID,
        client_turn_id: str,
        turn: AgentTurn,
    ) -> ExecutedTool:
        if name not in SPECS:
            raise ValidationError("Unknown model tool")
        if turn.photo_context is not None and name not in PHOTO_READ_TOOLS:
            raise ValidationError(
                "Photo evidence cannot authorize record actions; send a separate explicit text message"
            )
        params = SPECS[name][0].model_validate(arguments).model_dump(exclude_none=True)
        if name == "get_medication_understanding":
            if self._understanding is None:
                raise ProviderUnavailableError("Medication knowledge unavailable")
            if not params.get("medication_id") and not params.get("medication_name"):
                session = self._fallback.get_session(patient_id=patient_id, session_id=session_id)
                if session and session.context.referenced_medication_id:
                    params["medication_id"] = session.context.referenced_medication_id
            understanding = self._understanding.explain(
                patient_id=patient_id, **params, language=turn.language, timezone=self._timezone
            )
            payload = {
                "action": name,
                "item_count": 1,
                "state": "medication_understanding",
                **understanding.model_dump(mode="json"),
            }
            # Existing grouped read audit contract also covers medication education;
            # no new DB tool-name constraint, patient identity or write authority.
            unavailable = understanding.general_knowledge and understanding.general_knowledge.status == "unavailable"
            result = ToolResult(
                tool_name=ToolName.GET_LONG_TERM_CARE,
                status=ToolStatus.BLOCKED if unavailable else ToolStatus.SUCCESS,
                payload=payload,
                error_code="PROVIDER_UNAVAILABLE" if unavailable else None,
            )
            self._registry.record_care_result(
                ToolRequest(
                    patient_id=patient_id,
                    session_id=session_id,
                    correlation_id=correlation_id,
                    client_turn_id=client_turn_id,
                ),
                result,
            )
            return ExecutedTool(data=payload, intent=AgentIntent.CLARIFICATION, results=[result])
        if name in CARE_SPECS:
            if self._long_term is None:
                raise ProviderUnavailableError("Long-term care unavailable")
            output = execute_care_tool(
                self._long_term,
                name=name,
                arguments=arguments,
                patient_id=patient_id,
                session_id=session_id,
                turn_id=client_turn_id,
                text=turn.text,
                language=turn.language,
                timezone=self._timezone,
            )
            result = ToolResult(
                tool_name=ToolName.PREPARE_CARE_ACTION if output.review else ToolName.GET_LONG_TERM_CARE,
                status=ToolStatus.SUCCESS,
                payload={
                    "item_count": 1,
                    "patient_safe_summary": output.data["patient_safe_summary"],
                    "action": name,
                    **(
                        {"care_clarification": output.data["care_clarification"]}
                        if "care_clarification" in output.data
                        else {}
                    ),
                },
            )
            self._registry.record_care_result(
                ToolRequest(
                    patient_id=patient_id,
                    session_id=session_id,
                    correlation_id=correlation_id,
                    client_turn_id=client_turn_id,
                ),
                result,
            )
            return ExecutedTool(
                data=output.data, intent=AgentIntent.CLARIFICATION, results=[result], care_review=output.review
            )
        if name == "reconcile_medication_sources":
            session = self._fallback.get_session(patient_id=patient_id, session_id=session_id)
            task_id = turn.slots.get("evidence_task_id") or (session.context.enrollment_task_id if session else None)
            if not task_id or self._evidence is None:
                raise ValidationError("Choose an owned enrollment task first")
            try:
                parsed_task_id = UUID(str(task_id))
            except (ValueError, TypeError) as exc:
                raise ValidationError("Choose a valid owned enrollment task") from exc
            task = self._evidence.get(patient_id, parsed_task_id)
            summary = self._evidence.summary(task, turn.language)
            return ExecutedTool(
                data={
                    **self.evidence_context(patient_id, task.id),
                    "product": task.product.model_dump(mode="json"),
                    "patient_safe_summary": summary,
                },
                intent=AgentIntent.MEDICATION_ENROLLMENT,
                results=[
                    ToolResult(
                        tool_name=ToolName.RECONCILE_MEDICATION_SOURCES,
                        status=ToolStatus.SUCCESS,
                        payload={"patient_safe_summary": summary, "evidence_task_id": str(task.id)},
                    )
                ],
            )
        if name == "prepare_health_observation":
            if self._observations is None:
                raise ProviderUnavailableError("Health notes unavailable")
            review = self._observations.prepare_review(turn.text)
            return ExecutedTool(
                data=review.model_dump(mode="json"), intent=AgentIntent.CLARIFICATION, results=[], health_review=review
            )
        base = {
            "patient_id": patient_id,
            "session_id": session_id,
            "correlation_id": correlation_id,
            "client_turn_id": client_turn_id,
        }
        if name == "check_medication_image":
            if self._visual is None or self._enrollment is None:
                raise ProviderUnavailableError("Visual check unavailable")
            action = self._visual.prepare_upload(
                patient_id=patient_id, regimen_id=params.get("regimen_id"), enrollment=self._enrollment
            )
            return ExecutedTool(
                data=action.model_dump(mode="json"), intent=AgentIntent.CLARIFICATION, results=[], visual_request=action
            )
        if name == "prepare_self_report":
            import re

            text = turn.text.lower()
            if any(word in text for word in ["not sure", "unsure", "whether", "不确定", "不记得"]):
                raise ValidationError("Uncertainty must use a read-only tool")
            session = self._fallback.get_session(patient_id=patient_id, session_id=session_id)
            clarified = session.context.awaiting_clarification if session else None
            explicit = bool(
                re.search(r"^\s*i (?:already )?(?:took|did not take|didn't take)\b", text)
            ) or text.startswith(("我吃了", "我已经吃了", "我没吃"))
            if not explicit and not (clarified and clarified.requested_intake_status):
                raise ValidationError("An explicit self-report is required")
            listed = self._registry.execute(ToolName.LIST_ACTIVE_MEDICATIONS, ListActiveMedicationsRequest(**base))
            medications = listed.payload.get("medications", [])
            if len(medications) > 1:
                known = session.context.referenced_regimen_id if session else None
                named = [row for row in medications if row["display_name"].lower() in text]
                allowed = {row["regimen_id"] for row in named}
                if known and (re.search(r"\bit\b", text) or "这" in text):
                    allowed.add(str(known))
                if clarified:
                    choice = text.strip().removeprefix("the ").strip(" .?!")
                    choices = [row for row in clarified.candidates if choice and choice in row.display_name.lower()]
                    if len(choices) == 1:
                        allowed.add(str(choices[0].regimen_id))
                if not params.get("regimen_id") or str(params["regimen_id"]) not in allowed:
                    reply = self._fallback.handle_turn(patient_id=patient_id, session_id=session_id, turn=turn)
                    return ExecutedTool(
                        data={"requires_clarification": True, "message": reply.message},
                        intent=AgentIntent.DOSE_SELF_REPORT,
                        results=reply.tool_results,
                        prepared_reply=reply,
                    )
            expected = (
                ("not_taken" if any(word in text for word in ["did not take", "didn't take", "我没吃"]) else "taken")
                if explicit
                else clarified.requested_intake_status
            )
            if params["intake_status"] != expected:
                raise ValidationError("Self-report choice differs from patient's explicit report")
            # Existing orchestrator owns challenge/session version/idempotency.
            import hashlib

            slots = {
                **params,
                "client_turn_id": client_turn_id,
                "idempotency_key": "llm-" + hashlib.sha256(f"{session_id}:{client_turn_id}".encode()).hexdigest(),
            }
            reply = self._fallback.handle_turn(
                patient_id=patient_id,
                session_id=session_id,
                turn=AgentTurn(text=turn.text, language=turn.language, slots=slots),
            )
            return ExecutedTool(
                data={
                    "requires_confirmation": reply.requires_confirmation,
                    "pending_report": reply.pending_report.model_dump(mode="json") if reply.pending_report else None,
                    "message": reply.message,
                },
                intent=AgentIntent.DOSE_SELF_REPORT,
                results=reply.tool_results,
                prepared_reply=reply,
            )
        mapping = {
            "list_active_medications": (
                ToolName.LIST_ACTIVE_MEDICATIONS,
                ListActiveMedicationsRequest,
                AgentIntent.CLARIFICATION,
            ),
            "check_due_dose": (ToolName.CHECK_DUE_DOSE, CheckDueDoseRequest, AgentIntent.CLARIFICATION),
            "get_dose_status": (ToolName.GET_DOSE_STATUS, GetDoseStatusRequest, AgentIntent.DOSE_STATUS_QUERY),
            "get_medication_history": (
                ToolName.GET_MEDICATION_HISTORY,
                MedicationHistoryRequest,
                AgentIntent.MEDICATION_HISTORY,
            ),
            "create_reminder": (ToolName.CREATE_REMINDER, CreateReminderRequest, AgentIntent.REMINDER),
        }
        if name == "create_reminder":
            import re

            match = re.search(r"\bin (\d+) (?:minutes?|min)\b", turn.text.lower())
            if not match or int(match[1]) != params["minutes"]:
                raise ValidationError("Confirm an explicit reminder delay")
        tool, request_type, intent = mapping[name]
        result = self._registry.execute(tool, request_type(**base, **params))
        return ExecutedTool(
            data=result.model_dump(mode="json", exclude={"error_message"}), intent=intent, results=[result]
        )
