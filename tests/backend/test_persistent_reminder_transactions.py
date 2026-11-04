"""DEMO_ONLY durable reminder writes do not acquire delivery authority."""

import importlib
from datetime import timedelta
from uuid import UUID, uuid4, uuid5

import pytest
from app.contracts.assistant_workflows import BusinessRef
from app.contracts.preferences import PreferenceUpdate
from app.contracts.reminder_workflow import SnoozeFields
from app.contracts.workflow_persistence import WorkflowWriteBinding
from app.domain.errors import StaleVersionError, ValidationError

from .test_workflow_reminder_writes import fields


def api(name):
    return getattr(importlib.import_module("app.contracts.workflow_reminder_writes"), name)


def harness(h):
    cls = importlib.import_module("app.infrastructure.workflow_reminder_writes").MemoryReminderWorkflowWrites
    w = h.container.assistant_workflows
    return cls(
        state=w._repository._state,
        store=h.container.store,
        clock=h.clock,
        tasks=w._repository,
        controls=w._controls,
        adapter=w._adapters["reminder.snooze"],
        reminders=h.container.reminders,
        reminder_storage=h.container.reminders._repository,
        preferences=h.container.preferences,
        preference_storage=h.container.preferences._repository,
    )


def prepared(h, port, capability="reminder.snooze"):
    view = h.start(capability, fields(h, capability))
    action = uuid4()
    port.prepare(
        h.owner_ids["A"],
        api("PrepareReminderReview")(
            binding=WorkflowWriteBinding(
                task_id=UUID(view["task_id"]),
                task_revision=view["revision"],
                capability_id=capability,
                action_key=action,
                prepared_ref=BusinessRef(kind="reminder_review", id=action, version=1),
                expected_domain_revision=port.revision(h.owner_ids["A"]),
            )
        ),
    )
    return h.view(view["task_id"])


def command(h, port, view):
    ref, values = BusinessRef.model_validate(view["result_ref"]), view["input_fields"]
    binding = WorkflowWriteBinding(
        task_id=UUID(view["task_id"]),
        task_revision=view["revision"],
        capability_id=view["capability_id"],
        action_key=uuid5(ref.id, "reminder-patient-confirmation"),
        prepared_ref=ref,
        expected_domain_revision=port.revision(h.owner_ids["A"]),
    )
    if view["capability_id"] == "reminder.snooze":
        return api("SnoozeReminder")(binding=binding, values=SnoozeFields.model_validate(values), confirmed=True)
    return api("SaveReminderSettings")(
        binding=binding,
        values=PreferenceUpdate(
            reminders_enabled=values["reminders_enabled"], reminder_lead_minutes=values["reminder_lead_minutes"]
        ),
        previous_enabled=values["previous_enabled"],
        previous_lead_minutes=values["previous_lead_minutes"],
        previous_timezone=values["previous_timezone"],
        confirmed=True,
    )


@pytest.mark.parametrize("capability", ["reminder.snooze", "reminder.settings"])
def test_duplicate_snooze_or_settings_has_one_actual_change(workflow, capability):
    h, owner = workflow, workflow.owner_ids["A"]
    port = harness(h)
    view = prepared(h, port, capability)
    cmd = command(h, port, view)
    before = h.snapshot()
    saved = port.apply(owner, cmd)
    revision = port.revision(owner)
    h.clock.advance(seconds=1)
    assert port.apply(owner, cmd) == saved and port.revision(owner) == revision
    after = h.snapshot()
    assert after["dose_events"] == before["dose_events"]
    if capability == "reminder.snooze":
        assert saved.result.remind_at == h.clock.now() - timedelta(seconds=1) + timedelta(minutes=15)
        assert saved.receipt.business_ref == BusinessRef(kind="dose_occurrence", id=cmd.values.occurrence_id)
    else:
        assert not saved.result.reminders_enabled and saved.result.reminder_lead_minutes == 30


def test_changed_timezone_requires_new_review(workflow):
    h, owner = workflow, workflow.owner_ids["A"]
    port = harness(h)
    cmd = command(h, port, prepared(h, port))
    h.container.preferences.save(owner, PreferenceUpdate(timezone="America/New_York"))
    with pytest.raises(StaleVersionError):
        port.apply(owner, cmd)
    assert not h.container.store.reminders and port.lookup(owner, cmd.binding.action_key) is None


def test_snooze_rejects_closed_or_stale_occurrence(workflow):
    from app.contracts.enums import OccurrenceStatus

    h, owner = workflow, workflow.owner_ids["A"]
    port = harness(h)
    cmd = command(h, port, prepared(h, port))
    repo = h.container.reminders._occurrences
    occurrence = repo.get(owner, cmd.values.occurrence_id)
    repo.update(occurrence.model_copy(update={"status": OccurrenceStatus.CLOSED}))
    with pytest.raises((StaleVersionError, ValidationError)):
        port.apply(owner, cmd)
    assert not h.container.store.reminders and port.lookup(owner, cmd.binding.action_key) is None


@pytest.mark.parametrize("capability", ["reminder.snooze", "reminder.settings"])
def test_failed_task_publication_restores_actual_reminder_or_preference(workflow, monkeypatch, capability):
    h, owner = workflow, workflow.owner_ids["A"]
    port = harness(h)
    cmd = command(h, port, prepared(h, port, capability))
    old = h.container.preferences.get(owner)
    revision = port.revision(owner)

    def failed(*_args, **_kwargs):
        if capability == "reminder.snooze":
            assert h.container.reminders.get_saved(owner, cmd.values.occurrence_id) is not None
        else:
            assert not h.container.preferences.get(owner).reminders_enabled
        raise StaleVersionError("DEMO task CAS failed after actual native reminder publication")

    monkeypatch.setattr(port._tasks, "cas", failed)
    with pytest.raises(StaleVersionError):
        port.apply(owner, cmd)
    assert not h.container.store.reminders and h.container.preferences.get(owner) == old
    assert port.revision(owner) == revision and port.lookup(owner, cmd.binding.action_key) is None


def test_reminder_run_expiry_rolls_back_actual_snooze(workflow, monkeypatch):
    from app.contracts.workflow_persistence import RunWriteBinding
    from app.infrastructure.durable_agent_runs import MemoryDurableRunControl

    from .test_durable_agent_runs import claimed

    h, owner = workflow, workflow.owner_ids["A"]
    port = harness(h)
    cmd = command(h, port, prepared(h, port))
    state = h.container.assistant_workflows._repository._state
    run = claimed(MemoryDurableRunControl(clock=h.clock, state=state), owner)
    cmd = cmd.model_copy(
        update={
            "binding": cmd.binding.model_copy(
                update={"run_binding": RunWriteBinding(run_id=run.run_id, epoch=run.epoch)}
            )
        }
    )
    snooze = h.container.reminders.snooze

    def slow(*args, **kwargs):
        result = snooze(*args, **kwargs)
        h.clock.advance(seconds=46)
        return result

    monkeypatch.setattr(h.container.reminders, "snooze", slow)
    with pytest.raises(StaleVersionError):
        port.apply(owner, cmd)
    assert not h.container.store.reminders and port.lookup(owner, cmd.binding.action_key) is None


@pytest.mark.parametrize("recovery", [False, True])
@pytest.mark.parametrize("post_write_delay", [0, 40])
def test_remote_reminder_uses_owned_fixed_write_or_read_only_recovery(
    workflow, monkeypatch, recovery, post_write_delay
):
    import json

    import httpx
    from app.domain.errors import AuthenticationRequiredError, ProviderUnavailableError
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.workflow_repos import SupabaseWorkflowMutations

    h, owner = workflow, workflow.owner_ids["A"]
    local = harness(h)
    cmd = command(h, local, prepared(h, local))
    snooze = h.container.reminders.snooze

    def delayed_result(*args, **kwargs):
        row = snooze(*args, **kwargs)
        h.clock.advance(seconds=post_write_delay)
        return row

    monkeypatch.setattr(h.container.reminders, "snooze", delayed_result)
    result = local.apply(owner, cmd)
    calls, bad = [], [False]

    def respond(request):
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json=[result.receipt.model_dump(mode="json")] if recovery else [])
        body = json.loads(request.content)["p_command"]
        assert body == cmd.model_dump(mode="json")
        value = result.model_dump(mode="json")
        if bad[0]:
            value["result"]["patient_id"] = str(h.owner_ids["B"])
        return httpx.Response(200, json={"result": value, "replayed": recovery})

    data = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=owner,
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    cls = importlib.import_module("app.infrastructure.workflow_reminder_writes").SupabaseReminderWorkflowWrites
    remote = cls(data=data, receipts=SupabaseWorkflowMutations(data))
    assert remote.apply(owner, cmd) == result
    assert calls == [
        ("GET", "/rest/v1/assistant_business_receipts"),
        ("POST", "/rest/v1/rpc/assistant_reminder_read" if recovery else "/rest/v1/rpc/assistant_reminder_write"),
    ]
    calls.clear()
    with pytest.raises(AuthenticationRequiredError):
        remote.apply(h.owner_ids["B"], cmd)
    assert calls == []
    bad[0] = True
    with pytest.raises(ProviderUnavailableError):
        remote.apply(owner, cmd)


def test_reminder_sql_candidate_inventory_keeps_delivery_outside_database_commands():
    """Candidate packaging only; actual SQL/DST/role/concurrency gates are separate."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "supabase/review/assistant_workflows"
    up, down = root / "reminders.up.sql", root / "reminders.down.sql"
    assert up.is_file() and down.is_file(), "Missing reminder SQL review pair"
    source = up.read_text(encoding="utf-8")
    for name in (
        "assistant_reminder_write",
        "assistant_reminder_prepare",
        "assistant_reminder_read",
        "assistant_reminder_revision",
        "assistant_reminder_deadline",
        "assistant_reminder_commands",
        "assistant_run_assert_current",
    ):
        assert name in source
    assert "TO assistant_evidence_login" not in source
    assert "INSERT INTO public.push_subscriptions" not in source
    assert "assistant_reminder_commands" in down.read_text(encoding="utf-8")
