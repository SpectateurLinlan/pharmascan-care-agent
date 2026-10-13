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
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from ..contracts.dto import AgentSessionDTO
from ..contracts.enums import AgentIntent, ToolName, ToolStatus
from ..contracts.ports import AgentSessionRepository, Clock, IdGenerator
from ..domain.errors import NotFoundError
from .registry import ToolRegistry
from .tools import (
    CheckDueDoseRequest,
    ConfirmRegimenRequest,
    EnrollMedicationRequest,
    GetDoseStatusRequest,
    ListActiveMedicationsRequest,
    MedicationHistoryRequest,
    RecordSelfReportRequest,
    ToolRequest,
    ToolResult,
)

MAX_STEPS_PER_TURN = 4
SESSION_TTL = timedelta(hours=2)

#: Matches keyword occurrences at word boundaries so "past" does not fire
#: inside "pasta" and "add" does not fire inside "address". Multi-word phrases
#: ("did i take") still match because the boundary is only asserted at the
#: outer edges of the phrase.
_KEYWORD_PATTERN_CACHE: dict[str, object] = {}


def _mentions(haystack: str, keyword: str) -> bool:
    import re

    pattern = _KEYWORD_PATTERN_CACHE.get(keyword)
    if pattern is None:
        pattern = re.compile(rf"(?<!\w){re.escape(keyword)}(?!\w)")
        _KEYWORD_PATTERN_CACHE[keyword] = pattern
    return bool(pattern.search(haystack))


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
        # A "did I take it / have I taken it" question is a READ, not a report.
        # It must be matched before the self-report keywords, otherwise the
        # word "taken" would route it into a write path.
        (
            AgentIntent.DOSE_STATUS_QUERY,
            (
                "have i taken",
                "have i had",
                "did i take",
                "did i already take",
                "did i miss",
                "have i missed",
                "should i have taken",
                "is my dose recorded",
                "did i record",
                "did i log",
            ),
        ),
        (AgentIntent.DOSE_SELF_REPORT, ("took", "taken", "not taken", "unsure", "reported")),
        (AgentIntent.MEDICATION_HISTORY, ("history", "past", "last week", "summary")),
        (AgentIntent.MEDICATION_ENROLLMENT, ("add", "enroll", "new medication", "prescription")),
    )

    #: Filler removed before a question is treated as a medication name. These
    #: are stripped, never guessed against: if nothing remains, the agent asks
    #: which medication rather than matching an arbitrary one.
    _QUERY_FILLERS: tuple[str, ...] = (
        "have i taken",
        "have i had",
        "did i take",
        "did i already take",
        "did i miss",
        "have i missed",
        "should i have taken",
        "is my dose recorded",
        "did i record",
        "did i log",
        "my",
        "the",
        "today",
        "tonight",
        "this morning",
        "this evening",
        "yet",
        "already",
        "please",
        "?",
        ".",
        ",",
    )

    def route(self, turn: AgentTurn, session: AgentSessionDTO) -> AgentIntent:
        # An explicit slot always wins over free text.
        if "intake_status" in turn.slots:
            return AgentIntent.DOSE_SELF_REPORT
        if "medication_name" in turn.slots and "ask_status" not in turn.slots:
            return AgentIntent.MEDICATION_ENROLLMENT

        lowered = turn.text.lower()
        for intent, keywords in self._KEYWORDS:
            if any(_mentions(lowered, keyword) for keyword in keywords):
                return intent
        # Free text never inherits a previous intent. A follow-up that belongs
        # to an open flow (confirming a summary, supplying a missing field) is
        # always expressed with an explicit slot, which is handled above — so
        # an unrecognised sentence must fall through to clarification rather
        # than being answered with whichever tool ran last. This is exactly how
        # "What is the capital of France?" used to be answered with dose data.
        return AgentIntent.CLARIFICATION

    #: Words that look like a name but carry no identity. Returning one of
    #: these would match an arbitrary medication, so they are treated as "no
    #: medication named" and the agent asks instead.
    _NON_NAMES: frozenset[str] = frozenset(
        {"it", "that", "this", "them", "those", "the", "my", "mine", "one", "any"}
    )

    @classmethod
    def extract_medication_name(cls, text: str) -> str:
        """Strip question filler from a status question to isolate the name.

        Deterministic and conservative: only known filler phrases are removed.
        If nothing legible remains the caller receives an empty string and must
        ask a clarifying question instead of matching some arbitrary record.
        """
        working = text.strip()
        lowered = working.lower()
        # Remove filler phrases longest-first so "have i taken" is consumed
        # before the shorter "taken".
        for filler in sorted(cls._QUERY_FILLERS, key=len, reverse=True):
            start = 0
            while True:
                index = lowered.find(filler, start)
                if index == -1:
                    break
                working = working[:index] + " " + working[index + len(filler) :]
                lowered = working.lower()
                start = index + 1
        cleaned = " ".join(working.split()).strip()
        # A pronoun or determiner is not a medication name: ask rather than
        # resolve it against whichever record happens to exist.
        if cleaned.lower() in cls._NON_NAMES:
            return ""
        return cleaned


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

    def get_session(self, *, patient_id: UUID, session_id: UUID) -> AgentSessionDTO | None:
        """Patient-scoped session read. Returns None when absent or foreign."""
        session = self._sessions.get(patient_id, session_id)
        if session is not None and self._clock.now() >= session.expires_at:
            session = session.model_copy(
                update={
                    "state": "expired",
                    "updated_at": self._clock.now(),
                    "state_version": session.state_version + 1,
                }
            )
            self._sessions.update(session)
        return session

    def await_confirmation(self, *, patient_id: UUID, session_id: UUID) -> AgentSessionDTO:
        """Move a live session into ``awaiting_confirmation``.

        Called after a confirmation summary has been displayed. The returned
        ``state_version`` is the one the client must echo back when activating,
        so a stale tab cannot confirm a summary it never saw.
        """
        session = self._sessions.get(patient_id, session_id)
        if session is None:
            raise NotFoundError(f"Agent session {session_id} not found for this patient")
        return self._mark_awaiting_confirmation(session)

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

    def _router_medication_name(self, turn: AgentTurn) -> str:
        """Ask the router to isolate a medication name, if it can.

        A real LLM router would extract this as a typed slot; the deterministic
        router exposes ``extract_medication_name``. When the router cannot do
        it, an empty string is returned and the caller asks for clarification
        rather than guessing.
        """
        extractor = getattr(self._router, "extract_medication_name", None)
        if not callable(extractor):
            return ""
        return str(extractor(turn.text) or "")

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

        if intent == AgentIntent.DOSE_STATUS_QUERY:
            # A read-only status question. The medication name comes from an
            # explicit slot if present; otherwise filler is stripped from the
            # question itself. If nothing legible remains the request is not
            # attempted at all — the agent asks instead of matching an
            # arbitrary medication (no plausible-but-wrong answers).
            if ToolName.GET_DOSE_STATUS not in executed:
                explicit = turn.slots.get("medication_name") or turn.slots.get(
                    "query_medication_name"
                )
                name = str(explicit).strip() if explicit else self._router_medication_name(turn)
                if not name:
                    return None
                return ToolName.GET_DOSE_STATUS, GetDoseStatusRequest(
                    **base, medication_name=name, day_offset=0
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

        # Clarification: state the degraded capability and ask, but do not
        # fetch medication data for a question that is not about medication —
        # that would produce a plausible-but-irrelevant answer.
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
            if intent == AgentIntent.DOSE_STATUS_QUERY:
                return prefix + (
                    "I can look up what you have already reported for a medication, "
                    "but I could not tell which medication you mean. "
                    "Tell me the name, for example: \u201cHave I taken Amlodipine today?\u201d "
                    "You can also open Today to see a due dose, or Medication List for your records."
                )
            if intent == AgentIntent.CLARIFICATION:
                return prefix + (
                    "I can only help with a few things right now: add or review a "
                    "medication, record whether you took a dose, check what you "
                    "reported today, or show your dose history. I cannot answer "
                    "general medical or unrelated questions in this build. "
                    "Which of those would you like?"
                )
            return prefix + "I could not determine what you need. Could you tell me more?"

        last = results[-1]
        if last.requires_confirmation:
            return (
                prefix
                + "Please review the summary and confirm before I save it. "
                "I will not change your medication record without your confirmation."
            )
        if last.blocked:
            # An unresolvable medication is a clarification, not a crash: state
            # the limitation and offer the executable next step.
            if last.tool_name == ToolName.GET_DOSE_STATUS and last.error_code == "NOT_FOUND":
                return prefix + (last.error_message or "I could not find that medication.")
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
    if result.tool_name == ToolName.GET_DOSE_STATUS:
        return _describe_dose_status(result)
    return f"{result.tool_name} completed."


def _describe_dose_status(result: ToolResult) -> str:
    """Render a dose-status answer without ever asserting ingestion.

    Absence of a report is stated as "no confirmed record", never as a missed
    dose. A reported "taken" is attributed to the patient, not to the system.
    """
    payload = result.payload
    name = payload.get("medication_name")
    if payload.get("resolution") == "unknown_medication":
        return result.error_message or "I could not find that medication in your list."
    if payload.get("resolution") == "no_regimen" or not payload.get("reported"):
        if not payload.get("reported"):
            return (
                f"No confirmed dose record for {name or 'that medication'} today. "
                "That is not the same as a missed dose, and I cannot tell whether "
                "you took it."
            )
    status = payload.get("intake_status")
    reported_at = payload.get("reported_at")
    when = _local_time_label(reported_at)
    if status == "reported_taken":
        return (
            f"You reported taking {name} today{when}."
            " This is your own report and does not prove the medicine was taken."
        )
    if status == "reported_not_taken":
        return f"You reported not taking {name} today{when}."
    if status == "unsure":
        return (
            f"You reported being unsure whether you took {name} today{when}. "
            "I will not guess — you can check again or record it once you know."
        )
    return f"No confirmed dose record for {name or 'that medication'} today."


def _local_time_label(iso_timestamp: object) -> str:
    """Best-effort local-time suffix; display only, never a schedule decision."""
    if not isinstance(iso_timestamp, str) or not iso_timestamp:
        return ""
    try:
        from datetime import UTC
        from zoneinfo import ZoneInfo

        moment = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        local = moment.astimezone(ZoneInfo("Asia/Singapore"))
        _ = UTC  # keep the import meaningful for linters
        return f" at {local.strftime('%H:%M')}"
    except (ValueError, TypeError):
        return ""
