"""SIMULATED model I/O; real existing application/tool/session safety."""

from datetime import timedelta
from uuid import UUID

import pytest
from app.agent.conversation import ConversationService
from app.agent.model_tools import ModelTools, model_tool_schemas
from app.agent.orchestrator import AgentTurn
from app.contracts.model import FunctionCall, ModelReply

PATIENT = UUID(int=100)


@pytest.fixture()
def agent(wired):
    from app.agent.orchestrator import AgentOrchestrator, DeterministicIntentRouter
    from app.agent.registry import ToolRegistry

    registry = ToolRegistry(
        enrollment=wired.enrollment,
        schedule=wired.schedule,
        self_report=wired.self_report,
        traces=wired.traces,
        clock=wired.clock,
        ids=wired.ids,
    )
    return AgentOrchestrator(
        registry=registry, sessions=wired.sessions, router=DeterministicIntentRouter(), clock=wired.clock, ids=wired.ids
    ), registry


class Scripted:
    model = "SIMULATED-gemini"

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def create(self, **request):
        self.requests.append(request)
        return self.replies.pop(0)


def service(agent, wired, model):
    fallback, registry = agent
    return ConversationService(
        model=model,
        tools=ModelTools(registry=registry, fallback=fallback),
        fallback=fallback,
        sessions=wired.sessions,
        ids=wired.ids,
    )


def test_provider_429_refunds_user_turn_but_keeps_model_request_accounting(agent, wired):
    from app.application.ai_quota import QuotaAgent
    from app.contracts.model import ModelProviderError
    from app.infrastructure.memory_quota import MemoryQuota

    class RateLimited:
        model = "SIMULATED-rate-limited"

        def create(self, **kwargs):
            raise ModelProviderError("quota")

    quota = MemoryQuota(clock=wired.clock, nonce_factory=lambda: "SIMULATED")
    guarded = QuotaAgent(repository=quota, conversation=service(agent, wired, RateLimited()), fallback=agent[0])
    session = agent[0].start_session(patient_id=PATIENT)
    reply = guarded.handle_turn(
        patient_id=PATIENT,
        session_id=session.id,
        turn=AgentTurn(text="What medicine should I take tonight?", slots={"client_turn_id": "quota-failure"}),
    )
    assert "current free usage capacity" in reply.message and reply.mode == "deterministic_degraded"
    assert reply.usage.llm_user_turns == 0 and reply.usage.model_requests == 1
    assert not wired.store.events


def test_model_schema_has_no_identity_or_confirmed_write_surface():
    import json

    schemas = model_tool_schemas()
    assert "patient_id" not in json.dumps(schemas)
    assert "confirmed_challenge_id" not in json.dumps(schemas)
    assert "record_self_report" not in {row["name"] for row in schemas}
    assert "prepare_health_observation" in {row["name"] for row in schemas}


def test_health_function_only_offers_original_words_for_review(agent, wired):
    from app.application.observations import ObservationService
    from app.infrastructure.observation_repos import MemoryObservations

    observations = ObservationService(MemoryObservations(), wired.medications, wired.clock)
    model = Scripted(
        [ModelReply(calls=[FunctionCall(id="health-call", name="prepare_health_observation", arguments={})])]
    )
    fallback, registry = agent
    session = fallback.start_session(patient_id=PATIENT)
    conversation = ConversationService(
        model=model,
        tools=ModelTools(registry=registry, fallback=fallback, observations=observations),
        fallback=fallback,
        sessions=wired.sessions,
        ids=wired.ids,
    )
    reply = conversation.handle_turn(
        patient_id=PATIENT, session_id=session.id, turn=AgentTurn(text="DEMO I feel dizzy after my evening medicine")
    )
    assert reply.health_note_request.description == "DEMO I feel dizzy after my evening medicine"
    assert not wired.store.events and not wired.store.regimens
    assert (
        observations.list(PATIENT, wired.clock.now() - timedelta(days=1), wired.clock.now() + timedelta(days=1)) == []
    )
    saved = fallback.get_session(patient_id=PATIENT, session_id=session.id)
    assert saved.context.recent_turns[-1].user == "DEMO I feel dizzy after my evening medicine"


def test_severe_health_description_gets_conditional_help_not_diagnosis_or_intake(agent, wired):
    from app.application.observations import ObservationService
    from app.infrastructure.observation_repos import MemoryObservations

    model = Scripted([ModelReply(calls=[FunctionCall(id="urgent", name="prepare_health_observation", arguments={})])])
    fallback, registry = agent
    session = fallback.start_session(patient_id=PATIENT)
    observations = ObservationService(MemoryObservations(), wired.medications, wired.clock)
    conversation = ConversationService(
        model=model,
        tools=ModelTools(registry=registry, fallback=fallback, observations=observations),
        fallback=fallback,
        sessions=wired.sessions,
        ids=wired.ids,
    )
    reply = conversation.handle_turn(
        patient_id=PATIENT, session_id=session.id, turn=AgentTurn(text="DEMO I cannot breathe")
    )
    assert reply.health_note_request is None and model.requests == []
    assert "995 in Singapore" in reply.message and "do not wait" in reply.message
    assert not wired.store.events and reply.pending_report is None
    assert not wired.store.challenges


@pytest.mark.parametrize(
    "window,text", [("tonight", "What medicine should I take tonight?"), ("today", "今天需要吃药吗？")]
)
def test_function_result_roundtrip_is_id_bound_and_no_fake_medication(agent, wired, window, text):
    model = Scripted(
        [
            ModelReply(calls=[FunctionCall(id="call-demo", name="check_due_dose", arguments={"window": window})]),
            ModelReply(text="Take fabricated medicine now."),
        ]
    )
    session = agent[0].start_session(patient_id=PATIENT)
    reply = service(agent, wired, model).handle_turn(
        patient_id=PATIENT,
        session_id=session.id,
        turn=AgentTurn(text=text, language="zh" if window == "today" else "en"),
    )
    assert reply.mode == "gemini" and "fabricated" not in reply.message
    result = model.requests[1]["history"][-1]
    assert (
        result["type"] == "function_result" and result["call_id"] == "call-demo" and result["name"] == "check_due_dose"
    )
    assert not wired.store.events


@pytest.mark.parametrize(
    "name,args",
    [
        ("delete_database", {}),
        ("check_due_dose", {"patient_id": str(PATIENT)}),
        ("prepare_self_report", {"confirmed_challenge_id": str(UUID(int=9))}),
    ],
)
def test_unknown_or_identity_and_confirmation_arguments_rejected(agent, wired, name, args):
    model = Scripted([ModelReply(calls=[FunctionCall(id="unsafe", name=name, arguments=args)])])
    session = agent[0].start_session(patient_id=PATIENT)
    reply = service(agent, wired, model).handle_turn(
        patient_id=PATIENT, session_id=session.id, turn=AgentTurn(text="What medicine should I take tonight?")
    )
    assert reply.mode == "deterministic_degraded" and not wired.store.events
