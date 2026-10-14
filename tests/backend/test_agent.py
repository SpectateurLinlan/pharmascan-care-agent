"""Agent orchestration tests (Gate 3).

End-to-end through the real orchestrator, real tool registry, real policy and
real in-memory repositories. The intent router is the *degraded* deterministic
rule engine (SIMULATED, no LLM key) — assertions on wording therefore check
the degraded-mode label rather than pretending this is an LLM.

No test here claims live LLM behaviour or a live database.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from app.agent.orchestrator import AgentOrchestrator, AgentTurn, DeterministicIntentRouter
from app.agent.registry import ToolRegistry, UnknownToolError
from app.agent.tools import (
    ListActiveMedicationsRequest,
)
from app.contracts.enums import AgentIntent, IntakeStatus, ToolName, ToolStatus

PATIENT = UUID(int=100)
OTHER_PATIENT = UUID(int=200)


def test_expired_session_read_is_derived_without_mutating_history(agent, wired):
    orchestrator, _ = agent
    session = orchestrator.start_session(patient_id=PATIENT)
    wired.clock.advance(hours=3)
    expired = orchestrator.get_session(patient_id=PATIENT, session_id=session.id)
    assert expired.state == "expired"
    assert expired.updated_at == session.updated_at
    assert wired.sessions.get(PATIENT, session.id) == session
    assert orchestrator.get_session(patient_id=OTHER_PATIENT, session_id=session.id) is None


def test_expired_session_cannot_execute_tools_or_create_confirmation(agent, wired):
    orchestrator, _ = agent
    session = orchestrator.start_session(patient_id=PATIENT)
    wired.clock.advance(hours=3)
    reply = orchestrator.handle_turn(patient_id=PATIENT, session_id=session.id, turn=AgentTurn(text="I took it."))
    assert reply.session_state == "expired" and "Reload" in reply.message
    assert not reply.tool_results and not reply.requires_confirmation and reply.pending_report is None
    assert wired.sessions.get(PATIENT, session.id) == session
    assert not wired.store.events and not wired.store.challenges


def test_tonight_followup_it_resolves_verified_occurrence_and_bounded_memory(agent, wired):
    orchestrator, _ = agent
    result, _ = _activate_via_services(wired, times=("20:00",), add_extra_rule=False)
    session = orchestrator.start_session(patient_id=PATIENT)
    orchestrator.handle_turn(
        patient_id=PATIENT, session_id=session.id, turn=AgentTurn(text="What medicine should I take tonight?")
    )
    saved = orchestrator.get_session(patient_id=PATIENT, session_id=session.id)
    assert saved.context.referenced_medication_id == result.medication.id
    assert saved.context.referenced_occurrence_id is not None
    reply = orchestrator.handle_turn(
        patient_id=PATIENT, session_id=session.id, turn=AgentTurn(text="Did I already take it?")
    )
    assert reply.tool_results[-1].tool_name == ToolName.GET_DOSE_STATUS
    assert result.medication.display_name in reply.message and not wired.store.events
    for _ in range(8):
        orchestrator.handle_turn(patient_id=PATIENT, session_id=session.id, turn=AgentTurn(text="What is due?"))
    assert len(orchestrator.get_session(patient_id=PATIENT, session_id=session.id).context.recent_turns) == 6


def test_multiple_medicines_clarify_then_prepare_only_selected_report(agent, wired):
    orchestrator, _ = agent
    _activate_via_services(wired, add_extra_rule=False)
    metformin, _ = _activate_via_services(wired, name="Metformin", add_extra_rule=False)
    wired.clock.advance(hours=2)
    session = orchestrator.start_session(patient_id=PATIENT)
    reply = orchestrator.handle_turn(
        patient_id=PATIENT, session_id=session.id, turn=AgentTurn(text="I took my medicine.")
    )
    assert "Which medicine did you mean" in reply.message and not reply.pending_report
    assert (
        len(
            orchestrator.get_session(
                patient_id=PATIENT, session_id=session.id
            ).context.awaiting_clarification.candidates
        )
        == 2
    )
    reply = orchestrator.handle_turn(patient_id=PATIENT, session_id=session.id, turn=AgentTurn(text="The Metformin."))
    assert reply.requires_confirmation and reply.pending_report.regimen_id == metformin.regimen.id
    assert not wired.store.events


def test_resuming_draft_is_owned_and_does_not_activate_it(wired):
    from app.contracts.dto import RegimenDraftInput
    from app.domain.errors import NotFoundError

    draft = wired.enrollment.enroll_draft(
        patient_id=PATIENT, draft=RegimenDraftInput(medication_name="DEMO unfinished")
    )
    resumed = wired.enrollment.resume_draft(PATIENT, draft.regimen.id)
    assert resumed.regimen == draft.regimen and resumed.missing_instructions
    with pytest.raises(NotFoundError):
        wired.enrollment.resume_draft(OTHER_PATIENT, draft.regimen.id)
    assert wired.enrollment.find_active_regimen(PATIENT, draft.medication.id) is None


@pytest.mark.parametrize("language,text", [("en", "What medicine should I take tonight?"), ("zh", "今晚吃什么药？")])
def test_tonight_queries_future_reviewed_occurrence_not_generic_count(agent, wired, language, text):
    orchestrator, _ = agent
    result, _activated = _activate_via_services(wired, times=("08:00", "20:00"), add_extra_rule=False)
    session = orchestrator.start_session(patient_id=PATIENT)
    reply = orchestrator.handle_turn(
        patient_id=PATIENT, session_id=session.id, turn=AgentTurn(text=text, language=language)
    )
    schedule = reply.tool_results[-1].payload["schedule"]
    assert len(schedule) == 1 and schedule[0]["local_time"] == "20:00"
    assert result.medication.display_name in reply.message and "20:00" in reply.message
    assert "active medication(s)" not in reply.message
    assert not wired.store.events


@pytest.mark.parametrize("language,text", [("en", "Do I need medicine today?"), ("zh", "今天需要吃药吗？")])
def test_today_question_lists_named_doses_including_later_today_without_intake_write(agent, wired, language, text):
    orchestrator, _ = agent
    result, _ = _activate_via_services(wired, times=("08:00", "20:00"), add_extra_rule=False)
    session = orchestrator.start_session(patient_id=PATIENT)
    reply = orchestrator.handle_turn(
        patient_id=PATIENT, session_id=session.id, turn=AgentTurn(text=text, language=language)
    )
    payload = reply.tool_results[-1].payload
    assert payload["window"] == "today"
    assert {row["local_time"] for row in payload["schedule"]} == {"08:00", "20:00"}
    assert result.medication.display_name in reply.message
    assert "08:00" in reply.message and "20:00" in reply.message
    assert "1 片" in reply.message if language == "zh" else "1 tablet" in reply.message
    assert not wired.store.events and reply.pending_report is None
    other = orchestrator.start_session(patient_id=OTHER_PATIENT)
    isolated = orchestrator.handle_turn(
        patient_id=OTHER_PATIENT, session_id=other.id, turn=AgentTurn(text=text, language=language)
    )
    assert result.medication.display_name not in isolated.message
    assert isolated.tool_results[-1].payload["schedule"] == []


@pytest.mark.parametrize("language", ["en", "zh"])
def test_due_tool_returns_name_quantity_time_for_grounded_reply_without_new_intake(agent, wired, language):
    from app.agent.tools import CheckDueDoseRequest

    orchestrator, registry = agent
    result, _ = _activate_via_services(wired, times=("00:00",), add_extra_rule=False)
    wired.clock.advance(hours=17)
    session = orchestrator.start_session(patient_id=PATIENT)
    due = registry.execute(
        ToolName.CHECK_DUE_DOSE,
        CheckDueDoseRequest(
            patient_id=PATIENT, session_id=session.id, correlation_id=UUID(int=700), client_turn_id="due-demo"
        ),
    )
    row = due.payload["due_doses"][0]
    assert row["medication_name"] == result.medication.display_name
    assert row["dose_amount"] == 1 and row["dose_unit"] == "tablet" and row["local_time"] == "00:00"
    message = orchestrator.render_results(AgentIntent.CLARIFICATION, [due], language)
    assert result.medication.display_name in message and "00:00" in message
    assert not wired.store.events


@pytest.mark.parametrize("text", ["I'm not sure whether I took it.", "我不确定是否吃过药。"])
def test_uncertainty_is_read_only_no_challenge_or_dose_event(agent, wired, text):
    orchestrator, _ = agent
    _activate_via_services(wired)
    session = orchestrator.start_session(patient_id=PATIENT)
    before = len(wired.store.challenges)
    reply = orchestrator.handle_turn(patient_id=PATIENT, session_id=session.id, turn=AgentTurn(text=text))
    assert "No dose will be marked as taken" in reply.message
    assert not reply.requires_confirmation and reply.pending_report is None
    assert len(wired.store.challenges) == before and not wired.store.events


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


# --- allowlist / boundary ---------------------------------------------------


def test_tool_registry_exposes_only_the_documented_allowlist(agent):
    _orchestrator, registry = agent
    assert registry.allowlist == {
        ToolName.CREATE_REMINDER,
        ToolName.LIST_ACTIVE_MEDICATIONS,
        ToolName.GET_MEDICATION_HISTORY,
        ToolName.GET_DOSE_STATUS,
        ToolName.ENROLL_MEDICATION_DRAFT,
        ToolName.CONFIRM_REGIMEN_DRAFT,
        ToolName.CHECK_DUE_DOSE,
        ToolName.RECORD_SELF_REPORT,
    }


def test_unregistered_tool_is_refused(agent):
    _orchestrator, registry = agent
    with pytest.raises(UnknownToolError):
        registry.execute("drop_all_tables", ListActiveMedicationsRequest(**_base(PATIENT, UUID(int=1))))


def test_agent_layer_never_imports_orm_or_sql():
    """Structural guard: the agent package must not reach the database."""
    import re
    from pathlib import Path

    agent_dir = Path(__file__).resolve().parents[2] / "backend" / "app" / "agent"
    forbidden = re.compile(r"\b(psycopg|sqlalchemy|supabase|create table|insert into)\b", re.IGNORECASE)
    for path in agent_dir.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not forbidden.search(source), f"{path.name} reaches the database directly"


# --- enrollment via tools ---------------------------------------------------


def test_agent_enrollment_produces_a_draft_and_asks_for_missing_fields(agent):
    orchestrator, _registry = agent
    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=1),
        turn=AgentTurn(
            text="add a new medication",
            slots={"medication_name": "Metformin"},  # dose + schedule missing
        ),
    )
    assert reply.intent == AgentIntent.MEDICATION_ENROLLMENT
    assert reply.mode == "deterministic_degraded"
    assert reply.tool_results[-1].tool_name == ToolName.ENROLL_MEDICATION_DRAFT
    result = reply.tool_results[-1]
    assert result.payload["state"] == "pending_clarification"
    assert set(result.payload["missing_instructions"]) == {
        "dose_amount",
        "dose_unit",
        "frequency_rule",
    }
    # The agent must ask, not invent the dose.
    assert "I still need" in (result.clarification_question or "")


def test_agent_does_not_activate_without_explicit_confirmation(agent):
    orchestrator, registry = agent
    session_id = UUID(int=2)
    first = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=session_id,
        turn=AgentTurn(
            text="add medication",
            slots={
                "medication_name": "Amlodipine 5mg",
                "dose_amount": 1,
                "dose_unit": "tablet",
                "frequency_kind": "daily",
                "frequency_local_times": ["08:00"],
            },
        ),
    )
    regimen_id = UUID(first.tool_results[-1].payload["regimen_id"])

    # Attempting to confirm without a server-issued challenge must be blocked.
    blocked = registry.execute(
        ToolName.CONFIRM_REGIMEN_DRAFT,
        __import__("app.agent.tools", fromlist=["x"]).ConfirmRegimenRequest(
            **_base(PATIENT, session_id),
            regimen_id=regimen_id,
            challenge_id=UUID(int=999),
            session_state="awaiting_confirmation",
            session_state_version=1,
        ),
    )
    assert blocked.status == ToolStatus.BLOCKED
    assert blocked.error_code == "NOT_FOUND"


# --- self report end-to-end -------------------------------------------------


def _activate_via_services(wired, *, times=("08:00",), add_extra_rule=True, name="Amlodipine 5mg"):
    """Helper: activate a scheduled regimen and register its daily rule."""
    from app.contracts.dto import DoseRuleDTO, FrequencyRuleDTO, RegimenDraftInput
    from app.contracts.enums import RuleKind

    result = wired.enrollment.enroll_draft(
        patient_id=PATIENT,
        draft=RegimenDraftInput(
            medication_name=name,
            dose_amount=1,
            dose_unit="tablet",
            frequency_rule=FrequencyRuleDTO(kind="daily", local_times=list(times)),
        ),
    )
    challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=PATIENT,
        regimen_id=result.regimen.id,
        session_id=UUID(int=500),
        session_state_version=1,
    )
    wired.enrollment.confirm_challenge(patient_id=PATIENT, challenge_id=challenge.id)
    wired.enrollment.review_source_fields(patient_id=PATIENT, source_id=result.regimen.source_id)
    activated = wired.enrollment.activate_regimen(
        patient_id=PATIENT,
        regimen_id=result.regimen.id,
        challenge_id=challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=1,
    )
    if not add_extra_rule:
        return result, activated
    wired.schedule.add_rule(
        patient_id=PATIENT,
        regimen_id=activated.regimen.id,
        rule=DoseRuleDTO(
            id=wired.ids.new_id(),
            patient_id=PATIENT,
            regimen_id=activated.regimen.id,
            rule_kind=RuleKind.SCHEDULED,
            local_times=list(times),
            days_of_week=[],
            timezone="Asia/Singapore",
        ),
    )
    return result, activated


def _due_occurrence_id(reply) -> UUID:
    """The occurrence the agent resolved as due during this turn."""
    for result in reply.tool_results:
        if result.tool_name != ToolName.CHECK_DUE_DOSE:
            continue
        doses = result.payload.get("due_doses") or []
        assert doses, "test setup: the agent must have found a due dose"
        return UUID(str(doses[0]["occurrence_id"]))
    raise AssertionError("the agent never checked for a due dose")


def _arm_confirmation(
    wired,
    *,
    session_id,
    session_state_version,
    regimen_id,
    occurrence_id,
    intake_status,
    idempotency_key,
):
    """Issue and confirm a ``record_self_report`` challenge, as the UI would.

    The database requires every dose event to cite a confirmed, unconsumed
    challenge, and the agent's recording turn advances the session version once
    before it records — so the challenge is armed for the version that turn will
    observe. Nothing here weakens the check; it completes the real lifecycle.
    """
    result = wired.self_report.request_confirmation(
        patient_id=PATIENT,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status=intake_status,
        idempotency_key=idempotency_key,
        session_id=session_id,
        session_state_version=session_state_version,
    )
    wired.self_report.confirm_challenge(patient_id=PATIENT, challenge_id=result.challenge.id)
    return result.challenge.id


def test_agent_self_report_flow_lists_then_records_and_never_claims_ingestion(agent, wired):
    orchestrator, _registry = agent
    _result, activated = _activate_via_services(wired)
    # Advance past today's 08:00 SG dose so it is genuinely due.
    wired.clock.advance(hours=10)
    session_id = UUID(int=3)
    slots = {
        "regimen_id": activated.regimen.id,
        "intake_status": "taken",
        "idempotency_key": "e2e-1",
    }

    # Turn 1: the agent resolves the due dose but must NOT write without an
    # explicit, confirmed challenge — the database would reject the write, so
    # the agent asks for confirmation instead of fabricating one.
    asked = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=session_id,
        turn=AgentTurn(text="I took my morning dose", slots=dict(slots)),
    )
    assert asked.intent == AgentIntent.DOSE_SELF_REPORT
    names = [r.tool_name for r in asked.tool_results]
    assert ToolName.LIST_ACTIVE_MEDICATIONS in names
    assert ToolName.CHECK_DUE_DOSE in names
    gate = asked.tool_results[-1]
    assert gate.tool_name == ToolName.RECORD_SELF_REPORT
    assert gate.status == ToolStatus.BLOCKED
    assert gate.error_code == "CONFIRMATION_REQUIRED"
    assert asked.requires_confirmation is True
    assert asked.session_state == "awaiting_confirmation"

    # The UI completes the confirmation lifecycle against the live session.
    occurrence_id = _due_occurrence_id(asked)
    session = wired.sessions.get(PATIENT, session_id)
    assert session is not None
    challenge_id = _arm_confirmation(
        wired,
        session_id=session_id,
        session_state_version=session.state_version + 1,
        regimen_id=activated.regimen.id,
        occurrence_id=occurrence_id,
        intake_status=IntakeStatus.REPORTED_TAKEN,
        idempotency_key="e2e-1",
    )

    # Turn 2: with a confirmed challenge the report is recorded, and it still
    # never claims ingestion.
    recorded = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=session_id,
        turn=AgentTurn(text="I confirm", slots={**slots, "confirm_challenge_id": challenge_id}),
    )
    last = recorded.tool_results[-1]
    assert last.tool_name == ToolName.RECORD_SELF_REPORT
    assert last.status == ToolStatus.SUCCESS
    assert last.payload["already_recorded"] is False
    assert last.payload["ingestion_proven"] is False
    assert last.payload["visual_status"] == "not_checked"
    assert "does not prove" in recorded.message


def test_agent_replayed_turn_is_idempotent(agent, wired):
    orchestrator, _registry = agent
    _result, activated = _activate_via_services(wired)
    wired.clock.advance(hours=10)
    session_id = UUID(int=4)
    slots = {
        "regimen_id": activated.regimen.id,
        "intake_status": "taken",
        "idempotency_key": "same-key",
    }

    # The agent asks for confirmation; the UI arms the confirmed challenge.
    asked = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=session_id,
        turn=AgentTurn(text="took it", slots=dict(slots)),
    )
    occurrence_id = _due_occurrence_id(asked)
    session = wired.sessions.get(PATIENT, session_id)
    assert session is not None
    challenge_id = _arm_confirmation(
        wired,
        session_id=session_id,
        session_state_version=session.state_version + 1,
        regimen_id=activated.regimen.id,
        occurrence_id=occurrence_id,
        intake_status=IntakeStatus.REPORTED_TAKEN,
        idempotency_key="same-key",
    )
    turn = AgentTurn(text="took it", slots={**slots, "confirm_challenge_id": challenge_id})

    first = orchestrator.handle_turn(patient_id=PATIENT, session_id=session_id, turn=turn)
    second = orchestrator.handle_turn(patient_id=PATIENT, session_id=session_id, turn=turn)

    assert first.tool_results[-1].payload["already_recorded"] is False
    assert second.tool_results[-1].ok, second.tool_results[-1]
    assert second.tool_results[-1].payload["already_recorded"] is True


def test_agent_turn_is_bounded_by_step_budget(agent, wired):
    orchestrator, _registry = agent
    _result, activated = _activate_via_services(wired)
    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=5),
        turn=AgentTurn(
            text="history please",
            slots={"regimen_id": activated.regimen.id, "days": 7},
        ),
    )
    # The orchestrator must not exceed its configured per-turn budget.
    assert len(reply.tool_results) <= 4


def test_agent_history_reports_unreported_as_not_missed(agent, wired):
    orchestrator, _registry = agent
    _result, activated = _activate_via_services(wired, times=("08:00", "20:00"))
    wired.schedule.materialize(patient_id=PATIENT, regimen_id=activated.regimen.id, days=2)

    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=6),
        turn=AgentTurn(text="show history", slots={"regimen_id": activated.regimen.id, "days": 7}),
    )
    history = reply.tool_results[-1]
    assert history.tool_name == ToolName.GET_MEDICATION_HISTORY
    assert history.payload["note"] == "not_reported is not the same as missed"
    assert all(entry["reported"] is False for entry in history.payload["entries"])


# --- traces -----------------------------------------------------------------


def test_every_tool_call_is_traced_and_redacted(agent, wired):
    orchestrator, _registry = agent
    session_id = UUID(int=7)
    orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=session_id,
        turn=AgentTurn(
            text="add medication",
            slots={
                "medication_name": "Metformin 500mg",
                "dose_amount": 1,
                "dose_unit": "tablet",
                "frequency_kind": "daily",
                "frequency_local_times": ["08:00"],
            },
        ),
    )
    traces = wired.traces.list_for_session(PATIENT, session_id)
    assert traces, "each tool call must be persisted as a trace"
    allowed = {
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
    for trace in traces:
        for summary in (trace.request_summary, trace.response_summary):
            assert set(summary).issubset(allowed)
            # No medication names or patient identifiers leak into traces.
            assert "Metformin" not in str(summary)


def test_cross_patient_session_is_isolated(agent):
    orchestrator, _registry = agent
    session = orchestrator.start_session(patient_id=PATIENT)
    # Reusing the first patient's session id for another identity must be
    # refused outright rather than silently starting a new shared session.
    with pytest.raises(PermissionError):
        orchestrator.handle_turn(
            patient_id=OTHER_PATIENT,
            session_id=session.id,
            turn=AgentTurn(text="hello"),
        )


def test_each_patient_gets_their_own_session(agent):
    orchestrator, _registry = agent
    first = orchestrator.start_session(patient_id=PATIENT)
    second = orchestrator.start_session(patient_id=OTHER_PATIENT)
    assert first.id != second.id
    assert orchestrator._sessions.get(PATIENT, first.id) is not None
    assert orchestrator._sessions.get(OTHER_PATIENT, first.id) is None


def test_degraded_mode_is_always_labelled(agent):
    orchestrator, _registry = agent
    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=8),
        turn=AgentTurn(text="hello there"),
    )
    assert reply.mode == "deterministic_degraded"
    assert reply.message.startswith("[degraded: deterministic rule routing, not a live LLM]")


def test_router_is_rule_based_and_not_presented_as_llm():
    router = DeterministicIntentRouter()
    assert router.is_llm is False
    assert router.name.startswith("SIMULATED")


# --- negative branches required by the Gate 3 checklist ---------------------


def test_agent_blocks_report_on_archived_medication(agent, wired):
    """Discontinued/archived medication must not accept new dose reports."""
    from datetime import UTC, datetime

    orchestrator, _registry = agent
    _result, activated = _activate_via_services(wired)
    wired.clock.advance(hours=10)
    wired.schedule.materialize(patient_id=PATIENT, regimen_id=activated.regimen.id, days=2)

    medication = wired.medications.get(PATIENT, activated.regimen.patient_medication_id)
    assert medication is not None
    wired.medications.update(medication.model_copy(update={"archived_at": datetime(2026, 10, 13, tzinfo=UTC)}))

    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=11),
        turn=AgentTurn(
            text="I took it",
            slots={
                "regimen_id": activated.regimen.id,
                "intake_status": "taken",
                "idempotency_key": "archived-1",
            },
        ),
    )
    last = reply.tool_results[-1]
    assert last.tool_name == ToolName.RECORD_SELF_REPORT
    assert last.status == ToolStatus.BLOCKED
    assert last.error_code in ("STALE_VERSION", "POLICY_BLOCKED")


def test_agent_blocks_report_on_inactive_regimen(agent, wired):
    orchestrator, _registry = agent
    _result, activated = _activate_via_services(wired)
    wired.clock.advance(hours=10)
    wired.schedule.materialize(patient_id=PATIENT, regimen_id=activated.regimen.id, days=2)

    from app.contracts.enums import RegimenState

    wired.regimens.update(
        activated.regimen.model_copy(update={"state": RegimenState.ENDED, "effective_to": wired.clock.now()})
    )
    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=12),
        turn=AgentTurn(
            text="took my dose",
            slots={
                "regimen_id": activated.regimen.id,
                "intake_status": "taken",
                "idempotency_key": "ended-2",
            },
        ),
    )
    last = reply.tool_results[-1]
    assert last.status == ToolStatus.BLOCKED


def test_agent_rejects_invalid_patient_choice_without_defaulting(agent, wired):
    """An unrecognised intake choice must be refused, not silently guessed."""
    orchestrator, _registry = agent
    _result, activated = _activate_via_services(wired)
    wired.clock.advance(hours=10)
    wired.schedule.materialize(patient_id=PATIENT, regimen_id=activated.regimen.id, days=2)

    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=13),
        turn=AgentTurn(
            text="whatever",
            slots={
                "regimen_id": activated.regimen.id,
                "intake_status": "maybe_later_probably",
                "idempotency_key": "bad-choice",
            },
        ),
    )
    last = reply.tool_results[-1]
    assert last.status == ToolStatus.BLOCKED
    assert last.error_code == "INVALID_INPUT"


def test_agent_enrollment_without_dose_asks_and_never_invents(agent):
    """Missing regimen instructions must produce a question, not a default."""
    orchestrator, _registry = agent
    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=14),
        turn=AgentTurn(text="add a medication", slots={"medication_name": "Unknown pill"}),
    )
    result = reply.tool_results[-1]
    assert result.payload["state"] == "pending_clarification"
    assert result.payload["missing_instructions"]
    assert result.clarification_question is not None


def test_vision_provider_timeout_never_becomes_a_successful_match():
    """A Stage2 timeout must surface as unavailable, never as a match."""
    from app.infrastructure.stage2_adapter import HttpStage2VisionProvider, HttpTransport
    from app.infrastructure.vision_contracts import VisionUnavailable

    class TimeoutTransport(HttpTransport):
        def __init__(self) -> None:
            super().__init__(base_url="https://example.invalid", timeout_seconds=1.0)

        def post_json(self, path, payload):  # type: ignore[no-untyped-def]
            raise TimeoutError("simulated timeout")

        def post_multipart(self, path, files, data):  # type: ignore[no-untyped-def]
            raise TimeoutError("simulated timeout")

    import json
    from pathlib import Path

    from app.contracts.vision import EmbeddingResult, GalleryReference
    from app.infrastructure.stage2_schema import Stage2Contract

    spec = json.loads(
        (Path(__file__).resolve().parents[2] / "docs/external/pharmascan-api-openapi-0.8.0.json").read_text(
            encoding="utf-8"
        )
    )
    provider = HttpStage2VisionProvider(
        transport=TimeoutTransport(),
        contract=Stage2Contract(spec),
        embedding_space_id="s",
        model_version="m",
        preprocessing_version="p",
    )
    with pytest.raises(VisionUnavailable):
        provider.match(
            queries=[
                EmbeddingResult(
                    embedding=[1.0] + [0.0] * 255,
                    dimension=256,
                    embedding_space_id="s",
                    model_version="m",
                    preprocessing_version="p",
                    normalized=True,
                )
            ],
            gallery=[
                GalleryReference(
                    medication_id="med-1",
                    embeddings=[[1.0] + [0.0] * 255],
                    embedding_space_id="s",
                    model_version="m",
                    preprocessing_version="p",
                )
            ],
        )


def test_explicit_due_question_uses_typed_read_tool_without_intake_write():
    from uuid import uuid4

    from app.agent.orchestrator import AgentTurn
    from app.transport.container import build_container

    container = build_container()
    patient = uuid4()
    session = container.orchestrator.start_session(patient_id=patient)
    reply = container.orchestrator.handle_turn(
        patient_id=patient, session_id=session.id, turn=AgentTurn(text="What medicine should I take tonight?")
    )
    assert not container.store.events and not container.store.regimens
    assert reply.tool_results[0].tool_name.value == "check_due_dose"
    assert reply.tool_results[0].payload["item_count"] == 0
