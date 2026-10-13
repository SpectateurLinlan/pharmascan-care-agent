"""Unsupported assistant questions must be answered honestly (Session 3A item 4).

** SIMULATED / DEGRADED ** There is no live LLM and no live Knowledge tool
(B03). The product rule is: when the deterministic router cannot support a
question, say so, offer an executable next step, and never emit a
plausible-but-irrelevant answer or invented medical knowledge.

The observed defect this file guards against: "What is the capital of France?"
was answered with "Done. You have 1 active medication(s)." — a confident,
irrelevant reply produced by reusing the previous turn's intent and by always
calling ``list_active_medications`` on the clarification path.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from app.agent.orchestrator import (
    AgentOrchestrator,
    AgentTurn,
    DeterministicIntentRouter,
)
from app.agent.registry import ToolRegistry
from app.contracts.dto import FrequencyRuleDTO, RegimenDraftInput
from app.contracts.enums import AgentIntent

PATIENT = UUID(int=100)


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


def _activate(wired, *, name="Amlodipine 5mg"):
    result = wired.enrollment.enroll_draft(
        patient_id=PATIENT,
        draft=RegimenDraftInput(
            medication_name=name,
            dose_amount=1,
            dose_unit="tablet",
            frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["08:00"]),
        ),
    )
    challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=PATIENT,
        regimen_id=result.regimen.id,
        session_id=UUID(int=500),
        session_state_version=1,
    )
    wired.enrollment.confirm_challenge(patient_id=PATIENT, challenge_id=challenge.id)
    wired.enrollment.review_source_fields(
        patient_id=PATIENT, source_id=result.regimen.source_id
    )
    return wired.enrollment.activate_regimen(
        patient_id=PATIENT,
        regimen_id=result.regimen.id,
        challenge_id=challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=1,
    )


@pytest.mark.parametrize(
    "question",
    [
        "What is the capital of France?",
        "Tell me a joke",
        "Should I increase my dose?",
        "What is the weather tomorrow?",
        "Can you diagnose my headache?",
        "How do I cook pasta?",
    ],
)
def test_unsupported_question_is_routed_to_clarification(agent, wired, question):
    orchestrator, _registry = agent
    _activate(wired)
    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=1),
        turn=AgentTurn(text=question),
    )
    assert reply.intent == AgentIntent.CLARIFICATION


@pytest.mark.parametrize(
    "question",
    [
        "What is the capital of France?",
        "Tell me a joke",
        "What is the weather tomorrow?",
    ],
)
def test_unsupported_question_never_returns_a_medication_fact(agent, wired, question):
    """The repair: an unrelated question must not be answered with dose data."""
    orchestrator, _registry = agent
    _activate(wired)
    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=2),
        turn=AgentTurn(text=question),
    )
    lowered = reply.message.lower()
    assert "active medication" not in lowered
    assert "reported taking" not in lowered
    assert reply.tool_results == [], "no tool should run for an unsupported question"


def test_unsupported_question_states_the_degraded_capability(agent, wired):
    orchestrator, _registry = agent
    _activate(wired)
    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=3),
        turn=AgentTurn(text="Tell me about drug interactions"),
    )
    assert reply.mode == "deterministic_degraded"
    assert reply.message.startswith("[degraded: deterministic rule routing, not a live LLM]")
    assert "I can only help with" in reply.message
    assert "cannot answer" in reply.message.lower()


def test_unsupported_question_offers_executable_supported_actions(agent, wired):
    orchestrator, _registry = agent
    _activate(wired)
    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=4),
        turn=AgentTurn(text="hello there"),
    )
    lowered = reply.message.lower()
    # The patient is told concretely what the assistant CAN do.
    for capability in ("add", "record", "reported today", "history"):
        assert capability in lowered, f"missing offered capability: {capability}"


def test_unsupported_question_does_not_invent_medical_advice(agent, wired):
    """A dosing-advice question must not be answered as if it were clinical."""
    orchestrator, _registry = agent
    _activate(wired)
    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=5),
        turn=AgentTurn(text="Should I take two tablets instead?"),
    )
    # Whatever the route, no number or instruction is invented.
    assert "two tablets" not in reply.message.lower()
    assert "you should take" not in reply.message.lower()
    assert reply.intent in (AgentIntent.CLARIFICATION, AgentIntent.DOSE_SELF_REPORT)


def test_supported_question_is_not_swallowed_by_the_boundary(agent, wired):
    """The honesty boundary must not break genuinely supported questions."""
    orchestrator, _registry = agent
    _activate(wired)
    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=UUID(int=6),
        turn=AgentTurn(text="Have I taken Amlodipine today?"),
    )
    assert reply.intent == AgentIntent.DOSE_STATUS_QUERY
    assert reply.tool_results, "a supported question must still reach a tool"
