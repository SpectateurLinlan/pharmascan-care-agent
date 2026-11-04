"""P03 independent-review findings reproduced across real services and HTTP."""

import json
from uuid import UUID, uuid4

import pytest
from app.agent.conversation import ConversationService
from app.agent.model_tools import ModelTools
from app.contracts.assistant_workflows import WorkflowEvent
from app.contracts.model import FunctionCall, ModelReply
from app.contracts.preferences import PreferenceUpdate
from app.domain.errors import ValidationError
from app.infrastructure.memory_repos import InMemoryAgentSessionRepository


@pytest.mark.parametrize("path", ["fallback", "model", "knowledge"])
def test_revocation_during_reply_prevents_late_history_context_and_trace_content(workflow, monkeypatch, path):
    h = workflow
    owner = h.owner_ids["A"]
    service = h.container.assistant_workflows
    h.container.preferences.save(owner, PreferenceUpdate(conversation_history_enabled=True))
    first = h.start("medication.enroll", {"method": "manual"})
    secret = "DEMO-private-revoked-response"

    def revoke():
        control = service.control(owner, UUID(first["task_id"]))
        service.advance(
            owner,
            control.task_id,
            WorkflowEvent(event_id=uuid4(), expected_revision=control.revision, kind="cancel_save"),
        )

    if path == "fallback":
        original = h.container.orchestrator._router

        class RevokeDuringRoute:
            def route(self, *args):
                revoke()
                return original.route(*args)

        monkeypatch.setattr(h.container.orchestrator, "_router", RevokeDuringRoute())
    else:

        class Model:
            calls = 0

            def create(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    revoke()
                    return ModelReply(
                        calls=[FunctionCall(id="DEMO-read", name="list_active_medications", arguments={})]
                    )
                return ModelReply(text="DEMO read result")

        if path == "knowledge":
            original = h.container.medication_understanding.explain

            def revoke_during_knowledge(*args, **kwargs):
                revoke()
                return original(*args, **kwargs)

            monkeypatch.setattr(h.container.medication_understanding, "explain", revoke_during_knowledge)
        h.container.ai_agent = ConversationService(
            model=Model(),
            fallback=h.container.orchestrator,
            tools=ModelTools(
                registry=h.container.registry,
                fallback=h.container.orchestrator,
                medication_understanding=h.container.medication_understanding,
                clock=h.clock,
            ),
            sessions=InMemoryAgentSessionRepository(h.container.store),
            ids=h.container.ids,
        )
    text = f"What is {secret}?" if path == "knowledge" else f"Check application data: {secret}"
    response = h._request(
        "POST",
        "/api/agent/workflows/messages",
        json={
            "workspace_id": h.workspace_id,
            "task_id": first["task_id"],
            "conversation_id": None,
            "expected_revision": first["revision"],
            "client_turn_id": str(uuid4()),
            "text": text,
        },
    )
    assert not response["reply"]["history_saved"]
    assert secret not in json.dumps(h.snapshot())
    assert all(not row["request_summary"] and not row["response_summary"] for row in h.snapshot()["tool_traces"])


def test_valid_ephemeral_page_fields_survive_an_ordinary_chat_reply(workflow):
    h = workflow
    first = h.start("medication.enroll", save=False)
    response = h._request(
        "POST",
        "/api/agent/workflows/messages",
        json={
            "workspace_id": h.workspace_id,
            "task_id": first["task_id"],
            "client_turn_id": str(uuid4()),
            "text": "Please continue",
            "ephemeral": {
                "capability_id": "medication.enroll",
                "fields": {
                    "method": "manual",
                    "medication_name": "DEMO-page-field",
                },
            },
        },
    )
    assert response["workflow"]["state"] == "collecting"
    assert response["workflow"]["visible_fields"]["medication_name"] == "DEMO-page-field"
    assert "DEMO-page-field" not in json.dumps(h.snapshot())


@pytest.mark.parametrize("save", [True, False])
def test_resume_atomically_suspends_the_previous_foreground(workflow, save):
    h = workflow
    first = h.start("medication.enroll", save=save)
    second = h.start("medication.enroll", save=save)
    suspended = h.view(first["task_id"])
    h._request(
        "POST",
        f"/api/agent/workflows/tasks/{first['task_id']}/events",
        json={
            "event_id": str(uuid4()),
            "expected_revision": suspended["revision"],
            "kind": "resume",
            **({"ephemeral": {"capability_id": "medication.enroll", "fields": {}}} if not save else {}),
        },
    )
    after = h.view(second["task_id"])
    assert after["state"] == "suspended" and after["revision"] > second["revision"]


def test_a_conversation_has_one_foreground_across_different_workspaces(workflow):
    h = workflow
    owner = h.owner_ids["A"]
    h.container.preferences.save(owner, PreferenceUpdate(conversation_history_enabled=True))
    conversation = uuid4()
    h.container.conversation_threads.create(owner, conversation, "DEMO thread", False)
    service = h.container.assistant_workflows
    first = service.start(owner, "medication.enroll", uuid4(), conversation, {})
    service.start(owner, "medication.enroll", uuid4(), conversation, {})
    assert service.view(owner, first.task_id).state == "suspended"


def test_cancel_save_preserves_terminal_status_and_cannot_reopen_task(workflow):
    h = workflow
    first = h.start("medication.enroll")
    cancelled = h.event(first["task_id"], "cancel_task")
    revoked = h.event(first["task_id"], "cancel_save", revision=cancelled["revision"])
    with pytest.raises(ValidationError):
        h.container.assistant_workflows.advance(
            h.owner_ids["A"],
            UUID(first["task_id"]),
            WorkflowEvent(
                event_id=uuid4(),
                expected_revision=revoked["revision"],
                kind="provide_fields",
                values={"method": "manual"},
            ),
            ephemeral={"capability_id": "medication.enroll", "fields": {}},
        )
    assert h.view(first["task_id"])["state"] == "cancelled"


def test_saving_a_temporary_task_establishes_a_consistent_conversation_binding(workflow):
    h = workflow
    h.container.preferences.save(h.owner_ids["A"], PreferenceUpdate(conversation_history_enabled=True))
    first = h.start("medication.enroll", save=False)
    saved = h._request(
        "POST",
        f"/api/agent/workflows/tasks/{first['task_id']}/events",
        json={
            "event_id": str(uuid4()),
            "expected_revision": first["revision"],
            "kind": "allow_save",
            "ephemeral": {"capability_id": "medication.enroll", "fields": {"method": "manual"}},
        },
    )
    one = h._request(
        "POST",
        "/api/agent/workflows/messages",
        json={
            "workspace_id": h.workspace_id,
            "task_id": first["task_id"],
            "conversation_id": None,
            "expected_revision": saved["revision"],
            "client_turn_id": str(uuid4()),
            "text": "List my medications",
        },
    )
    two = h._request(
        "POST",
        "/api/agent/workflows/messages",
        json={
            "workspace_id": h.workspace_id,
            "task_id": first["task_id"],
            "conversation_id": one["reply"]["conversation_id"],
            "expected_revision": one["workflow"]["revision"],
            "client_turn_id": str(uuid4()),
            "text": "List my medications",
        },
    )
    assert one["reply"]["conversation_id"] and two["reply"]["conversation_id"] == one["reply"]["conversation_id"]


def test_revoked_request_cannot_materialize_dose_occurrences_through_a_read_tool(workflow):
    from app.agent.tools import CheckDueDoseRequest
    from app.contracts.enums import ToolName, ToolStatus

    h = workflow
    h.seed_reviewed_medication()
    h.clock.advance(seconds=3 * 86400)
    owner = h.owner_ids["A"]
    first = h.start("medication.enroll")
    task = UUID(first["task_id"])
    session = h.container.orchestrator.start_session(patient_id=owner)
    h.event(first["task_id"], "cancel_save")
    before = set(h.container.store.occurrences)
    request = CheckDueDoseRequest(
        patient_id=owner,
        session_id=session.id,
        correlation_id=uuid4(),
        client_turn_id="DEMO-late-read",
        content_guard=lambda write: h.container.assistant_workflows.guarded_write(
            owner, task, first["revision"], write
        ),
    )
    result = h.container.registry.execute(ToolName.CHECK_DUE_DOSE, request)
    assert result.status == ToolStatus.BLOCKED
    assert set(h.container.store.occurrences) == before
