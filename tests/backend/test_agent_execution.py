"""SIMULATED execution controls: no provider, patient or SQL writes."""

from importlib.util import find_spec
from uuid import uuid4

import pytest


def test_bounded_execution_available():
    assert find_spec("app.application.agent_execution"), "bounded execution service is missing"


@pytest.fixture
def runtime():
    from app.application.agent_execution import AgentExecutionService
    from app.infrastructure.memory_agent_runs import MemoryRunRepository
    from app.infrastructure.memory_workflows import MemoryWorkflowState

    now = [100.0]
    repo = MemoryRunRepository(MemoryWorkflowState())
    return AgentExecutionService(repo, monotonic=lambda: now[0]), repo, now


def test_four_model_and_tool_steps_no_fifth_side_effect(runtime):
    from app.contracts.agent_execution import BudgetExceeded, execution_step

    service, _, now = runtime
    owner, run = uuid4(), uuid4()
    touched = []

    def work():
        for _ in range(5):
            with execution_step("model"):
                now[0] += 0.1
            with execution_step("tool"):
                touched.append(1)
                now[0] += 0.2

    service.start(owner, run)
    with pytest.raises(BudgetExceeded):
        service.execute(owner, run, work)
    snapshot = service.read(owner, run)
    assert len(touched) == 4
    assert snapshot.metadata.model_requests == snapshot.metadata.tool_calls == 4
    assert snapshot.status == "failed" and snapshot.events[-1].reason_key == "budget_exceeded"
    assert [e.sequence for e in snapshot.events] == list(range(1, len(snapshot.events) + 1))
    assert all(e.duration_ms > 0 for e in snapshot.events if e.kind == "step_completed")


def test_deadline_prevents_next_step_and_late_history(runtime):
    from app.application.workflow_message_policy import MessagePersistencePolicy
    from app.contracts.agent_execution import DeadlineExceeded, execution_step

    service, _, now = runtime
    owner, run = uuid4(), uuid4()
    writes = []
    service.start(owner, run)

    def work():
        with execution_step("tool"):
            now[0] += 46
        MessagePersistencePolicy().write_history(lambda: writes.append("late"))

    with pytest.raises(DeadlineExceeded):
        service.execute(owner, run, work)
    assert not writes
    assert service.read(owner, run).events[-1].reason_key == "deadline_exceeded"


def test_cancel_shared_across_service_instances_preserves_committed_operation(runtime):
    from app.application.agent_execution import AgentExecutionService
    from app.contracts.agent_execution import TaskCancelled, execution_step

    service, repo, now = runtime
    other = AgentExecutionService(repo, monotonic=lambda: now[0])
    owner, run = uuid4(), uuid4()
    writes = []
    service.start(owner, run)

    def work():
        with execution_step("tool"):
            writes.append("independently confirmed before cancellation")
            other.cancel(owner, run)
            now[0] += 0.2
        writes.append("must not start")

    with pytest.raises(TaskCancelled):
        service.execute(owner, run, work)
    assert len(writes) == 1
    assert service.read(owner, run).status == "cancelled"
    other.cancel(owner, run)
    assert sum(e.kind == "run_cancelled" for e in service.read(owner, run).events) == 1


def test_completed_cancel_and_duplicate_never_reexecute(runtime):
    from app.domain.errors import DuplicateEventError, NotFoundError

    service, _, _ = runtime
    owner, run = uuid4(), uuid4()
    service.start(owner, run)
    assert service.execute(owner, run, lambda: "PRIVATE_REPLY") == "PRIVATE_REPLY"
    assert service.cancel(owner, run).status == "completed"
    with pytest.raises(DuplicateEventError):
        service.start(owner, run)
    with pytest.raises(DuplicateEventError):
        service.execute(owner, run, lambda: pytest.fail("replayed"))
    with pytest.raises(NotFoundError):
        service.read(uuid4(), run)
    assert "PRIVATE_REPLY" not in service.read(owner, run).model_dump_json()


def test_nested_tool_span_counts_once_and_scrubs_failure(runtime):
    from app.contracts.agent_execution import execution_step

    service, _, now = runtime
    owner, run = uuid4(), uuid4()
    service.start(owner, run)

    def work():
        with execution_step("tool"):
            with execution_step("tool"):
                now[0] += 0.25
                raise RuntimeError("PRIVATE_IMAGE_TOKEN_PROMPT")

    with pytest.raises(RuntimeError):
        service.execute(owner, run, work)
    snapshot = service.read(owner, run)
    assert snapshot.metadata.tool_calls == 1
    assert snapshot.metadata.usage is None and snapshot.metadata.sdk_attempts is None
    assert snapshot.events[-1].kind == "run_failed"
    assert "PRIVATE" not in snapshot.model_dump_json()


def test_cancel_blocks_persistence_even_without_next_tool(runtime):
    from app.application.workflow_message_policy import MessagePersistencePolicy
    from app.contracts.agent_execution import TaskCancelled

    service, _, _ = runtime
    owner, run = uuid4(), uuid4()
    service.start(owner, run)
    writes = []

    def work():
        service.cancel(owner, run)
        MessagePersistencePolicy().write_context(lambda: writes.append(1))

    with pytest.raises(TaskCancelled):
        service.execute(owner, run, work)
    assert not writes


def test_metadata_identifies_actual_working_code_not_only_base_commit(runtime):
    service, _, _ = runtime
    owner, run = uuid4(), uuid4()
    service.start(owner, run)
    metadata = service.read(owner, run).metadata.model_dump()
    assert isinstance(metadata.get("runtime_hash"), str) and len(metadata["runtime_hash"]) == 64


def test_cancel_wins_over_provider_failure_so_fallback_cannot_start(runtime):
    from app.contracts.agent_execution import TaskCancelled, execution_step
    from app.contracts.model import ModelProviderError

    service, _, _ = runtime
    owner, run = uuid4(), uuid4()
    service.start(owner, run)
    fallback = []

    def work():
        try:
            with execution_step("model"):
                service.cancel(owner, run)
                raise ModelProviderError("timeout")
        except ModelProviderError:
            fallback.append(1)

    with pytest.raises(TaskCancelled):
        service.execute(owner, run, work)
    assert not fallback


def test_knowledge_trace_times_the_service_not_just_audit_append(monkeypatch):
    from app.agent.orchestrator import AgentTurn

    from .correctness02_support import OWNER, build_harness

    harness = build_harness()
    try:
        ticks = [100.0]
        monkeypatch.setattr("app.agent.model_tools.monotonic", lambda: ticks[0])
        monkeypatch.setattr("app.agent.registry.monotonic", lambda: ticks[0])
        from app.application.medication_understanding import MedicationUnderstandingService

        original = MedicationUnderstandingService.explain

        def measured(self, **kwargs):
            ticks[0] += 0.125
            return original(self, **kwargs)

        monkeypatch.setattr(MedicationUnderstandingService, "explain", measured)
        harness.tools.execute(
            name="get_medication_understanding",
            arguments={"medication_id": str(harness.plans[0].medication.id), "question": "general_use"},
            patient_id=OWNER,
            session_id=uuid4(),
            correlation_id=uuid4(),
            client_turn_id="DEMO-timing",
            turn=AgentTurn(text="DEMO source read", language="en"),
        )
        assert list(harness.root.store.traces.values())[-1].duration_ms == 125
    finally:
        harness.close()


def test_cancel_preserves_native_confirmed_record_and_blocks_next_write(runtime):
    from app.contracts.agent_execution import TaskCancelled, execution_step
    from app.contracts.observations import ObservationInput
    from app.transport.container import build_container

    service, _, _ = runtime
    c = build_container()
    owner, run, first, second = uuid4(), uuid4(), uuid4(), uuid4()
    service.start(owner, run)
    saved = []

    def work():
        with execution_step("tool"):
            saved.append(
                c.observations.save(
                    owner,
                    ObservationInput(
                        id=first,
                        occurred_at=c.clock.now(),
                        description="DEMO_ONLY confirmed observation",
                        confirmed=True,
                    ),
                )
            )
            service.cancel(owner, run)
        with execution_step("tool"):
            c.observations.save(
                owner,
                ObservationInput(
                    id=second, occurred_at=c.clock.now(), description="DEMO_ONLY must not be saved", confirmed=True
                ),
            )

    try:
        before = dict(c.store.events)
        with pytest.raises(TaskCancelled):
            service.execute(owner, run, work)
        assert c.observations.get(owner, first) == saved[0]
        assert c.observations.get(owner, second) is None
        assert c.store.events == before
        assert service.read(owner, run).metadata.tool_calls == 1
    finally:
        if c.close_request:
            c.close_request()
