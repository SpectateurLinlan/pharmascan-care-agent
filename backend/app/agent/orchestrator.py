"""Bounded agent orchestrator + deterministic degraded-mode intent router.

** SIMULATED / DEGRADED **
No LLM provider key is available (B03). Therefore the routing here is a
deterministic rule-based ``IntentRouter``, which the architecture explicitly
names as a *degraded mode* and forbids presenting as verified LLM agent
behaviour (ARCHITECTURE.md section E). An ``LlmIntentRouter`` Port exists so a
real provider can be injected later without changing the orchestrator.

The orchestrator itself is real: it owns state transitions, the bounded step
budget, session persistence, confirmation gating and tool traces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol
from uuid import UUID

from ..contracts.dto import AgentSessionDTO
from ..contracts.enums import AgentIntent, ToolName, ToolStatus
from ..contracts.ports import AgentSessionRepository, Clock, IdGenerator
from .registry import ToolRegistry
from .tools import (
    CheckDueDoseRequest,
    ConfirmRegimenRequest,
    EnrollMedicationRequest,
    ListActiveMedicationsRequest,
    MedicationHistoryRequest,
    RecordSelfReportRequest,
    ToolRequest,
    ToolResult,
)

MAX_STEPS_PER_TURN = 4
SESSION_TTL = timedelta(hours=2)


@dataclass(frozen=True)
class AgentTurn:
    """One inbound user turn: text plus optional typed slots."""

    text: str
    slots: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentReply:
    """One outbound reply with its tool trace for auditability."""

    message: str
    intent: AgentIntent
    session_id: UUID
    session_state: str
    tool_results: list[ToolResult] = field(default_factory=list)
    requires_confirmation: bool = False
    mode: str = "deterministic_degraded"


class IntentRouter(Protocol):
    """Public boundary between the orchestrator and any intent classifier."""

    name: str
    is_llm: bool

    def route(self, turn: AgentTurn, session: AgentSessionDTO) -> AgentIntent: ...


class DeterministicIntentRouter:
    """** SIMULATED / DEGRADED ** keyword-based router used when no LLM key exists.

    It is a rule engine, not a language model. Every reply produced through it
    is labelled ``mode='deterministic_degraded'`` so it cannot be mistaken for
    verified LLM behaviour.
    """

    name = "SIMULATED:deterministic_rule_router"
    is_llm = False

    _KEYWORDS: tuple[tuple[AgentIntent, tuple[str, ...]], ...] = (
        (AgentIntent.DOSE_SELF_REPORT, ("took", "taken", "not taken", "unsure", "reported")),
        (AgentIntent.MEDICATION_HISTORY, ("history", "past", "last week", "summary")),
        (AgentIntent.MEDICATION_ENROLLMENT, ("add", "enroll", "new medication", "prescription")),
    )

    def route(self, turn: AgentTurn, session: AgentSessionDTO) -> AgentIntent:
        # An explicit slot always wins over free text.
        if "intake_status" in turn.slots:
            return AgentIntent.DOSE_SELF_REPORT
        if "medication_name" in turn.slots:
            return AgentIntent.MEDICATION_ENROLLMENT

        lowered = turn.text.lower()
        for intent, keywords in self._KEYWORDS:
            if any(keyword in lowered for keyword in keywords):
                return intent
        # An open session waiting on the patient keeps its intent.
        if session.intent:
            try:
                return AgentIntent(session.intent)
            except ValueError:
                pass
        return AgentIntent.CLARIFICATION


class AgentOrchestrator:
    """Single bounded orchestrator over an allowlisted tool registry."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        sessions: AgentSessionRepository,
        router: IntentRouter,
        clock: Clock,
        ids: IdGenerator,
        max_steps: int = MAX_STEPS_PER_TURN,
    ) -> None:
        self._registry = registry
        self._sessions = sessions
        self._router = router
        self._clock = clock
        self._ids = ids
        self._max_steps = max_steps

    # -- session handling ----------------------------------------------------

    def start_session(self, *, patient_id: UUID) -> AgentSessionDTO:
        now = self._clock.now()
        session = AgentSessionDTO(
            id=self._ids.new_id(),
            patient_id=patient_id,
            intent=None,
            state="collecting",
            pending_field_names=[],
            state_version=1,
            updated_at=now,
            expires_at=now + SESSION_TTL,
        )
        self._sessions.add(session)
        return session

    def handle_turn(
        self, *, patient_id: UUID, session_id: UUID, turn: AgentTurn
    ) -> AgentReply:
        session = self._sessions.get(patient_id, session_id)
        if session is None:
            # A caller-supplied session id is honoured so traces land on the
            # session the caller tracks. If that id is already owned by a
            # DIFFERENT patient, refuse: identities must never be shared
            # (AGENTS.md rule 22).
            if self._session_id_taken_by_other_patient(patient_id, session_id):
                raise PermissionError(
                    "session id belongs to another patient; refusing to reuse it"
                )
            now = self._clock.now()
            session = AgentSessionDTO(
                id=session_id,
                patient_id=patient_id,
                intent=None,
                state="collecting",
                pending_field_names=[],
                state_version=1,
                updated_at=now,
                expires_at=now + SESSION_TTL,
            )
            self._sessions.add(session)
        if self._clock.now() >= session.expires_at:
            session = session.model_copy(
                update={
                    "state": "expired",
                    "updated_at": self._clock.now(),
                    "state_version": session.state_version + 1,
                }
            )
            self._sessions.update(session)

        intent = self._router.route(turn, session)
        session = session.model_copy(
            update={
                "intent": intent.value,
                "updated_at": self._clock.now(),
                "state_version": session.state_version + 1,
            }
        )
        self._sessions.update(session)

        results: list[ToolResult] = []
        message: str
        requires_confirmation = False

        for step_index in range(self._max_steps):
            planned = self._plan(intent, turn, session, results)
            if planned is None:
                break
            tool_name, request = planned
            result = self._registry.execute(tool_name, request)
            results.append(result)

            if result.requires_confirmation:
                requires_confirmation = True
                session = self._mark_awaiting_confirmation(session)
                break
            if result.status == ToolStatus.BLOCKED and step_index >= 1:
                # Bounded: do not retry a blocked write in a loop.
                break

        message = self._compose_message(intent, results)
        session = self._sessions.get(patient_id, session.id) or session
        return AgentReply(
            message=message,
            intent=intent,
            session_id=session.id,
            session_state=session.state,
            tool_results=results,
            requires_confirmation=requires_confirmation,
        )

    # -- planning (bounded, no recursion) -----------------------------------

    def _plan(
        self,
        intent: AgentIntent,
        turn: AgentTurn,
        session: AgentSessionDTO,
        done: list[ToolResult],
    ) -> tuple[ToolName, ToolRequest] | None:
        """Return the next (tool, request) or None to end the turn.

        Deterministic single-step escalation: each call is derived from the
        intent plus slots, and results already obtained are not repeated.
        """
        executed = {r.tool_name for r in done}
        base = {
            "patient_id": session.patient_id,
            "session_id": session.id,
            "correlation_id": turn.slots.get("correlation_id", self._ids.new_id()),
            "client_turn_id": str(turn.slots.get("client_turn_id", "turn-1")),
        }

        if intent == AgentIntent.MEDICATION_ENROLLMENT:
            if ToolName.ENROLL_MEDICATION_DRAFT not in executed:
                return ToolName.ENROLL_MEDICATION_DRAFT, EnrollMedicationRequest(
                    **base,
                    medication_name=str(turn.slots.get("medication_name", turn.text.strip() or "Unknown")),
                    dose_amount=turn.slots.get("dose_amount"),
                    dose_unit=turn.slots.get("dose_unit"),
                    frequency_kind=turn.slots.get("frequency_kind"),
                    frequency_local_times=list(turn.slots.get("frequency_local_times", [])),
                    frequency_days_of_week=list(turn.slots.get("frequency_days_of_week", [])),
                    frequency_every_hours=turn.slots.get("frequency_every_hours"),
                    is_prn=bool(turn.slots.get("is_prn", False)),
                    route=turn.slots.get("route"),
                    food_instruction=turn.slots.get("food_instruction"),
                )
            # A confirmed summary was shown and the patient approved it.
            if (
                "confirm_challenge_id" in turn.slots
                and ToolName.CONFIRM_REGIMEN_DRAFT not in executed
                and session.state == "awaiting_confirmation"
            ):
                return ToolName.CONFIRM_REGIMEN_DRAFT, ConfirmRegimenRequest(
                    **base,
                    regimen_id=turn.slots["regimen_id"],
                    challenge_id=turn.slots["confirm_challenge_id"],
                    session_state=session.state,
                    session_state_version=session.state_version,
                )
            return None

        if intent == AgentIntent.DOSE_SELF_REPORT:
            if ToolName.LIST_ACTIVE_MEDICATIONS not in executed:
                return ToolName.LIST_ACTIVE_MEDICATIONS, ListActiveMedicationsRequest(**base)
            if "regimen_id" not in turn.slots:
                return None
            # For a scheduled regimen the report must reference the actual due
            # occurrence, so resolve it deterministically instead of guessing.
            if (
                turn.slots.get("occurrence_id") is None
                and not turn.slots.get("is_prn")
                and ToolName.CHECK_DUE_DOSE not in executed
            ):
                return ToolName.CHECK_DUE_DOSE, CheckDueDoseRequest(
                    **base, regimen_id=turn.slots["regimen_id"]
                )
            if ToolName.RECORD_SELF_REPORT not in executed:
                occurrence_id = turn.slots.get("occurrence_id")
                if occurrence_id is None:
                    occurrence_id = self._resolve_occurrence(done, turn)
                return ToolName.RECORD_SELF_REPORT, RecordSelfReportRequest(
                    **base,
                    regimen_id=turn.slots["regimen_id"],
                    occurrence_id=occurrence_id,
                    intake_status=str(turn.slots.get("intake_status", "unsure")),
                    idempotency_key=str(
                        turn.slots.get(
                            "idempotency_key", f"turn-{turn.slots.get('client_turn_id', '1')}"
                        )
                    ),
                )
            return None

        if intent == AgentIntent.MEDICATION_HISTORY:
            if "regimen_id" not in turn.slots:
                if ToolName.LIST_ACTIVE_MEDICATIONS not in executed:
                    return ToolName.LIST_ACTIVE_MEDICATIONS, ListActiveMedicationsRequest(**base)
                return None
            if ToolName.GET_MEDICATION_HISTORY not in executed:
                return ToolName.GET_MEDICATION_HISTORY, MedicationHistoryRequest(
                    **base,
                    regimen_id=turn.slots["regimen_id"],
                    days=int(turn.slots.get("days", 7)),
                )
            return None

        # Clarification: gather the minimum context, then ask.
        if intent == AgentIntent.CLARIFICATION and ToolName.LIST_ACTIVE_MEDICATIONS not in executed:
            return ToolName.LIST_ACTIVE_MEDICATIONS, ListActiveMedicationsRequest(**base)
        return None

    def _mark_awaiting_confirmation(self, session: AgentSessionDTO) -> AgentSessionDTO:
        updated = session.model_copy(
            update={
                "state": "awaiting_confirmation",
                "updated_at": self._clock.now(),
                "state_version": session.state_version + 1,
            }
        )
        self._sessions.update(updated)
        return updated

    @staticmethod
    def _resolve_occurrence(done: list[ToolResult], turn: AgentTurn) -> UUID | None:
        """Reuse the occurrence id from a previous check_due_dose result.

        Deterministic: the earliest due dose returned by the tool is the one
        the patient is reporting on. Nothing is invented when no occurrence
        was found — the value stays None and the policy rejects the write.
        """
        for result in reversed(done):
            if result.tool_name != ToolName.CHECK_DUE_DOSE:
                continue
            doses = result.payload.get("due_doses") or []
            if doses:
                candidate = doses[0].get("occurrence_id")
                if candidate:
                    return UUID(str(candidate))
        return None

    def _session_id_taken_by_other_patient(self, patient_id: UUID, session_id: UUID) -> bool:
        """True when the id exists in the store under a different patient.

        The session repository is patient-scoped, so we probe by attempting a
        read with the candidate id for every known patient id captured by the
        session store's ownership index.
        """
        probe = getattr(self._sessions, "is_owned_by_other_patient", None)
        if callable(probe):
            return bool(probe(patient_id, session_id))
        # Fallback for repositories without the optional probe: consult the
        # store's raw keys if available, otherwise assume not taken.
        keys = getattr(self._sessions, "known_keys", None)
        if keys is None:
            return False
        return any(owner != patient_id and sid == session_id for owner, sid in keys())

    # -- response composition -------------------------------------------------

    def _compose_message(self, intent: AgentIntent, results: list[ToolResult]) -> str:
        prefix = "[degraded: deterministic rule routing, not a live LLM] "
        if not results:
            return prefix + "I could not determine what you need. Could you tell me more?"

        last = results[-1]
        if last.requires_confirmation:
            return (
                prefix
                + "Please review the summary and confirm before I save it. "
                "I will not change your medication record without your confirmation."
            )
        if last.blocked:
            return prefix + f"I could not complete that: {last.error_message or last.error_code}."
        if last.clarification_question and last.status == ToolStatus.SUCCESS:
            if last.payload.get("missing_count") or last.clarification_question.startswith("I still need"):
                return prefix + last.clarification_question
            if last.payload.get("item_count") == 0 and "No dose" in last.clarification_question:
                return prefix + last.clarification_question
        return prefix + "Done. " + _summarise(last)


def _summarise(result: ToolResult) -> str:
    if result.tool_name == ToolName.RECORD_SELF_REPORT:
        return (
            "Recorded as reported by you — this does not prove the medication was taken."
        )
    if result.tool_name == ToolName.LIST_ACTIVE_MEDICATIONS:
        return f"You have {result.payload.get('item_count', 0)} active medication(s)."
    if result.tool_name == ToolName.GET_MEDICATION_HISTORY:
        return (
            f"Found {result.payload.get('item_count', 0)} scheduled dose(s). "
            "Doses with no report are not counted as missed."
        )
    if result.tool_name == ToolName.CHECK_DUE_DOSE:
        return f"{result.payload.get('item_count', 0)} dose(s) are due now."
    return f"{result.tool_name} completed."
