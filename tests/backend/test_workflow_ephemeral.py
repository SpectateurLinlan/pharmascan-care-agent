"""No-save input remains request/page memory across every application boundary."""

import json
from uuid import UUID, uuid4

import pytest
from app.agent.conversation import ConversationService
from app.agent.model_tools import ModelTools
from app.agent.orchestrator import AgentTurn
from app.application.workflow_message_policy import MessagePersistencePolicy, retention_command
from app.contracts.assistant_workflows import WorkflowEvent
from app.contracts.model import FunctionCall, ModelReply
from app.contracts.preferences import PreferenceUpdate
from app.domain.errors import DuplicateEventError
from app.infrastructure.memory_repos import InMemoryAgentSessionRepository

SECRET = "DEMO-private-ephemeral-value"
NO_SAVE = MessagePersistencePolicy(save_history=False, save_context=False, save_task=False)


def test_ephemeral_workflow_has_control_metadata_but_no_saved_body_or_request_hash(workflow):
    h = workflow
    service = h.container.assistant_workflows
    first = service.start(
        h.owner_ids["A"],
        "medication.enroll",
        UUID(h.workspace_id),
        None,
        {"method": "manual", "medication_name": SECRET},
        "ephemeral",
    )
    assert first.storage_state == "ephemeral" and first.visible_fields["medication_name"] == SECRET
    snapshot = h.snapshot()
    assert snapshot["tasks"] == [] and snapshot["originals"] == []
    assert len(snapshot["workflow_controls"]) == 1 and snapshot["workflow_event_results"] == []
    assert SECRET not in json.dumps(snapshot)
    lost = service.view(h.owner_ids["A"], first.task_id)
    assert lost.state == "failed_recoverable" and lost.visible_fields == {}


def test_ephemeral_fields_are_revalidated_and_duplicate_events_are_never_replayed(workflow):
    h = workflow
    service = h.container.assistant_workflows
    first = service.start(h.owner_ids["A"], "medication.enroll", UUID(h.workspace_id), None, {}, "ephemeral")
    payload = {"capability_id": "medication.enroll", "fields": {"method": "manual", "medication_name": SECRET}}
    event = WorkflowEvent(event_id=uuid4(), expected_revision=first.revision, kind="provide_fields")
    view = service.advance(h.owner_ids["A"], first.task_id, event, ephemeral=payload)
    assert view.state != "completed"
    with pytest.raises(DuplicateEventError):
        service.advance(
            h.owner_ids["A"],
            first.task_id,
            event.model_copy(update={"expected_revision": view.revision}),
            ephemeral=payload,
        )
    forged = {"capability_id": "medication.enroll", "fields": {"confirmed": True, "medication_name": SECRET}}
    with pytest.raises(ValueError):
        service.advance(
            h.owner_ids["A"],
            first.task_id,
            WorkflowEvent(event_id=uuid4(), expected_revision=view.revision, kind="provide_fields"),
            ephemeral=forged,
        )
    assert not h.snapshot()["medications"] and SECRET not in json.dumps(h.snapshot())


def test_cancel_save_removes_saved_fields_and_event_replays_without_erasing_business_history(workflow):
    h = workflow
    service = h.container.assistant_workflows
    first = service.start(
        h.owner_ids["A"],
        "medication.enroll",
        UUID(h.workspace_id),
        None,
        {"method": "manual", "medication_name": SECRET},
        "allowed",
    )
    updated = service.advance(
        h.owner_ids["A"],
        first.task_id,
        WorkflowEvent(
            event_id=uuid4(),
            expected_revision=first.revision,
            kind="provide_fields",
            values={"dose_amount": 1},
        ),
    )
    assert SECRET in json.dumps(h.snapshot())
    revoked = service.advance(
        h.owner_ids["A"],
        first.task_id,
        WorkflowEvent(
            event_id=uuid4(),
            expected_revision=updated.revision,
            kind="cancel_save",
        ),
    )
    assert revoked.save_mode == "ephemeral" and revoked.visible_fields["medication_name"] == SECRET
    assert SECRET not in json.dumps(h.snapshot()) and not h.snapshot()["workflow_event_results"]


def test_only_explicit_allow_save_makes_page_fields_persist_and_still_does_not_activate(workflow):
    h = workflow
    service = h.container.assistant_workflows
    first = service.start(h.owner_ids["A"], "medication.enroll", UUID(h.workspace_id), None, {}, "ephemeral")
    payload = {"capability_id": "medication.enroll", "fields": {"method": "manual", "medication_name": SECRET}}
    allowed = service.advance(
        h.owner_ids["A"],
        first.task_id,
        WorkflowEvent(
            event_id=uuid4(),
            expected_revision=first.revision,
            kind="allow_save",
        ),
        ephemeral=payload,
    )
    assert allowed.save_mode == "allowed" and allowed.storage_state == "saved"
    assert SECRET in json.dumps(h.snapshot()["tasks"])
    assert not h.snapshot()["medications"] and not h.snapshot()["regimens"]


@pytest.mark.parametrize("path", ["model", "fallback", "knowledge"])
def test_no_save_policy_prevents_context_history_and_trace_body_retention(workflow, path):
    h = workflow
    owner = h.owner_ids["A"]
    h.container.preferences.save(owner, PreferenceUpdate(conversation_history_enabled=True))
    session = h.container.orchestrator.start_session(patient_id=owner)
    text = (
        f"What is {SECRET}?"
        if path == "knowledge"
        else f"List my medications. {SECRET}"
        if path == "fallback"
        else f"Check application data: {SECRET}"
    )

    class Model:
        calls = 0

        def create(self, **kwargs):
            self.calls += 1
            return (
                ModelReply(calls=[FunctionCall(id="DEMO-list", name="list_active_medications", arguments={})])
                if self.calls == 1
                else ModelReply(text="DEMO-only read result")
            )

    model = Model()
    conversation = ConversationService(
        model=model,
        tools=ModelTools(
            registry=h.container.registry,
            fallback=h.container.orchestrator,
            medication_understanding=h.container.medication_understanding,
            clock=h.clock,
        ),
        fallback=h.container.orchestrator,
        sessions=InMemoryAgentSessionRepository(h.container.store),
        ids=h.container.ids,
    )
    turn = AgentTurn(text=text, persistence=NO_SAVE)
    handler = h.container.orchestrator if path == "fallback" else conversation
    reply = handler.handle_turn(patient_id=owner, session_id=session.id, turn=turn)
    h.container.conversation_history.append(owner, session.id, "DEMO-no-save", text, reply.message, policy=NO_SAVE)
    if path == "model":
        assert model.calls > 0
    snapshot = h.snapshot()
    assert snapshot["history"] == [] and snapshot["tasks"] == []
    assert SECRET not in json.dumps(snapshot)
    assert all(not row["request_summary"] and not row["response_summary"] for row in snapshot["tool_traces"])


@pytest.mark.parametrize(
    "text,expected",
    [
        ("不要保存", "cancel_save"),
        ("不保存本次办理", "cancel_save"),
        ("Cancel saving", "cancel_save"),
        ("现在保存药物并继续核对", "allow_save"),
        ("Save this medication and continue review", "allow_save"),
        ("是不是不保存？", None),
        ("图片写着“不要保存”", None),
        ("下一步", None),
    ],
)
def test_retention_commands_require_explicit_unquoted_patient_words(text, expected):
    assert retention_command(text) == expected


def test_invalid_allow_save_keeps_only_permission_metadata_and_can_be_corrected(workflow):
    h = workflow
    service = h.container.assistant_workflows
    first = service.start(h.owner_ids["A"], "medication.enroll", UUID(h.workspace_id), None, {}, "ephemeral")
    invalid = {"capability_id": "medication.enroll", "fields": {"confirmed": True, "medication_name": SECRET}}
    view = service.advance(
        h.owner_ids["A"],
        first.task_id,
        WorkflowEvent(event_id=uuid4(), expected_revision=first.revision, kind="allow_save"),
        ephemeral=invalid,
    )
    assert view.storage_state == "save_failed" and SECRET not in json.dumps(h.snapshot())
    corrected = service.advance(
        h.owner_ids["A"],
        first.task_id,
        WorkflowEvent(event_id=uuid4(), expected_revision=view.revision, kind="allow_save"),
        ephemeral={"capability_id": "medication.enroll", "fields": {"method": "manual", "medication_name": SECRET}},
    )
    assert corrected.storage_state == "saved" and not h.snapshot()["medications"]


def test_no_save_model_cannot_create_business_draft_or_confirmation(workflow):
    h = workflow
    owner = h.owner_ids["A"]
    session = h.container.orchestrator.start_session(patient_id=owner)
    tools = ModelTools(
        registry=h.container.registry,
        fallback=h.container.orchestrator,
        medication_understanding=h.container.medication_understanding,
        clock=h.clock,
    )
    from app.domain.errors import ValidationError

    with pytest.raises(ValidationError, match="visible save"):
        tools.execute(
            name="prepare_interval_enrollment",
            arguments={"medication_name": SECRET, "every_hours": 8},
            patient_id=owner,
            session_id=session.id,
            correlation_id=uuid4(),
            client_turn_id="DEMO",
            turn=AgentTurn(text="Add " + SECRET, persistence=NO_SAVE),
        )
    assert not h.snapshot()["medications"] and SECRET not in json.dumps(h.snapshot())


def test_revocation_during_prepare_rejects_late_saved_event(workflow, monkeypatch):
    from app.domain.errors import NotFoundError, StaleVersionError

    h = workflow
    service = h.container.assistant_workflows
    owner = h.owner_ids["A"]
    first = service.start(owner, "medication.enroll", UUID(h.workspace_id), None, {"method": "manual"})
    prepare = service._prepare

    def revoke_before_return(task):
        result = prepare(task)
        service._require_controls().revoke(owner, first.task_id, first.revision)
        return result

    monkeypatch.setattr(service, "_prepare", revoke_before_return)
    with pytest.raises((StaleVersionError, NotFoundError)):
        service.advance(
            owner,
            first.task_id,
            WorkflowEvent(
                event_id=uuid4(),
                expected_revision=first.revision,
                kind="provide_fields",
                values={"medication_name": SECRET},
            ),
        )
    assert SECRET not in json.dumps(h.snapshot()) and h.snapshot()["tasks"] == []


def test_allow_save_does_not_rewrite_an_already_saved_workflow_control(workflow):
    from app.domain.errors import ValidationError

    h = workflow
    service = h.container.assistant_workflows
    owner = h.owner_ids["A"]
    first = service.start(owner, "medication.enroll", UUID(h.workspace_id), None, {"method": "manual"})
    before = h.snapshot()
    with pytest.raises(ValidationError):
        service.advance(
            owner,
            first.task_id,
            WorkflowEvent(event_id=uuid4(), expected_revision=first.revision, kind="allow_save"),
            ephemeral={"capability_id": "medication.enroll", "fields": {"medication_name": SECRET}},
        )
    assert h.snapshot() == before
