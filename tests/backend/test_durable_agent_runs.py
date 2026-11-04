"""Actual synthetic durable-control semantics; no SQL/restart proof is inferred."""

import importlib
import importlib.util
from datetime import timedelta
from uuid import uuid4

import pytest
from app.contracts.agent_execution import BudgetExceeded, ProviderUsage, TaskCancelled
from app.contracts.workflow_persistence import WorkflowWriteBinding
from app.domain.errors import DuplicateEventError, NotFoundError, StaleVersionError
from app.infrastructure.memory_workflows import MemoryWorkflowState

from .conftest import FixedClock


def api(module, name):
    assert importlib.util.find_spec(module), f"Missing approved durable run contract: {module}"
    return getattr(importlib.import_module(module), name)


def command(name, state, **values):
    return api("app.contracts.workflow_run_control", name)(
        ticket_id=state.worker_ticket, nonce=state.worker_nonce, epoch=state.epoch, event_id=uuid4(), **values
    )


def harness():
    cls = api("app.infrastructure.durable_agent_runs", "MemoryDurableRunControl")
    clock, memory = FixedClock(), MemoryWorkflowState()
    return cls(clock=clock, state=memory), clock, memory


def claimed(port, owner, run_id=None):
    state = port.start(owner, run_id or uuid4(), None)
    return port.record_run(command("ClaimRun", state), timeout_seconds=3)


@pytest.mark.parametrize("step", ["model", "tool"])
def test_deadline_and_step_limits_are_server_controlled(step):
    port, clock, _ = harness()
    owner = uuid4()
    state = claimed(port, owner)
    assert state.deadline_at - state.started_at == timedelta(seconds=45)
    for _ in range(4):
        span = uuid4()
        state = port.record_run(command("StartRunStep", state, span_id=span, step_kind=step), timeout_seconds=3)
        state = port.record_run(
            command("FinishRunStep", state, span_id=span, succeeded=True, duration_ms=1), timeout_seconds=3
        )
    with pytest.raises(BudgetExceeded):
        port.record_run(command("StartRunStep", state, span_id=uuid4(), step_kind=step), timeout_seconds=3)
    assert state.deadline_at - clock.now() == timedelta(seconds=45)


def test_cancel_rejects_stale_epoch_and_content():
    port, _, _ = harness()
    owner, other = uuid4(), uuid4()
    initial = port.start(owner, uuid4(), None)
    state = port.record_run(command("ClaimRun", initial), timeout_seconds=3)
    with pytest.raises(StaleVersionError):
        port.record_run(command("StartRunStep", initial, span_id=uuid4(), step_kind="tool"), timeout_seconds=3)
    with pytest.raises(NotFoundError):
        port.read(other, state.run_id)
    cancelled = port.request_cancel(owner, state.run_id)
    assert cancelled.status == "cancelling"
    with pytest.raises(TaskCancelled):
        port.record_run(command("StartRunStep", state, span_id=uuid4(), step_kind="tool"), timeout_seconds=3)


def test_duplicate_events_and_usage_do_not_double_count():
    port, _, _ = harness()
    owner = uuid4()
    state = claimed(port, owner)
    span = uuid4()
    start = command("StartRunStep", state, span_id=span, step_kind="model")
    first = port.record_run(start, timeout_seconds=3)
    repeated = port.record_run(start, timeout_seconds=3)
    assert first.snapshot.metadata.model_requests == repeated.snapshot.metadata.model_requests == 1
    attempt = uuid4()
    port.record_run(
        command("RecordRunProvider", state, observation={"phase": "attempt", "span_id": span, "attempt_id": attempt}),
        timeout_seconds=3,
    )
    response = command(
        "RecordRunProvider",
        state,
        observation={
            "phase": "response",
            "attempt_id": attempt,
            "returned_model": "DEMO-model",
            "usage": ProviderUsage(input_tokens=11, output_tokens=3).model_dump(),
        },
    )
    port.record_run(response, timeout_seconds=3)
    final = port.record_run(response, timeout_seconds=3)
    assert final.snapshot.metadata.usage_responses == 1 and final.snapshot.metadata.usage.input_tokens == 11


def test_interruption_preserves_unknown_business_outcome_and_refuses_replay():
    port, clock, memory = harness()
    owner = uuid4()
    state = claimed(port, owner)
    original_tasks = dict(memory.tasks)
    clock.advance(seconds=46)
    result = port.record_run(command("RecoverInterruptedRun", state), timeout_seconds=3)
    assert result.status == "failed" and result.snapshot.events[-1].reason_key == "worker_interrupted"
    assert memory.tasks == original_tasks
    with pytest.raises(DuplicateEventError):
        port.record_run(command("ClaimRun", result), timeout_seconds=3)
    with pytest.raises(DuplicateEventError):
        port.start(owner, state.run_id, None)


def test_native_confirmation_outlives_chat_deadline():
    # Independent patient bindings must not inherit a completed chat's epoch or deadline.
    from app.contracts.assistant_workflows import BusinessRef

    binding = WorkflowWriteBinding(
        task_id=uuid4(),
        task_revision=1,
        capability_id="observation.add",
        action_key=uuid4(),
        prepared_ref=BusinessRef(kind="care_review", id=uuid4()),
        expected_domain_revision=0,
    )
    assert binding.run_binding is None


def test_another_instance_observes_the_same_cancel_state_without_process_mutex_facade():
    port, clock, memory = harness()
    second = type(port)(clock=clock, state=memory)
    owner = uuid4()
    first = claimed(port, owner)
    second.request_cancel(owner, first.run_id)
    assert port.read(owner, first.run_id).status == "cancelling"
    assert not hasattr(port, "locked")


def test_cancellation_keeps_actual_late_provider_usage():
    port, _, _ = harness()
    owner = uuid4()
    state = claimed(port, owner)
    span, attempt = uuid4(), uuid4()
    port.record_run(command("StartRunStep", state, span_id=span, step_kind="model"), timeout_seconds=3)
    port.record_run(
        command("RecordRunProvider", state, observation={"phase": "attempt", "span_id": span, "attempt_id": attempt}),
        timeout_seconds=3,
    )
    port.request_cancel(owner, state.run_id)
    final = port.record_run(
        command(
            "RecordRunProvider",
            state,
            observation={
                "phase": "response",
                "attempt_id": attempt,
                "returned_model": "DEMO-model",
                "usage": {"input_tokens": 9},
            },
        ),
        timeout_seconds=3,
    )
    assert final.status == "cancelling" and final.snapshot.metadata.usage.input_tokens == 9


def test_actual_execution_service_uses_commands_and_never_replays_work():
    from app.application.agent_execution import AgentExecutionService
    from app.contracts.agent_execution import current_execution, execution_step

    port, _, _ = harness()
    service = AgentExecutionService(control=port, verifier=port)
    owner, run = uuid4(), uuid4()
    service.start(owner, run)
    calls = []

    def work():
        calls.append("DEMO-work")
        with execution_step("model"):
            control = current_execution.get()
            control.model_started("DEMO-model", "DEMO-private-instruction", [])
            control.sdk_attempt()
            control.model_returned("DEMO-model", ProviderUsage(input_tokens=7))
        return "DEMO-result"

    assert service.execute(owner, run, work) == "DEMO-result"
    assert service.read(owner, run).status == "completed"
    assert service.read(owner, run).metadata.usage.input_tokens == 7
    with pytest.raises(DuplicateEventError):
        service.execute(owner, run, work)
    assert calls == ["DEMO-work"]
    assert "DEMO-private-instruction" not in service.read(owner, run).model_dump_json()


def test_durable_execution_rejects_an_unconverted_write_callback():
    from app.application.agent_execution import AgentExecutionService
    from app.contracts.agent_execution import current_execution
    from app.domain.errors import ProviderUnavailableError

    port, _, _ = harness()
    service = AgentExecutionService(control=port, verifier=port)
    owner, run, writes = uuid4(), uuid4(), []
    service.start(owner, run)

    def work():
        current_execution.get().guarded(lambda: writes.append("DEMO-private-write"))

    with pytest.raises(ProviderUnavailableError):
        service.execute(owner, run, work)
    assert writes == [] and service.read(owner, run).status == "failed"


def test_patient_run_wire_cannot_set_deadline_or_other_owner():
    import json

    import httpx
    from app.infrastructure.supabase_data import SupabaseDataClient

    port, _, _ = harness()
    owner, run = uuid4(), uuid4()
    state = port.start(owner, run, None)
    calls = []

    def remote(request):
        calls.append(request)
        return httpx.Response(200, json={"result": state.model_dump(mode="json")})

    data = SupabaseDataClient(
        base_url="https://demo-test.supabase.co",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=owner,
        client=httpx.Client(transport=httpx.MockTransport(remote)),
    )
    cls = api("app.infrastructure.durable_agent_runs", "SupabaseDurableRunControl")
    result = cls(data).start(owner, run, None)
    assert result.run_id == run
    body = json.loads(calls[0].content)["p_command"]
    assert body == {"kind": "start", "run_id": str(run), "task_id": None}
    assert calls[0].url.path == "/rest/v1/rpc/assistant_run_control"
    assert max(calls[0].extensions["timeout"].values()) <= 3


def test_typed_content_writes_keep_the_active_epoch_and_stop_after_cancel(workflow):
    from app.application.agent_execution import AgentExecutionService
    from app.application.workflow_message_policy import MessagePersistencePolicy
    from app.infrastructure.conversation_history import MemoryConversationHistory
    from app.infrastructure.conversation_threads import MemoryConversationThreads
    from app.infrastructure.memory_repos import InMemoryAgentSessionRepository, InMemoryStore
    from app.infrastructure.workflow_message_repos import MemoryConversationPersistence

    from .test_workflow_message_transactions import session

    port, clock, memory = harness()
    owner, run = workflow.owner_ids["A"], uuid4()
    store = InMemoryStore()
    sessions = InMemoryAgentSessionRepository(store)
    policy = MessagePersistencePolicy(
        messages=MemoryConversationPersistence(
            state=memory,
            sessions=sessions,
            threads=MemoryConversationThreads(),
            history=MemoryConversationHistory(),
            preferences=workflow.container.preferences,
            clock=clock,
        )
    )
    service = AgentExecutionService(control=port, verifier=port)
    service.start(owner, run)
    first, second = session(owner), session(owner)

    def work():
        assert policy.persist_session(sessions, first, create=True)
        service.cancel(owner, run)
        policy.persist_session(sessions, second, create=True)

    with pytest.raises(TaskCancelled):
        service.execute(owner, run, work)
    assert sessions.get(owner, first.id) is not None and sessions.get(owner, second.id) is None


def test_memory_transaction_accepts_live_durable_epoch_and_rejects_cancelled_epoch(workflow):
    from app.contracts.workflow_messages import ConversationWriteScope, CreateSession
    from app.contracts.workflow_persistence import RunWriteBinding
    from app.infrastructure.conversation_history import MemoryConversationHistory
    from app.infrastructure.conversation_threads import MemoryConversationThreads
    from app.infrastructure.memory_repos import InMemoryAgentSessionRepository, InMemoryStore
    from app.infrastructure.workflow_message_repos import MemoryConversationPersistence

    from .test_workflow_message_transactions import session

    port, clock, memory = harness()
    owner = workflow.owner_ids["A"]
    state = claimed(port, owner)
    sessions = InMemoryAgentSessionRepository(InMemoryStore())
    messages = MemoryConversationPersistence(
        state=memory,
        sessions=sessions,
        threads=MemoryConversationThreads(),
        history=MemoryConversationHistory(),
        preferences=workflow.container.preferences,
        clock=clock,
    )
    scope = ConversationWriteScope(run_binding=RunWriteBinding(run_id=state.run_id, epoch=state.epoch))
    first = session(owner)
    assert messages.execute(owner, CreateSession(scope=scope, session=first)).kind == "ack"
    port.request_cancel(owner, state.run_id)
    with pytest.raises(StaleVersionError):
        messages.execute(owner, CreateSession(scope=scope, session=session(owner)))


def test_restricted_run_wire_uses_only_its_fixed_function_and_ticket():
    from app.infrastructure.workflow_verification import (
        EvidenceConnectionSettings,
        PostgresEvidenceVerifier,
        RestrictedEvidenceConnection,
    )

    from .test_workflow_verification_transport import DSN, RecordingConnection, Row

    port, _, _ = harness()
    original = port.start(uuid4(), uuid4(), None)
    claim = command("ClaimRun", original)
    response = port.record_run(claim, timeout_seconds=3)

    class RunConnection(RecordingConnection):
        def execute(self, sql, params=None):
            if "record_run_observation" in sql:
                self.calls.append((sql, params))
                return Row({"result": response.model_dump(mode="json")})
            return super().execute(sql, params)

    db = RunConnection()
    verifier = PostgresEvidenceVerifier(
        RestrictedEvidenceConnection(EvidenceConnectionSettings(DSN), connect=lambda **kw: db)
    )
    actual = verifier.record_run(claim, timeout_seconds=3)
    assert actual.epoch == 1 and actual.owner == original.owner
    sql, params = next(row for row in db.calls if "record_run_observation" in row[0])
    assert sql == "SELECT assistant_evidence.record_run_observation(%s) AS result"
    assert "owner" not in params[0].obj and db.closed


def test_new_service_settles_only_expired_run_metadata_without_replaying_work():
    from app.application.agent_execution import AgentExecutionService

    port, clock, memory = harness()
    owner, run = uuid4(), uuid4()
    state = claimed(port, owner, run)
    clock.advance(seconds=46)
    restarted = AgentExecutionService(control=port, verifier=port)
    snapshot = restarted.read(owner, run)
    assert snapshot.status == "failed" and snapshot.events[-1].reason_key == "worker_interrupted"
    assert snapshot.metadata.model_requests == 0 and snapshot.metadata.tool_calls == 0
    assert memory.tasks == {} and state.run_id == run


def test_run_sql_candidates_separate_patient_and_server_authority():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "supabase/review/assistant_workflows"
    up, down = root / "runs.up.sql", root / "runs.down.sql"
    assert up.is_file() and down.is_file(), "Missing durable run SQL candidates"
    sql = up.read_text(encoding="utf-8")
    assert "public.assistant_run_control" in sql and "public.assistant_run_assert_current" in sql
    assert "assistant_evidence.record_run_observation" in sql and "session_user" in sql
    assert "interval '45 seconds'" in sql and "pg_advisory_xact_lock" in sql
    assert "FROM PUBLIC" in sql and "TO assistant_evidence_login" in sql
    assert "RAISE EXCEPTION" in down.read_text(encoding="utf-8")
    assert "DELETE FROM public.agent_sessions" not in sql
