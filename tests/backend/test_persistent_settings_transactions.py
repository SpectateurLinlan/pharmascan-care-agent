"""DEMO_ONLY native settings and workflow receipts share one transaction."""

import importlib
import json
from uuid import UUID, uuid4, uuid5

import pytest
from app.contracts.assistant_workflows import BusinessRef
from app.contracts.caregivers import CaregiverCreate
from app.contracts.patient_feedback import FeedbackInput
from app.contracts.preferences import PreferenceUpdate
from app.contracts.settings_workflow import PreferenceSnapshot
from app.contracts.workflow_persistence import WorkflowWriteBinding
from app.domain.errors import StaleVersionError

from .test_workflow_contacts import details
from .test_workflow_preferences import previous


def api(name):
    return getattr(importlib.import_module("app.contracts.workflow_settings_writes"), name)


def harness(h):
    cls = importlib.import_module("app.infrastructure.workflow_settings_writes").MemorySettingsWorkflowWrites
    w = h.container.assistant_workflows
    return cls(
        state=w._repository._state,
        store=h.container.store,
        clock=h.clock,
        tasks=w._repository,
        controls=w._controls,
        adapters=w._adapters,
        preferences=h.container.preferences,
        preference_storage=h.container.preferences._repository,
        contacts=h.container.caregivers,
        contact_storage=h.container.caregivers._repository,
        feedback=h.container.feedback,
        feedback_storage=h.container.feedback._repository,
    )


def binding(h, port, view):
    ref = BusinessRef.model_validate(view["result_ref"])
    return WorkflowWriteBinding(
        task_id=UUID(view["task_id"]),
        task_revision=view["revision"],
        capability_id=view["capability_id"],
        action_key=uuid5(ref.id, "settings-patient-confirmation"),
        prepared_ref=ref,
        expected_domain_revision=port.revision(h.owner_ids["A"]),
    )


def prepared(h, port, capability, values):
    view = h.start(capability, values)
    action = uuid4()
    command = api("PrepareSettingsReview")(
        binding=WorkflowWriteBinding(
            task_id=UUID(view["task_id"]),
            task_revision=view["revision"],
            capability_id=capability,
            action_key=action,
            prepared_ref=BusinessRef(kind="settings_review", id=action, version=1),
            expected_domain_revision=port.revision(h.owner_ids["A"]),
        )
    )
    result = port.prepare(h.owner_ids["A"], command)
    assert result.result is None and result.receipt.outcome == "prepared"
    return h.view(view["task_id"])


def preference_command(h, port, view, changes):
    return api("SavePreferences")(
        binding=binding(h, port, view),
        previous=PreferenceSnapshot.model_validate(view["input_fields"]["previous"]),
        values=PreferenceUpdate(**changes),
        confirmed=True,
    )


def test_settings_save_has_actual_readback_and_immutable_receipt(workflow):
    h, owner = workflow, workflow.owner_ids["A"]
    port = harness(h)
    view = prepared(h, port, "preference.text", {"text_scale_percent": 130, "previous": previous(h)})
    cmd = preference_command(h, port, view, {"text_scale_percent": 130})
    result = port.apply(owner, cmd)
    assert result.result == h.container.preferences.get(owner)
    assert result.result.text_scale_percent == 130 and result.result.text_size == "large"
    assert result.receipt.business_ref == BusinessRef(kind="preference", id=owner)
    assert port.apply(owner, cmd) == result
    h.container.preferences.save(owner, PreferenceUpdate(text_scale_percent=100))
    with pytest.raises(StaleVersionError):
        port.apply(owner, cmd)
    assert port.lookup(owner, cmd.binding.action_key) == result.receipt


def test_stale_settings_or_contact_is_rejected(workflow):
    h, owner = workflow, workflow.owner_ids["A"]
    port = harness(h)
    view = prepared(h, port, "preference.language", {"preferred_language": "zh", "previous": previous(h)})
    cmd = preference_command(h, port, view, {"preferred_language": "zh"})
    h.container.preferences.save(owner, PreferenceUpdate(display_name="DEMO changed independently"))
    with pytest.raises(StaleVersionError):
        port.apply(owner, cmd)
    assert h.container.preferences.get(owner).preferred_language == "en"
    assert port.lookup(owner, cmd.binding.action_key) is None


def test_contact_without_consent_has_no_write(workflow):
    h, owner = workflow, workflow.owner_ids["A"]
    port = harness(h)
    view = prepared(h, port, "caregiver.add", details())
    cmd = api("CreateContact")(
        binding=binding(h, port, view),
        values=CaregiverCreate(id=UUID(view["result_ref"]["id"]), **details()),
        confirmed=True,
    )
    with pytest.raises(ValueError):
        port.apply(owner, cmd.model_copy(update={"values": cmd.values.model_copy(update={"storage_consent": False})}))
    assert not h.container.caregivers.list(owner)
    result = port.apply(owner, cmd)
    assert result.result.verification_status == "pending"
    assert not result.result.notifications_enabled and not result.result.sharing_enabled


def test_feedback_body_is_absent_from_runtime_metadata(workflow):
    h, owner = workflow, workflow.owner_ids["A"]
    port = harness(h)
    view = prepared(h, port, "feedback.submit", {"category": "issue", "message": "DEMO-feedback-body"})
    cmd = api("SubmitFeedback")(
        binding=binding(h, port, view),
        values=FeedbackInput(id=UUID(view["result_ref"]["id"]), category="issue", message="DEMO-feedback-body"),
        confirmed=True,
    )
    result = port.apply(owner, cmd)
    assert result.result == h.container.feedback.get(owner, cmd.values.id)
    state = h.container.assistant_workflows._repository._state
    runtime = json.dumps(
        {
            "commands": list(state.settings_commands.values()),
            "preparations": list(state.settings_preparations.values()),
            "receipts": [x.model_dump(mode="json") for x in state.business_receipts.values()],
        },
        default=str,
    )
    assert "DEMO-feedback-body" not in runtime
    assert port.apply(owner, cmd) == result


def test_settings_task_failure_restores_native_preference_and_receipt(workflow, monkeypatch):
    h, owner = workflow, workflow.owner_ids["A"]
    port = harness(h)
    view = prepared(h, port, "profile.edit", {"display_name": "DEMO proposal", "previous": previous(h)})
    cmd = preference_command(h, port, view, {"display_name": "DEMO proposal"})
    old = h.container.preferences.get(owner)

    def failed(*_args, **_kwargs):
        assert h.container.preferences.get(owner).display_name == "DEMO proposal"
        raise StaleVersionError("DEMO task CAS failed after native profile publication")

    monkeypatch.setattr(port._tasks, "cas", failed)
    with pytest.raises(StaleVersionError):
        port.apply(owner, cmd)
    assert h.container.preferences.get(owner) == old
    assert port.lookup(owner, cmd.binding.action_key) is None


def test_disabling_history_fences_same_turn_append(workflow):
    from app.contracts.conversation_threads import ConversationMessage, ConversationSummary
    from app.contracts.workflow_messages import AppendConversationTurn, CreateConversation, CreateSession
    from app.infrastructure.conversation_history import MemoryConversationHistory
    from app.infrastructure.conversation_threads import MemoryConversationThreads
    from app.infrastructure.memory_repos import InMemoryAgentSessionRepository
    from app.infrastructure.workflow_message_repos import MemoryConversationPersistence

    from .test_workflow_message_transactions import session

    h, owner = workflow, workflow.owner_ids["A"]
    h.container.preferences.save(owner, PreferenceUpdate(conversation_history_enabled=True))
    state = h.container.assistant_workflows._repository._state
    threads, history = MemoryConversationThreads(), MemoryConversationHistory()
    messages = MemoryConversationPersistence(
        state=state,
        sessions=InMemoryAgentSessionRepository(h.container.store),
        threads=threads,
        history=history,
        preferences=h.container.preferences,
        clock=h.clock,
    )
    conversation = ConversationSummary(
        id=uuid4(), title="DEMO existing conversation", created_at=h.clock.now(), updated_at=h.clock.now()
    )
    messages.execute(owner, CreateConversation(conversation=conversation))
    active = session(owner).model_copy(update={"conversation_id": conversation.id})
    messages.execute(owner, CreateSession(session=active))
    append = AppendConversationTurn(
        session_id=active.id,
        message=ConversationMessage(
            id=uuid4(),
            conversation_id=conversation.id,
            user_text="DEMO same turn",
            assistant_text="DEMO reply",
            created_at=h.clock.now(),
        ),
    )
    port = harness(h)
    view = prepared(h, port, "preference.privacy", {"conversation_history_enabled": False, "previous": previous(h)})
    port.apply(owner, preference_command(h, port, view, {"conversation_history_enabled": False}))
    with pytest.raises(StaleVersionError):
        messages.execute(owner, append)
    assert threads.messages(owner, conversation.id, None, 20) == []


def test_timezone_change_preserves_old_utc_events(workflow):
    from .test_persistent_record_transactions import prn_command

    h, owner = workflow, workflow.owner_ids["A"]
    reports, report, _summary = prn_command(h)
    event = reports.apply(owner, report).result.event
    before = h.snapshot()["dose_events"]
    assert before, "UTC preservation must exercise an actual independently confirmed self-report"
    port = harness(h)
    view = prepared(h, port, "preference.timezone", {"timezone": "America/New_York", "previous": previous(h)})
    result = port.apply(owner, preference_command(h, port, view, {"timezone": "America/New_York"}))
    assert result.result.timezone == "America/New_York"
    assert h.snapshot()["dose_events"] == before
    assert any(row["event_time"] == event.event_time.isoformat().replace("+00:00", "Z") for row in before)


def test_settings_run_deadline_rechecks_after_native_save(workflow, monkeypatch):
    from app.contracts.workflow_persistence import RunWriteBinding
    from app.infrastructure.durable_agent_runs import MemoryDurableRunControl

    from .test_durable_agent_runs import claimed

    h, owner = workflow, workflow.owner_ids["A"]
    port = harness(h)
    view = prepared(h, port, "profile.edit", {"display_name": "DEMO late write", "previous": previous(h)})
    state = h.container.assistant_workflows._repository._state
    run = claimed(MemoryDurableRunControl(clock=h.clock, state=state), owner)
    cmd = preference_command(h, port, view, {"display_name": "DEMO late write"})
    cmd = cmd.model_copy(
        update={
            "binding": cmd.binding.model_copy(
                update={"run_binding": RunWriteBinding(run_id=run.run_id, epoch=run.epoch)}
            )
        }
    )
    old, save = h.container.preferences.get(owner), h.container.preferences.save

    def slow(*args, **kwargs):
        result = save(*args, **kwargs)
        h.clock.advance(seconds=46)
        return result

    monkeypatch.setattr(h.container.preferences, "save", slow)
    with pytest.raises(StaleVersionError):
        port.apply(owner, cmd)
    assert h.container.preferences.get(owner) == old and port.lookup(owner, cmd.binding.action_key) is None


def test_contact_edit_stale_and_delete_recovery_preserve_receipt(workflow):
    from app.contracts.caregivers import CaregiverDetails

    h, owner = workflow, workflow.owner_ids["A"]
    port = harness(h)
    contact = h.container.caregivers.create(owner, CaregiverCreate(id=uuid4(), **details()))

    def change(capability):
        current = h.container.caregivers.get(owner, contact.id)
        before = current.model_dump(mode="json", include=set(CaregiverDetails.model_fields))
        fields = {
            "contact_id": str(contact.id),
            "previous": before,
            "previous_updated_at": current.updated_at.isoformat(),
        }
        if capability == "caregiver.edit":
            fields |= before | {"name": "DEMO independently reviewed edit"}
        view = prepared(h, port, capability, fields)
        args = dict(
            binding=binding(h, port, view),
            contact_id=contact.id,
            previous=CaregiverDetails.model_validate(before),
            previous_updated_at=current.updated_at,
            confirmed=True,
        )
        return (
            api("EditContact")(**args, values=CaregiverDetails(**(before | {"name": fields["name"]})))
            if capability.endswith("edit")
            else api("DeleteContact")(**args)
        )

    edit = change("caregiver.edit")
    h.clock.advance(seconds=1)
    h.container.caregivers.update(
        owner, contact.id, CaregiverDetails(**(details() | {"name": "DEMO current other edit"}))
    )
    with pytest.raises(StaleVersionError):
        port.apply(owner, edit)
    delete = change("caregiver.delete")
    result = port.apply(owner, delete)
    assert result.result is None and h.container.caregivers.get(owner, contact.id) is None
    assert port.apply(owner, delete) == result
    h.container.caregivers.create(owner, CaregiverCreate(id=contact.id, **details()))
    with pytest.raises(StaleVersionError):
        port.apply(owner, delete)
    assert port.lookup(owner, delete.binding.action_key) == result.receipt


def test_unbound_privacy_change_cannot_commit_inside_an_inflight_history_append(workflow, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from app.contracts.conversation_threads import ConversationMessage, ConversationSummary
    from app.contracts.workflow_messages import (
        AppendConversationTurn,
        ClaimConversationTurn,
        CreateConversation,
        CreateSession,
    )
    from app.infrastructure.conversation_history import MemoryConversationHistory
    from app.infrastructure.conversation_threads import MemoryConversationThreads
    from app.infrastructure.memory_repos import InMemoryAgentSessionRepository
    from app.infrastructure.workflow_message_repos import MemoryConversationPersistence

    from .test_workflow_message_transactions import session

    h, owner = workflow, workflow.owner_ids["A"]
    h.container.preferences.save(owner, PreferenceUpdate(conversation_history_enabled=True))
    threads = MemoryConversationThreads()
    messages = MemoryConversationPersistence(
        state=h.container.assistant_workflows._repository._state,
        sessions=InMemoryAgentSessionRepository(h.container.store),
        threads=threads,
        history=MemoryConversationHistory(),
        preferences=h.container.preferences,
        clock=h.clock,
    )
    conversation = ConversationSummary(
        id=uuid4(), title="DEMO race", created_at=h.clock.now(), updated_at=h.clock.now()
    )
    messages.execute(owner, CreateConversation(conversation=conversation))
    active = session(owner).model_copy(update={"conversation_id": conversation.id})
    messages.execute(owner, CreateSession(session=active))
    command = AppendConversationTurn(
        session_id=active.id,
        message=ConversationMessage(
            id=uuid4(),
            conversation_id=conversation.id,
            user_text="DEMO inflight",
            assistant_text="DEMO reply",
            created_at=h.clock.now(),
        ),
    )
    messages.execute(
        owner, ClaimConversationTurn(conversation_id=conversation.id, turn_id=command.message.id, digest="a" * 64)
    )
    entered, release, writing, saved = Event(), Event(), Event(), Event()
    append = threads.append

    def slow_append(*args, **kwargs):
        entered.set()
        assert release.wait(3), "DEMO test controller failed to release the append"
        return append(*args, **kwargs)

    def disable():
        writing.set()
        h.container.preferences.save(owner, PreferenceUpdate(conversation_history_enabled=False))
        saved.set()

    monkeypatch.setattr(threads, "append", slow_append)
    with ThreadPoolExecutor(max_workers=2) as workers:
        pending = workers.submit(messages.execute, owner, command)
        assert entered.wait(3)
        change = workers.submit(disable)
        try:
            assert writing.wait(3)
            assert not saved.wait(0.3), (
                "Privacy change committed after append authorization but before content publication"
            )
        finally:
            release.set()
        pending.result(timeout=3)
        change.result(timeout=3)
    assert saved.is_set() and not h.container.preferences.get(owner).conversation_history_enabled
    with pytest.raises(StaleVersionError):
        messages.execute(owner, command)


@pytest.mark.parametrize("recovery", [False, True])
def test_remote_settings_selects_fixed_write_or_owned_readback(workflow, recovery):
    import httpx
    from app.domain.errors import AuthenticationRequiredError, ProviderUnavailableError
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.workflow_repos import SupabaseWorkflowMutations

    h, owner = workflow, workflow.owner_ids["A"]
    local = harness(h)
    view = prepared(h, local, "preference.text", {"text_scale_percent": 130, "previous": previous(h)})
    cmd = preference_command(h, local, view, {"text_scale_percent": 130})
    result = local.apply(owner, cmd)
    calls, wrong = [], [False]

    def respond(request):
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json=[result.receipt.model_dump(mode="json")] if recovery else [])
        body = json.loads(request.content)["p_command"]
        assert body["values"] == {"text_scale_percent": 130}
        value = result.model_dump(mode="json")
        if wrong[0]:
            value["result"]["patient_id"] = str(h.owner_ids["B"])
        return httpx.Response(200, json={"result": value, "replayed": recovery})

    data = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=owner,
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    cls = importlib.import_module("app.infrastructure.workflow_settings_writes").SupabaseSettingsWorkflowWrites
    remote = cls(data=data, receipts=SupabaseWorkflowMutations(data))
    assert remote.apply(owner, cmd) == result
    assert calls == [
        ("GET", "/rest/v1/assistant_business_receipts"),
        ("POST", "/rest/v1/rpc/assistant_settings_read" if recovery else "/rest/v1/rpc/assistant_settings_write"),
    ]
    calls.clear()
    with pytest.raises(AuthenticationRequiredError):
        remote.apply(h.owner_ids["B"], cmd)
    assert calls == []
    wrong[0] = True
    with pytest.raises(ProviderUnavailableError):
        remote.apply(owner, cmd)


def test_settings_sql_candidate_inventory_is_bounded_and_preserving():
    """Source packaging only; no claim about executed SQL, privileges or races."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "supabase/review/assistant_workflows"
    up, down = root / "settings.up.sql", root / "settings.down.sql"
    assert up.is_file() and down.is_file(), "Missing settings SQL review pair"
    source = up.read_text(encoding="utf-8")
    for name in (
        "assistant_settings_prepare",
        "assistant_settings_write",
        "assistant_settings_read",
        "assistant_settings_revision",
        "assistant_settings_commands",
        "assistant_run_assert_current",
        "caregiver_contacts",
        "patient_feedback",
        "assistant_business_receipts",
    ):
        assert name in source
    assert "TO assistant_evidence_login" not in source
    assert "DELETE FROM public.patient_feedback" not in source
    assert "assistant_settings_commands" in down.read_text(encoding="utf-8")


def test_settings_preparation_cannot_overwrite_another_action(workflow):
    from app.contracts.assistant_workflows import ActionReceipt
    from app.domain.errors import DuplicateEventError

    h, owner = workflow, workflow.owner_ids["A"]
    port = harness(h)
    view = h.start("preference.text", {"text_scale_percent": 130, "previous": previous(h)})
    action = uuid4()
    state = h.container.assistant_workflows._repository._state
    old = ActionReceipt(
        owner=owner,
        task_id=UUID(view["task_id"]),
        capability_id="preference.text",
        action_key=action,
        binding_revision=view["revision"],
        state="succeeded",
        safe_reason="DEMO prior action",
        updated_at=h.clock.now(),
    )
    state.actions[owner, action] = old
    command = api("PrepareSettingsReview")(
        binding=WorkflowWriteBinding(
            task_id=UUID(view["task_id"]),
            task_revision=view["revision"],
            capability_id="preference.text",
            action_key=action,
            prepared_ref=BusinessRef(kind="settings_review", id=action, version=1),
            expected_domain_revision=port.revision(owner),
        )
    )
    with pytest.raises(DuplicateEventError):
        port.prepare(owner, command)
    assert state.actions[owner, action] == old
    assert port.lookup(owner, action) is None


@pytest.mark.parametrize("kind", ["contact", "feedback"])
def test_settings_task_failure_restores_native_contact_or_feedback(workflow, monkeypatch, kind):
    h, owner = workflow, workflow.owner_ids["A"]
    port = harness(h)
    values = details() if kind == "contact" else {"category": "issue", "message": "DEMO retained only on success"}
    view = prepared(h, port, "caregiver.add" if kind == "contact" else "feedback.submit", values)
    target = UUID(view["result_ref"]["id"])
    command = api("CreateContact" if kind == "contact" else "SubmitFeedback")(
        binding=binding(h, port, view),
        values=(CaregiverCreate if kind == "contact" else FeedbackInput)(id=target, **values),
        confirmed=True,
    )
    service = h.container.caregivers if kind == "contact" else h.container.feedback

    def failed(*_args, **_kwargs):
        assert service.get(owner, target) is not None
        raise StaleVersionError("DEMO task CAS failed after actual native publication")

    monkeypatch.setattr(port._tasks, "cas", failed)
    with pytest.raises(StaleVersionError):
        port.apply(owner, command)
    assert service.get(owner, target) is None
    assert port.lookup(owner, command.binding.action_key) is None
