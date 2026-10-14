"""``dose_status_query`` — "Have I taken X today?" (Session 3A item 3).

This is a **read-only** product capability. The defect it repairs is real and
was observed in the running product: the degraded assistant answered *"Have I
taken Amlodipine today?"* by calling ``list_active_medications`` and replying
*"You have 1 active medication(s)."* — a plausible but irrelevant answer to a
direct question about a dose.

The tests here exercise the real orchestrator, the real tool registry, real
policy and real in-memory repositories. Only the intent router is the
deterministic degraded rule engine (SIMULATED, no LLM key).

Covered (all six required by the work item):
1. active medication + reported taken today
2. active medication + reported unsure today
3. active medication + no report at all
4. unknown medication
5. historical / discontinued medication
6. cross-patient access refused

Plus the general honesty rules: a status question never writes an event, and an
unrelated question never inherits the previous turn's intent.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from app.agent.orchestrator import (
    AgentOrchestrator,
    AgentTurn,
    DeterministicIntentRouter,
)
from app.agent.registry import ToolRegistry
from app.agent.tools import GetDoseStatusRequest
from app.contracts.dto import (
    AgentSessionDTO,
    DoseEventInput,
    FrequencyRuleDTO,
    RegimenDraftInput,
)
from app.contracts.enums import AgentIntent, IntakeStatus, RegimenState, ToolName, ToolStatus

PATIENT = UUID(int=100)
OTHER_PATIENT = UUID(int=200)


@pytest.fixture()
def agent(wired):
    registry = ToolRegistry(
        enrollment=wired.enrollment,
        schedule=wired.schedule,
        self_report=wired.self_report,
        traces=wired.traces,
        clock=wired.clock,
        ids=wired.ids,
    )
    orchestrator = AgentOrchestrator(
        registry=registry,
        sessions=wired.sessions,
        router=DeterministicIntentRouter(),
        clock=wired.clock,
        ids=wired.ids,
    )
    return orchestrator, registry


def _base(patient_id: UUID, session_id: UUID, turn: int = 1) -> dict:
    return {
        "patient_id": patient_id,
        "session_id": session_id,
        "correlation_id": UUID(int=900 + turn),
        "client_turn_id": f"turn-{turn}",
    }


def _activate(wired, *, name="Amlodipine 5mg", times=("08:00",), patient_id=PATIENT):
    """Enroll + activate a scheduled regimen through the real services."""
    result = wired.enrollment.enroll_draft(
        patient_id=patient_id,
        draft=RegimenDraftInput(
            medication_name=name,
            dose_amount=1,
            dose_unit="tablet",
            frequency_rule=FrequencyRuleDTO(kind="daily", local_times=list(times)),
        ),
    )
    challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=patient_id,
        regimen_id=result.regimen.id,
        session_id=UUID(int=500),
        session_state_version=1,
    )
    wired.enrollment.confirm_challenge(patient_id=patient_id, challenge_id=challenge.id)
    wired.enrollment.review_source_fields(
        patient_id=patient_id, source_id=result.regimen.source_id
    )
    activated = wired.enrollment.activate_regimen(
        patient_id=patient_id,
        regimen_id=result.regimen.id,
        challenge_id=challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=1,
    )
    return result, activated


def _report(wired, regimen_id, status: IntakeStatus, *, key: str, patient_id=PATIENT):
    """Report against the current due occurrence through the real lifecycle.

    The database requires a confirmed, unconsumed ``record_self_report``
    challenge for every dose event, so the test issues and confirms one exactly
    as the transport does before recording.
    """
    wired.schedule.materialize(patient_id=patient_id, regimen_id=regimen_id, days=2)
    due = wired.schedule.find_due(patient_id=patient_id, regimen_id=regimen_id)
    assert due.occurrence is not None, "test setup: a dose must be due to report on"
    session_id = UUID(int=800)
    wired.sessions.add(
        AgentSessionDTO(
            id=session_id,
            patient_id=patient_id,
            intent="record_self_report",
            state="awaiting_confirmation",
            state_version=1,
            updated_at=wired.clock.now(),
            expires_at=wired.clock.now() + timedelta(hours=1),
        )
    )
    challenge = wired.self_report.request_confirmation(
        patient_id=patient_id,
        regimen_id=regimen_id,
        occurrence_id=due.occurrence.id,
        intake_status=status,
        idempotency_key=key,
        session_id=session_id,
        session_state_version=1,
    )
    wired.self_report.confirm_challenge(
        patient_id=patient_id, challenge_id=challenge.challenge.id
    )
    return wired.self_report.report(
        patient_id=patient_id,
        payload=DoseEventInput(
            regimen_id=regimen_id,
            occurrence_id=due.occurrence.id,
            intake_status=status,
            event_time=wired.clock.now(),
            idempotency_key=key,
        ),
        challenge_id=challenge.challenge.id,
    )


# --- 1. active medication + reported taken today ----------------------------


def test_active_medication_reported_taken_today(agent, wired):
    orchestrator, _registry = agent
    _result, activated = _activate(wired)
    wired.clock.advance(hours=10)  # past today's 08:00 SG dose
    _report(wired, activated.regimen.id, IntakeStatus.REPORTED_TAKEN, key="taken-1")

    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=1),
        turn=AgentTurn(text="Have I taken Amlodipine today?"),
    )

    assert reply.intent == AgentIntent.DOSE_STATUS_QUERY
    last = reply.tool_results[-1]
    assert last.tool_name == ToolName.GET_DOSE_STATUS
    assert last.status == ToolStatus.SUCCESS
    assert last.payload["intake_status"] == "reported_taken"
    assert last.payload["reported"] is True
    assert last.payload["medication_name"] == "Amlodipine 5mg"
    # The confirmation must be attributed to the patient, not to the system.
    assert "reported" in reply.message.lower()
    assert "does not prove" in reply.message
    # And it must not have leaked into the wrong answer.
    assert "active medication" not in reply.message


def test_reported_status_includes_a_local_time(agent, wired):
    orchestrator, _registry = agent
    _result, activated = _activate(wired)
    wired.clock.advance(hours=10)
    _report(wired, activated.regimen.id, IntakeStatus.REPORTED_TAKEN, key="taken-time")

    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=2),
        turn=AgentTurn(text="Did I take my Amlodipine?"),
    )
    assert reply.intent == AgentIntent.DOSE_STATUS_QUERY
    # 2026-10-13T09:00Z == 17:00 Asia/Singapore.
    assert "17:00" in reply.message


# --- 2. active medication + reported unsure today ---------------------------


def test_active_medication_reported_unsure_today(agent, wired):
    orchestrator, _registry = agent
    _result, activated = _activate(wired)
    wired.clock.advance(hours=10)
    _report(wired, activated.regimen.id, IntakeStatus.UNSURE, key="unsure-1")

    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=3),
        turn=AgentTurn(text="Have I taken Amlodipine today?"),
    )

    last = reply.tool_results[-1]
    assert last.status == ToolStatus.SUCCESS
    assert last.payload["intake_status"] == "unsure"
    assert "unsure" in reply.message.lower()
    # The agent must not resolve the uncertainty for the patient.
    assert "missed" not in reply.message.lower()
    assert "does not prove" not in reply.message


def test_unsure_is_never_converted_to_missed_or_taken(agent, wired):
    """Policy guard: an "unsure" report keeps its own status verbatim."""
    orchestrator, _registry = agent
    _result, activated = _activate(wired)
    wired.clock.advance(hours=10)
    _report(wired, activated.regimen.id, IntakeStatus.UNSURE, key="unsure-2")

    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=4),
        turn=AgentTurn(text="Have I taken Amlodipine yet?"),
    )
    assert reply.tool_results[-1].payload["intake_status"] == IntakeStatus.UNSURE.value


def test_reported_not_taken_is_reported_verbatim(agent, wired):
    orchestrator, _registry = agent
    _result, activated = _activate(wired)
    wired.clock.advance(hours=10)
    _report(wired, activated.regimen.id, IntakeStatus.REPORTED_NOT_TAKEN, key="not-taken-1")

    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=5),
        turn=AgentTurn(text="Have I taken Amlodipine today?"),
    )
    last = reply.tool_results[-1]
    assert last.payload["intake_status"] == "reported_not_taken"
    assert "not taking" in reply.message.lower()


# --- 3. active medication + no report --------------------------------------


def test_active_medication_with_no_report_says_no_confirmed_record(agent, wired):
    orchestrator, _registry = agent
    _result, activated = _activate(wired)
    wired.clock.advance(hours=10)  # the dose is due, but nothing was reported

    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=6),
        turn=AgentTurn(text="Have I taken Amlodipine today?"),
    )

    last = reply.tool_results[-1]
    assert last.tool_name == ToolName.GET_DOSE_STATUS
    assert last.status == ToolStatus.SUCCESS
    assert last.payload["reported"] is False
    assert last.payload["intake_status"] == "no_report"
    # The critical wording: absence of a report is NOT a missed dose.
    assert "no confirmed dose record" in reply.message.lower()
    assert "not the same as a missed dose" in reply.message.lower()
    assert last.payload["note"].startswith("No confirmed dose record")


def test_no_report_on_a_not_yet_due_dose_is_still_no_report(agent, wired):
    """Before the dose is due, the answer is still "no record", never "missed"."""
    orchestrator, _registry = agent
    _result, activated = _activate(wired)
    # Clock has NOT advanced: today's 08:00 SG dose is still ahead.
    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=7),
        turn=AgentTurn(text="Have I taken Amlodipine today?"),
    )
    last = reply.tool_results[-1]
    assert last.payload["reported"] is False
    assert "missed" in reply.message.lower()  # only inside the "not a missed dose" clause


# --- 4. unknown medication --------------------------------------------------


def test_unknown_medication_is_reported_as_not_found(agent, wired):
    orchestrator, _registry = agent
    _activate(wired, name="Amlodipine 5mg")

    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=8),
        turn=AgentTurn(text="Have I taken Metformin today?"),
    )

    last = reply.tool_results[-1]
    assert last.tool_name == ToolName.GET_DOSE_STATUS
    assert last.status == ToolStatus.BLOCKED
    assert last.error_code == "NOT_FOUND"
    assert last.payload["resolution"] == "unknown_medication"
    assert "Metformin" in reply.message
    # It must not invent a status for a medication the patient does not have.
    assert "reported_taken" not in reply.message


def test_question_without_a_resolvable_medication_asks_instead_of_guessing(agent, wired):
    orchestrator, _registry = agent
    _activate(wired, name="Amlodipine 5mg")

    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=9),
        turn=AgentTurn(text="Have I taken it today?"),
    )
    # No medication is named, so nothing is looked up and the agent asks.
    assert AgentIntent.DOSE_STATUS_QUERY == reply.intent
    assert reply.tool_results == []
    assert "which medication" in reply.message.lower()
    assert "Have I taken Amlodipine today?" in reply.message


# --- 5. historical / discontinued medication -------------------------------


def test_discontinued_medication_is_answered_as_history_not_current_status(agent, wired):
    orchestrator, _registry = agent
    _result, activated = _activate(wired)
    wired.clock.advance(hours=10)
    _report(wired, activated.regimen.id, IntakeStatus.REPORTED_TAKEN, key="hist-1")

    # End the regimen: the medication is no longer current.
    wired.regimens.update(
        activated.regimen.model_copy(
            update={"state": RegimenState.ENDED, "effective_to": wired.clock.now()}
        )
    )

    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=10),
        turn=AgentTurn(text="Have I taken Amlodipine today?"),
    )
    last = reply.tool_results[-1]
    # The read must still work and must surface that the regimen is inactive.
    assert last.status == ToolStatus.SUCCESS
    assert last.payload["regimen_active"] is False
    assert last.payload["intake_status"] == "reported_taken"


def test_archived_medication_is_still_findable_for_a_status_question(agent, wired):
    """A discontinued medication must not vanish from a read-only history query."""
    from datetime import UTC, datetime

    orchestrator, _registry = agent
    _result, activated = _activate(wired)
    medication = wired.medications.get(PATIENT, activated.regimen.patient_medication_id)
    assert medication is not None
    wired.medications.update(
        medication.model_copy(update={"archived_at": datetime(2026, 10, 13, tzinfo=UTC)})
    )
    wired.clock.advance(hours=10)

    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=11),
        turn=AgentTurn(text="Have I taken Amlodipine today?"),
    )
    last = reply.tool_results[-1]
    assert last.tool_name == ToolName.GET_DOSE_STATUS
    assert last.payload["resolution"] == "resolved"


# --- 6. cross-patient access refused ---------------------------------------


def test_status_query_never_sees_another_patients_medication(agent, wired):
    """Patient B asking about patient A's medication gets "not found"."""
    orchestrator, _registry = agent
    _activate(wired, name="Amlodipine 5mg", patient_id=PATIENT)

    reply = orchestrator.handle_turn(
        patient_id=OTHER_PATIENT,
        session_id=UUID(int=12),
        turn=AgentTurn(text="Have I taken Amlodipine today?"),
    )
    last = reply.tool_results[-1]
    assert last.status == ToolStatus.BLOCKED
    assert last.error_code == "NOT_FOUND"
    assert last.payload["resolution"] == "unknown_medication"


def test_status_query_tool_is_scoped_by_patient_id(wired):
    """Direct tool call: the same name resolves for its owner only."""
    registry = ToolRegistry(
        enrollment=wired.enrollment,
        schedule=wired.schedule,
        self_report=wired.self_report,
        traces=wired.traces,
        clock=wired.clock,
        ids=wired.ids,
    )
    _activate(wired, name="Amlodipine 5mg", patient_id=PATIENT)

    mine = registry.execute(
        ToolName.GET_DOSE_STATUS,
        GetDoseStatusRequest(**_base(PATIENT, UUID(int=13)), medication_name="Amlodipine"),
    )
    theirs = registry.execute(
        ToolName.GET_DOSE_STATUS,
        GetDoseStatusRequest(**_base(OTHER_PATIENT, UUID(int=14)), medication_name="Amlodipine"),
    )
    assert mine.payload["resolution"] == "resolved"
    assert theirs.payload["resolution"] == "unknown_medication"


def test_reusing_another_patients_session_for_a_status_query_is_refused(agent, wired):
    orchestrator, _registry = agent
    session = orchestrator.start_session(patient_id=PATIENT)
    with pytest.raises(PermissionError):
        orchestrator.handle_turn(
            patient_id=OTHER_PATIENT,
            session_id=session.id,
            turn=AgentTurn(text="Have I taken Amlodipine today?"),
        )


# --- read-only guarantee + no intent leak ----------------------------------


def test_status_query_writes_no_event(agent, wired):
    """Asking a question must never create a record."""
    from datetime import timedelta

    orchestrator, _registry = agent
    _result, activated = _activate(wired)
    wired.clock.advance(hours=10)
    wired.schedule.materialize(patient_id=PATIENT, regimen_id=activated.regimen.id, days=2)
    window_start = wired.clock.now() - timedelta(days=30)
    window_end = wired.clock.now()
    before = len(wired.events.list_for_patient(PATIENT, window_start, window_end))

    orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=15),
        turn=AgentTurn(text="Have I taken Amlodipine today?"),
    )

    after = len(wired.events.list_for_patient(PATIENT, window_start, window_end))
    assert after == before, "a status query must not write a dose event"


def test_unrelated_question_does_not_inherit_a_previous_intent(agent, wired):
    """The observed defect: 'capital of France' inherited dose_self_report."""
    orchestrator, _registry = agent
    _result, activated = _activate(wired)
    wired.clock.advance(hours=10)
    session_id = UUID(int=16)

    first = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=session_id,
        turn=AgentTurn(
            text="I took my dose",
            slots={
                "regimen_id": activated.regimen.id,
                "intake_status": "taken",
                "idempotency_key": "leak-1",
            },
        ),
    )
    assert first.intent == AgentIntent.DOSE_SELF_REPORT

    second = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=session_id,
        turn=AgentTurn(text="What is the capital of France?"),
    )
    assert second.intent == AgentIntent.CLARIFICATION
    # And it must not answer with a dose/medication fact.
    assert "active medication" not in second.message
    assert "dose" not in second.message.lower() or "record" in second.message.lower()
    assert "I can only help with" in second.message


def test_router_extracts_the_medication_name_from_the_question():
    router = DeterministicIntentRouter()
    assert router.extract_medication_name("Have I taken Amlodipine today?") == "Amlodipine"
    assert router.extract_medication_name("Did I take my Metformin yet?") == "Metformin"
    # A pronoun carries no identity: returning it would match an arbitrary
    # medication, so the extractor yields nothing and the agent asks instead.
    assert router.extract_medication_name("Have I taken it today?") == ""
    assert router.extract_medication_name("Have I taken that today?") == ""


def test_status_query_stays_within_the_step_budget(agent, wired):
    orchestrator, _registry = agent
    _activate(wired)
    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=17),
        turn=AgentTurn(text="Have I taken Amlodipine today?"),
    )
    assert len(reply.tool_results) <= 4


def test_status_query_is_labelled_degraded(agent, wired):
    orchestrator, _registry = agent
    _activate(wired)
    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=18),
        turn=AgentTurn(text="Have I taken Amlodipine today?"),
    )
    assert reply.mode == "deterministic_degraded"
    assert reply.message.startswith("[degraded: deterministic rule routing, not a live LLM]")
