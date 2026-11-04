"""Local release rehearsal on one injected synthetic memory state; no restart/SQL."""

from dataclasses import replace
from uuid import uuid4

from app.application.agent_execution import AgentExecutionService
from app.infrastructure.memory_agent_runs import MemoryRunRepository
from app.infrastructure.memory_workflows import MemoryWorkflowState

from .test_workflow_originals import original_png


def test_disabling_progress_composition_preserves_saved_task_and_original(workflow):
    h = workflow
    h.container.assistant_execution = AgentExecutionService(MemoryRunRepository(MemoryWorkflowState()))
    task = h.start("medication.enroll", {"method": "photo"})
    uploaded = h.upload(task["task_id"], original_png())
    identifier = uploaded["attachment"]["id"]
    saved = h.view(task["task_id"])
    assert h._request("GET", "/api/agent/workflows/capabilities")["progress_enabled"] is True
    h.container.assistant_execution = None
    manifest = h._request("GET", "/api/agent/workflows/capabilities")
    assert manifest["enabled"] and manifest["progress_enabled"] is False
    assert h.view(task["task_id"]) == saved
    assert h.read_original(identifier) == original_png()
    status = h.client.get(f"/api/agent/workflows/runs/{uuid4()}", params={"client_id": "DEMO-workflow-A"})
    assert status.status_code == 503
    old = h._request(
        "POST", "/api/agent/messages", json={"text": "List my medications", "client_turn_id": str(uuid4())}
    )
    assert old["session_id"] and "workflow" not in old
    current = h._request(
        "POST",
        "/api/agent/workflows/messages",
        json={"text": "DEMO continuation", "workspace_id": h.workspace_id, "client_turn_id": str(uuid4())},
    )
    assert current["reply"]["session_id"]
    assert h.read_original(identifier) == original_png()


def test_assistant_entrypoint_removal_preserves_native_draft_and_can_restore_same_state(workflow):
    h = workflow
    task = h.start(
        "medication.enroll",
        {
            "method": "manual",
            "medication_name": "DEMO release recovery",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_rule": {"kind": "daily", "local_times": ["08:00"]},
        },
    )
    prepared = h.event(task["task_id"], "prepare_confirmation")
    reference = prepared["result_ref"]["id"]
    before = h._request("GET", f"/api/medications/drafts/{reference}")
    original = h.container
    # This only removes the message/task entry point from the same injected
    # services. It is not a settings restart or persistent rollback proof.
    off = replace(original, assistant_workflows=None, assistant_execution=None)
    h.client.app.state.container = off
    try:
        assert h._request("GET", "/api/agent/workflows/capabilities")["enabled"] is False
        assert h._request("GET", f"/api/medications/drafts/{reference}") == before
        blocked = h.client.get(f"/api/agent/workflows/tasks/{task['task_id']}", params={"client_id": "DEMO-workflow-A"})
        assert blocked.status_code == 503
        old = h._request(
            "POST", "/api/agent/messages", json={"text": "List my medications", "client_turn_id": str(uuid4())}
        )
        assert old["session_id"] and "workflow" not in old
    finally:
        h.client.app.state.container = original
    assert h.view(task["task_id"])["result_ref"] == prepared["result_ref"]
    assert h._request("GET", f"/api/medications/drafts/{reference}") == before


def test_old_message_shape_and_new_json_retain_native_reply_contract(workflow):
    h = workflow
    h.container.assistant_execution = AgentExecutionService(MemoryRunRepository(MemoryWorkflowState()))
    message = {"text": "List my medications", "client_turn_id": str(uuid4())}
    old = h._request("POST", "/api/agent/messages", json=message)
    current = h._request(
        "POST",
        "/api/agent/workflows/messages",
        json={**message, "workspace_id": h.workspace_id, "client_turn_id": str(uuid4())},
    )
    assert old["session_id"] and current["reply"]["session_id"]
    # Both remain real validated replies; workflow-enabled routing may choose
    # a dedicated entry, so do not equate wording or mode across the two paths.
    assert {"message", "mode", "tool_traces"} <= old.keys()
    assert {"message", "mode", "tool_traces"} <= current["reply"].keys()
    assert not h.snapshot()["dose_events"]
