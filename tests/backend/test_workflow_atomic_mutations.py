"""Explicit atomic workflow commands, synthetic state and recording Data API."""

import importlib
import importlib.util
import json
from uuid import uuid4

import httpx
import pytest
from app.contracts.agent_execution import ExecutionBudget, RunMetadata, RunRecord
from app.contracts.assistant_workflows import WorkflowTask, WorkflowUpdate
from app.domain.errors import StaleVersionError
from app.infrastructure.memory_workflows import MemoryWorkflowState
from app.infrastructure.supabase_data import SupabaseDataClient
from pydantic import ValidationError

from .conftest import FixedClock


def api(module, name):
    imported = importlib.import_module(module)
    assert hasattr(imported, name), f"Missing atomic workflow contract: {name}"
    return getattr(imported, name)


def memory():
    cls = api("app.infrastructure.memory_workflows", "MemoryWorkflowMutations")
    state, clock = MemoryWorkflowState(), FixedClock()
    return cls(clock, state=state), state, clock


def command(name, **values):
    return api("app.contracts.workflow_persistence", name)(**values)


def task(clock, owner=None):
    return WorkflowTask(
        id=uuid4(),
        owner=owner or uuid4(),
        workspace_id=uuid4(),
        capability_id="medication.enroll",
        fields={"method": "manual", "medication_name": "DEMO-private-input"},
        updated_at=clock.now(),
    )


def test_cancelled_run_prevents_content_mutation():
    port, state, clock = memory()
    row = task(clock)
    port.apply(row.owner, command("StartSavedWorkflow", task=row))
    run_id = uuid4()
    state.runs[(row.owner, run_id)] = RunRecord(
        budget=ExecutionBudget(deadline_monotonic=45),
        started_monotonic=0,
        metadata=RunMetadata(run_id=run_id),
        status="cancelled",
    )
    with pytest.raises(StaleVersionError):
        port.apply(
            row.owner,
            command(
                "AdvanceWorkflow",
                task_id=row.id,
                expected_revision=1,
                event_id=uuid4(),
                update=WorkflowUpdate(
                    state="collecting",
                    save_mode="allowed",
                    storage_state="saved",
                    fields={"method": "manual", "medication_name": "DEMO-new"},
                ),
                request_digest="b" * 64,
                run_binding={"run_id": run_id, "epoch": 1},
            ),
        )
    assert state.tasks[(row.owner, row.id)].fields["medication_name"] == "DEMO-private-input"


def test_saved_to_ephemeral_never_keeps_body_or_digest():
    port, state, clock = memory()
    row = task(clock)
    port.apply(row.owner, command("StartSavedWorkflow", task=row, event_id=uuid4(), request_digest="a" * 64))
    result = port.apply(row.owner, command("RevokeWorkflow", task_id=row.id, expected_revision=1, event_id=uuid4()))
    assert result.mode == "ephemeral" and result.revoked
    assert state.tasks == {} and state.events == {}
    assert "DEMO-private-input" not in json.dumps([x.model_dump(mode="json") for x in state.controls.values()])
    assert all(len(key) == 3 for key in state.used)


def test_resume_handoff_validates_both_revisions_before_changing_either_task():
    port, state, clock = memory()
    source, target = task(clock), task(clock)
    target = target.model_copy(update={"owner": source.owner})
    port.apply(source.owner, command("StartSavedWorkflow", task=source))
    port.apply(source.owner, command("StartSavedWorkflow", task=target))
    before = dict(state.tasks)
    with pytest.raises(StaleVersionError):
        port.apply(
            source.owner,
            command(
                "ResumeWorkflowHandoff",
                task_id=source.id,
                expected_revision=1,
                target_task_id=target.id,
                target_revision=42,
                event_id=uuid4(),
            ),
        )
    assert state.tasks == before


def test_resume_handoff_updates_both_tasks_under_one_memory_transaction():
    port, state, clock = memory()
    source, target = task(clock), task(clock)
    target = target.model_copy(update={"owner": source.owner})
    port.apply(source.owner, command("StartSavedWorkflow", task=source))
    port.apply(source.owner, command("StartSavedWorkflow", task=target))
    result = port.apply(
        source.owner,
        command(
            "ResumeWorkflowHandoff",
            task_id=source.id,
            expected_revision=1,
            target_task_id=target.id,
            target_revision=1,
            event_id=uuid4(),
        ),
    )
    assert result.id == target.id and result.revision == 2
    assert state.tasks[(source.owner, source.id)].state == "suspended"


def test_receipt_claim_does_not_authorize_domain_write():
    parse = api("app.contracts.workflow_persistence", "parse_workflow_mutation")
    with pytest.raises(ValidationError):
        parse({"kind": "action_complete", "state": "succeeded", "confirmed": True})


def test_resume_handoff_is_one_versioned_rpc_and_never_sends_an_owner():
    cls = api("app.infrastructure.workflow_repos", "SupabaseWorkflowMutations")
    clock, calls = FixedClock(), []
    row = task(clock)
    other = uuid4()

    def remote(request):
        calls.append(request)
        return httpx.Response(200, json={"result": row.model_copy(update={"revision": 2}).model_dump(mode="json")})

    data = SupabaseDataClient(
        base_url="https://demo-test.supabase.co",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=row.owner,
        client=httpx.Client(transport=httpx.MockTransport(remote)),
    )
    result = cls(data).apply(
        row.owner,
        command(
            "ResumeWorkflowHandoff",
            task_id=other,
            expected_revision=1,
            target_task_id=row.id,
            target_revision=1,
            event_id=uuid4(),
        ),
    )
    assert result.id == row.id and len(calls) == 1
    assert calls[0].url.path == "/rest/v1/rpc/assistant_workflow_mutate"
    body = json.loads(calls[0].content)["p_command"]
    assert body["kind"] == "resume_handoff" and "owner" not in body


def test_ephemeral_start_accepts_only_content_free_control():
    cls = api("app.contracts.workflow_persistence", "StartEphemeralWorkflow")
    from app.contracts.assistant_workflows import ControlReceipt

    with pytest.raises(ValidationError):
        cls(
            control=ControlReceipt(owner=uuid4(), task_id=uuid4(), capability_id="medication.enroll"),
            fields={"medication_name": "DEMO-secret"},
        )


def test_real_service_routes_saved_updates_and_privacy_through_atomic_port(workflow):
    from app.agent.capabilities import build_capability_registry
    from app.application.assistant_capabilities.enrollment import EnrollmentAdapter
    from app.application.assistant_workflows import WorkflowService
    from app.contracts.assistant_workflows import WorkflowEvent
    from app.infrastructure.memory_workflows import MemoryControlRepository, MemoryWorkflowRepository

    port, state, _ = memory()
    calls = []

    class RecordingPort:
        def apply(self, owner, operation):
            calls.append(operation.kind)
            return port.apply(owner, operation)

        def read_receipt(self, owner, action_key):
            return port.read_receipt(owner, action_key)

    service = WorkflowService(
        repository=MemoryWorkflowRepository(workflow.clock, state=state),
        registry=build_capability_registry(),
        adapters={"medication.enroll": EnrollmentAdapter(workflow.container.enrollment)},
        clock=workflow.clock,
        ids=workflow.container.ids,
        conversations=workflow.container.conversation_threads,
        preferences=workflow.container.preferences,
        controls=MemoryControlRepository(workflow.clock, state=state),
        mutations=RecordingPort(),
    )
    owner = workflow.owner_ids["A"]
    first = service.start(owner, "medication.enroll", uuid4(), None, {"method": "manual"})
    updated = service.advance(
        owner,
        first.task_id,
        WorkflowEvent(
            event_id=uuid4(),
            expected_revision=first.revision,
            kind="provide_fields",
            values={"medication_name": "DEMO-private-input"},
        ),
    )
    assert updated.visible_fields["medication_name"] == "DEMO-private-input"
    cleared = service.advance(
        owner, first.task_id, WorkflowEvent(event_id=uuid4(), expected_revision=updated.revision, kind="cancel_save")
    )
    assert cleared.save_mode == "ephemeral" and state.tasks == {} and state.events == {}
    assert calls == ["start", "advance", "revoke"]


def test_generic_task_update_cannot_publish_a_business_completion():
    port, state, clock = memory()
    row = task(clock)
    port.apply(row.owner, command("StartSavedWorkflow", task=row))
    from app.domain.errors import ValidationError as DomainValidationError

    with pytest.raises(DomainValidationError):
        port.apply(
            row.owner,
            command(
                "AdvanceWorkflow",
                task_id=row.id,
                expected_revision=1,
                event_id=uuid4(),
                update=WorkflowUpdate(state="completed", save_mode="allowed", storage_state="saved", fields=row.fields),
                request_digest="a" * 64,
            ),
        )
    assert state.tasks[(row.owner, row.id)].state != "completed"
