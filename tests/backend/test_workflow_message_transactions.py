"""DEMO_ONLY retention transactions over real local services and a recording wire."""

import importlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from app.application.workflow_message_policy import MessagePersistencePolicy
from app.contracts.dto import AgentSessionDTO
from app.domain.errors import ProviderUnavailableError, StaleVersionError
from app.infrastructure.memory_repos import InMemoryAgentSessionRepository, InMemoryStore
from app.infrastructure.supabase_data import SupabaseDataClient


def contract(name, **values):
    from importlib.util import find_spec

    path = "app.contracts.workflow_messages"
    assert find_spec(path), "Missing typed conversation transaction contracts"
    return getattr(importlib.import_module(path), name)(**values)


def session(owner):
    now = datetime(2026, 10, 28, tzinfo=UTC)
    return AgentSessionDTO(
        id=uuid4(),
        patient_id=owner,
        intent=None,
        state="collecting",
        updated_at=now,
        expires_at=now + timedelta(minutes=15),
    )


def remote_port(owner, response, calls):
    module = importlib.import_module("app.infrastructure.workflow_message_repos")

    def remote(request):
        calls.append(request)
        return httpx.Response(200, json=response)

    return module.SupabaseConversationPersistence(
        SupabaseDataClient(
            base_url="https://demo-test.supabase.co",
            publishable_key="sb_publishable_DEMO",
            access_token="DEMO-token",
            patient_id=owner,
            client=httpx.Client(transport=httpx.MockTransport(remote)),
        )
    )


def test_no_save_fences_every_content_writer():
    owner, calls = uuid4(), []
    row = session(owner)
    command = contract("CreateSession", session=row)
    port = remote_port(owner, {"result": {"kind": "ack"}}, calls)
    policy = MessagePersistencePolicy(save_history=False, save_context=False, save_task=False, messages=port)
    assert policy.execute(owner, command) is None
    assert calls == []
    store = InMemoryStore()
    assert not policy.persist_session(InMemoryAgentSessionRepository(store), row, create=True)
    assert store.sessions == {}


def test_revoked_append_is_rejected_without_legacy_fallback():
    owner, calls = uuid4(), []
    row = session(owner)
    port = remote_port(owner, {"error": "stale"}, calls)
    policy = MessagePersistencePolicy(messages=port)
    store = InMemoryStore()
    with pytest.raises(StaleVersionError):
        policy.persist_session(InMemoryAgentSessionRepository(store), row)
    assert len(calls) == 1 and store.sessions == {}
    assert calls[0].url.path == "/rest/v1/rpc/assistant_message_command"


def test_remote_policy_refuses_unconverted_python_write_callbacks():
    owner, calls = uuid4(), []
    command = contract("CreateSession", session=session(owner))
    policy = MessagePersistencePolicy(messages=remote_port(owner, {"result": {"kind": "ack"}}, calls))
    writes = []
    with pytest.raises(ProviderUnavailableError):
        policy.write_context(lambda: writes.append("DEMO-body"))
    assert writes == [] and calls == []
    assert policy.execute(owner, command).kind == "ack"


def test_typed_session_wire_cannot_choose_patient_identity():
    import json

    owner, calls = uuid4(), []
    row = session(owner)
    command = contract("CreateSession", session=row)
    port = remote_port(owner, {"result": {"kind": "ack"}}, calls)
    result = port.execute(owner, command)
    assert result.kind == "ack"
    body = json.loads(calls[0].content)["p_command"]
    assert "patient_id" not in body["session"] and "owner" not in body


def test_clear_keeps_native_business_records(workflow):
    owner = workflow.owner_ids["A"]
    command = contract("ClearConversationHistory", confirmed=True)
    module = importlib.import_module("app.infrastructure.workflow_message_repos")
    from app.infrastructure.conversation_history import MemoryConversationHistory
    from app.infrastructure.conversation_threads import MemoryConversationThreads
    from app.infrastructure.memory_workflows import MemoryWorkflowState

    store = workflow.container.store
    from app.contracts.dto import PatientMedicationDTO

    medication = PatientMedicationDTO(id=uuid4(), patient_id=owner, display_name="DEMO-preserve-native-medication")
    store.medications[(owner, medication.id)] = medication
    sessions = InMemoryAgentSessionRepository(store)
    history = MemoryConversationHistory(clear_context=sessions.clear_conversation_text)
    port = module.MemoryConversationPersistence(
        state=MemoryWorkflowState(),
        sessions=sessions,
        threads=MemoryConversationThreads(),
        history=history,
        preferences=workflow.container.preferences,
    )
    before = dict(store.medications)
    assert port.execute(owner, command).kind == "ack"
    assert dict(store.medications) == before and before


def test_duplicate_turn_has_one_saved_result(workflow):
    owner = workflow.owner_ids["A"]
    now = workflow.clock.now()
    from app.contracts.preferences import PreferenceUpdate

    workflow.container.preferences.save(owner, PreferenceUpdate(conversation_history_enabled=True))
    contract("ConversationWriteScope")
    module = importlib.import_module("app.infrastructure.workflow_message_repos")
    from app.contracts.conversation_threads import ConversationMessage, ConversationSummary
    from app.infrastructure.conversation_history import MemoryConversationHistory
    from app.infrastructure.conversation_threads import MemoryConversationThreads
    from app.infrastructure.memory_workflows import MemoryWorkflowState

    store, threads = InMemoryStore(), MemoryConversationThreads()
    port = module.MemoryConversationPersistence(
        state=MemoryWorkflowState(),
        sessions=InMemoryAgentSessionRepository(store),
        threads=threads,
        history=MemoryConversationHistory(),
        preferences=workflow.container.preferences,
    )
    conversation = ConversationSummary(id=uuid4(), title="DEMO-thread", created_at=now, updated_at=now)
    port.execute(owner, contract("CreateConversation", conversation=conversation))
    turn = uuid4()
    port.execute(
        owner, contract("ClaimConversationTurn", conversation_id=conversation.id, turn_id=turn, digest="a" * 64)
    )
    message = ConversationMessage(
        id=turn, conversation_id=conversation.id, user_text="DEMO-input", assistant_text="DEMO-reply", created_at=now
    )
    active = session(owner).model_copy(update={"conversation_id": conversation.id})
    port.execute(owner, contract("CreateSession", session=active))
    command = contract("AppendConversationTurn", session_id=active.id, message=message)
    first, duplicate = port.execute(owner, command), port.execute(owner, command)
    assert first.message == duplicate.message and len(threads.messages(owner, conversation.id, None, 20)) == 1


def test_orchestrator_does_not_create_a_session_when_content_saving_is_forbidden(workflow):
    owner = workflow.owner_ids["A"]
    policy = MessagePersistencePolicy(save_context=False, save_history=False, save_task=False)
    created = workflow.container.orchestrator.start_session(patient_id=owner, persistence=policy)
    assert workflow.container.orchestrator.get_session(patient_id=owner, session_id=created.id) is None


def test_actual_message_service_uses_typed_port_for_thread_context_and_history(workflow):
    from app.application.assistant_messages import AssistantMessageService
    from app.application.conversation_history import ConversationHistoryService
    from app.application.conversation_threads import ConversationThreadService
    from app.contracts.assistant_workflows import WorkflowMessageInput
    from app.contracts.preferences import PreferenceUpdate
    from app.infrastructure.conversation_history import MemoryConversationHistory
    from app.infrastructure.conversation_threads import MemoryConversationThreads
    from app.infrastructure.memory_workflows import MemoryWorkflowState

    module = importlib.import_module("app.infrastructure.workflow_message_repos")
    owner = workflow.owner_ids["A"]
    workflow.container.preferences.save(owner, PreferenceUpdate(conversation_history_enabled=True))
    sessions = InMemoryAgentSessionRepository(workflow.container.store)
    threads, history = (
        MemoryConversationThreads(),
        MemoryConversationHistory(clear_context=sessions.clear_conversation_text),
    )
    port = module.MemoryConversationPersistence(
        state=MemoryWorkflowState(),
        sessions=sessions,
        threads=threads,
        history=history,
        preferences=workflow.container.preferences,
    )
    service = AssistantMessageService(
        orchestrator=workflow.container.orchestrator,
        handler=None,
        enrollment=workflow.container.enrollment,
        self_report=workflow.container.self_report,
        preferences=workflow.container.preferences,
        conversation_threads=ConversationThreadService(
            threads, sessions, workflow.clock, workflow.container.preferences
        ),
        conversation_history=ConversationHistoryService(history, workflow.clock),
        clock=workflow.clock,
        workflows=None,
        message_persistence=port,
    )
    reply = service.handle(owner, WorkflowMessageInput(text="Hello", threaded=True, client_turn_id=str(uuid4())))
    assert reply.history_saved is True and reply.conversation_id is not None
    messages = threads.messages(owner, reply.conversation_id, None, 20)
    assert len(messages) == 1 and messages[0].user_text == "Hello"
    stored = sessions.get(owner, reply.reply.session_id)
    assert stored.conversation_id == reply.conversation_id


@pytest.mark.parametrize("saving", [True, False])
def test_real_tool_trace_never_falls_back_to_unbound_repository(workflow, saving):
    from app.agent.tools import ListActiveMedicationsRequest
    from app.contracts.enums import ToolName, ToolStatus

    owner, calls = workflow.owner_ids["A"], []
    policy = MessagePersistencePolicy(
        save_context=saving, messages=remote_port(owner, {"result": {"kind": "ack"}}, calls)
    )
    request = ListActiveMedicationsRequest(
        patient_id=owner,
        session_id=uuid4(),
        correlation_id=uuid4(),
        client_turn_id="DEMO-trace",
        trace_writer=policy.trace_writer,
    )
    before = dict(workflow.container.store.traces)
    result = workflow.container.registry.execute(ToolName.LIST_ACTIVE_MEDICATIONS, request)
    assert result.status == ToolStatus.SUCCESS
    assert dict(workflow.container.store.traces) == before
    assert len(calls) == (1 if saving else 0)


def test_message_sql_candidate_preserves_clinical_tables_and_uses_one_fence():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "supabase/review/assistant_workflows"
    up, down = root / "messages.up.sql", root / "messages.down.sql"
    assert up.exists() and down.exists(), "Missing closed message transaction SQL candidates"
    sql = up.read_text(encoding="utf-8")
    assert "pg_advisory_xact_lock" in sql and "auth.uid()" in sql
    assert "assistant_message_owner" in sql and "FROM PUBLIC" in sql
    assert "public.assistant_run_assert_current" in sql
    assert "public.clear_conversation_history()" in sql
    assert "UPDATE public.assistant_workflow_tasks" in sql  # detach FK before clearing thread metadata
    assert "DELETE FROM public.patient_medications" not in sql
    assert "DROP TABLE" not in down.read_text(encoding="utf-8")


def test_clear_detaches_session_and_task_links_without_losing_task_fields(workflow):
    from app.contracts.assistant_workflows import WorkflowTask
    from app.contracts.conversation_threads import ConversationSummary
    from app.infrastructure.conversation_history import MemoryConversationHistory
    from app.infrastructure.conversation_threads import MemoryConversationThreads
    from app.infrastructure.memory_workflows import MemoryWorkflowRepository, MemoryWorkflowState

    owner = workflow.owner_ids["A"]
    state, threads, store = MemoryWorkflowState(), MemoryConversationThreads(), InMemoryStore()
    sessions = InMemoryAgentSessionRepository(store)
    conversation = ConversationSummary(
        id=uuid4(), title="DEMO-previously-consented", created_at=workflow.clock.now(), updated_at=workflow.clock.now()
    )
    threads.create(owner, conversation)
    current = session(owner).model_copy(update={"conversation_id": conversation.id})
    sessions.add(current)
    task = WorkflowTask(
        id=uuid4(),
        owner=owner,
        workspace_id=uuid4(),
        conversation_id=conversation.id,
        capability_id="medication.enroll",
        fields={"medication_name": "DEMO-kept-draft"},
        updated_at=workflow.clock.now(),
    )
    tasks = MemoryWorkflowRepository(workflow.clock, state=state)
    tasks.create(task)
    port = importlib.import_module("app.infrastructure.workflow_message_repos").MemoryConversationPersistence(
        state=state,
        sessions=sessions,
        threads=threads,
        history=MemoryConversationHistory(),
        preferences=workflow.container.preferences,
    )
    port.execute(owner, contract("ClearConversationHistory", confirmed=True))
    assert sessions.get(owner, current.id).conversation_id is None
    saved = tasks.get(owner, task.id)
    assert saved.conversation_id is None and saved.fields == task.fields and saved.revision == task.revision + 1


def test_new_typed_session_cannot_reuse_another_owners_id():
    from app.domain.errors import ValidationError as DomainValidationError

    store = InMemoryStore()
    sessions = InMemoryAgentSessionRepository(store)
    original = session(uuid4())
    sessions.add(original)
    with pytest.raises(DomainValidationError):
        sessions.add(original.model_copy(update={"patient_id": uuid4()}))


@pytest.mark.parametrize("value", [1, "true", False])
def test_history_clear_requires_actual_explicit_boolean(value):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        contract("ClearConversationHistory", confirmed=value)


def test_content_command_rejects_naive_session_times():
    from pydantic import ValidationError

    original = session(uuid4())
    with pytest.raises(ValidationError):
        contract("CreateSession", session=original.model_copy(update={"updated_at": datetime(2026, 10, 28)}))
