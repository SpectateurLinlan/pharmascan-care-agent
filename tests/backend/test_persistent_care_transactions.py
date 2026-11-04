"""DEMO_ONLY independent care confirmation shares the native local transaction."""

import importlib
from uuid import UUID, uuid4, uuid5

import pytest
from app.contracts.assistant_workflows import BusinessRef
from app.contracts.long_term import StockInput, TaskUpdate
from app.contracts.observations import ObservationInput
from app.contracts.workflow_persistence import WorkflowWriteBinding
from app.domain.errors import StaleVersionError, ValidationError

from .test_workflow_care import fields
from .test_workflow_medication_management import active_plan


def remote_port(h, respond):
    import httpx
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.workflow_repos import SupabaseWorkflowMutations

    cls = importlib.import_module("app.infrastructure.workflow_care_writes").SupabaseCareWorkflowWrites
    data = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=h.owner_ids["A"],
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    return cls(data=data, receipts=SupabaseWorkflowMutations(data))


def api(name):
    return getattr(importlib.import_module("app.contracts.workflow_care_writes"), name)


def harness(h):
    cls = importlib.import_module("app.infrastructure.workflow_care_writes").MemoryCareWorkflowWrites
    workflows = h.container.assistant_workflows
    return cls(
        state=workflows._repository._state,
        store=h.container.store,
        clock=h.clock,
        tasks=workflows._repository,
        controls=workflows._controls,
        observations=h.container.observations,
        observation_storage=h.container.observations._repository,
        care=h.container.long_term,
        care_storage=h.container.long_term._repo,
        adapter=workflows._adapters["observation.add"],
        preferences=h.container.preferences,
    )


def binding(h, port, view):
    ref = BusinessRef.model_validate(view["result_ref"])
    return WorkflowWriteBinding(
        task_id=UUID(view["task_id"]),
        task_revision=view["revision"],
        capability_id=view["capability_id"],
        action_key=uuid5(ref.id, "care-patient-confirmation"),
        prepared_ref=ref,
        expected_domain_revision=port.revision(h.owner_ids["A"]),
    )


def prepared(h, capability, values):
    view = h.start(capability, values)
    port = harness(h)
    action = uuid4()
    command = api("PrepareCareReview")(
        binding=WorkflowWriteBinding(
            task_id=UUID(view["task_id"]),
            task_revision=view["revision"],
            capability_id=capability,
            action_key=action,
            prepared_ref=BusinessRef(kind="care_review", id=action, version=1),
            expected_domain_revision=port.revision(h.owner_ids["A"]),
        )
    )
    before = h.snapshot()
    receipt = port.prepare(h.owner_ids["A"], command)
    assert receipt.result is None and receipt.receipt.outcome == "prepared"
    assert h.snapshot()["dose_events"] == before["dose_events"]
    return h.view(view["task_id"])


def save_observation(h, view, port):
    payload = ObservationInput.model_validate({**view["visible_fields"]["care_review"]["payload"], "confirmed": True})
    return api("SaveObservation")(binding=binding(h, port, view), values=payload, confirmed=True)


def test_observation_receipt_survives_later_edit_or_delete(workflow):
    h, owner = workflow, workflow.owner_ids["A"]
    view = prepared(h, "observation.add", fields(h, "observation.add"))
    port = harness(h)
    first = save_observation(h, view, port)
    saved = port.apply(owner, first)
    original_receipt = saved.receipt
    h.clock.advance(seconds=1)
    updated = prepared(
        h,
        "observation.edit",
        {
            "observation_id": str(saved.result.id),
            "description": "DEMO explicitly corrected note",
            "occurred_at": h.clock.now().isoformat(),
        },
    )
    update = save_observation(h, updated, port)
    actual = port.apply(owner, update)
    assert (
        actual.result.created_at == saved.result.created_at
        and actual.result.description == "DEMO explicitly corrected note"
    )
    deletion = prepared(h, "observation.delete", {"observation_id": str(saved.result.id)})
    removed = port.apply(
        owner,
        api("DeleteObservation")(binding=binding(h, port, deletion), observation_id=saved.result.id, confirmed=True),
    )
    assert removed.result is None and h.container.observations.get(owner, saved.result.id) is None
    assert port.lookup(owner, first.binding.action_key) == original_receipt
    with pytest.raises(StaleVersionError):
        port.apply(owner, first)


def test_stock_count_is_unit_checked_and_idempotent(workflow):
    h, owner = workflow, workflow.owner_ids["A"]
    medicine = active_plan(h)
    view = prepared(h, "inventory.count", fields(h, "inventory.count", medicine))
    port = harness(h)
    values = StockInput.model_validate({**view["visible_fields"]["care_review"]["payload"], "confirmed": True})
    command = api("RecordStock")(
        binding=binding(h, port, view), medication_id=UUID(medicine["medication_id"]), values=values, confirmed=True
    )
    saved = port.apply(owner, command)
    assert saved.result.stock_after == 12 and saved.result.source == "patient_confirmed"
    assert port.apply(owner, command).receipt == saved.receipt
    status = h.container.long_term.inventory(owner, UUID(medicine["medication_id"]), "Asia/Singapore")
    assert len(status.transactions) == 1 and status.last_confirmed_stock == 12
    invalid = prepared(
        h,
        "inventory.count",
        {**fields(h, "inventory.count", medicine), "unit": "capsule", "kind": "refill", "quantity": 2},
    )
    wrong = StockInput.model_validate({**invalid["visible_fields"]["care_review"]["payload"], "confirmed": True})
    with pytest.raises(ValidationError):
        port.apply(
            owner,
            api("RecordStock")(
                binding=binding(h, port, invalid),
                medication_id=UUID(medicine["medication_id"]),
                values=wrong,
                confirmed=True,
            ),
        )
    assert (
        len(h.container.long_term.inventory(owner, UUID(medicine["medication_id"]), "Asia/Singapore").transactions) == 1
    )


def test_followup_rejects_stale_plan_or_version(workflow):
    from datetime import timedelta

    h, owner = workflow, workflow.owner_ids["A"]
    old = h._request(
        "POST",
        "/api/me/care-tasks",
        json={
            "id": str(uuid4()),
            "category": "medication_review",
            "title": "DEMO followup",
            "due_at": (h.clock.now() + timedelta(days=2)).isoformat(),
            "confirmed": True,
        },
    )
    view = prepared(h, "followup.complete", fields(h, "followup.complete", task=old))
    port = harness(h)
    values = TaskUpdate.model_validate({**view["visible_fields"]["care_review"]["payload"], "confirmed": True})
    command = api("UpdateFollowup")(
        binding=binding(h, port, view), task_id=UUID(old["id"]), expected_version=1, values=values, confirmed=True
    )
    h.container.long_term.update_task(
        owner,
        UUID(old["id"]),
        TaskUpdate(id=uuid4(), expected_version=1, status="contacted", notes="DEMO independent update", confirmed=True),
    )
    with pytest.raises(StaleVersionError):
        port.apply(owner, command)
    assert h.container.long_term.tasks(owner)[0].status == "contacted"
    assert port.lookup(owner, command.binding.action_key) is None


def test_task_failure_rolls_back_observation_and_care_receipt(workflow, monkeypatch):
    h, owner = workflow, workflow.owner_ids["A"]
    view = prepared(h, "observation.add", fields(h, "observation.add"))
    port = harness(h)
    command = save_observation(h, view, port)
    before = h.snapshot()

    def fail(*args, **kwargs):
        raise StaleVersionError("DEMO changed care task")

    monkeypatch.setattr(h.container.assistant_workflows._repository, "cas", fail)
    with pytest.raises(StaleVersionError):
        port.apply(owner, command)
    assert h.snapshot() == before and h.container.observations.get(owner, command.values.id) is None
    assert port.lookup(owner, command.binding.action_key) is None


def test_declined_care_review_has_no_write_or_receipt(workflow):
    h, owner = workflow, workflow.owner_ids["A"]
    view = prepared(h, "observation.add", fields(h, "observation.add"))
    port = harness(h)
    command = save_observation(h, view, port)
    command = command.model_copy(update={"values": command.values.model_copy(update={"confirmed": False})})
    before = h.snapshot()
    with pytest.raises(ValidationError):
        port.apply(owner, command)
    assert h.snapshot() == before and port.lookup(owner, command.binding.action_key) is None


def test_followup_explicit_clear_preserves_unset_fields_and_original_history(workflow):
    from datetime import timedelta

    h, owner = workflow, workflow.owner_ids["A"]
    medicine = active_plan(h)
    old = h._request(
        "POST",
        "/api/me/care-tasks",
        json={
            "id": str(uuid4()),
            "category": "medication_review",
            "title": "DEMO linked followup",
            "due_at": (h.clock.now() + timedelta(days=2)).isoformat(),
            "medication_id": medicine["medication_id"],
            "regimen_id": medicine["regimen_id"],
            "notes": "DEMO original note",
            "reminder_minutes": 60,
            "confirmed": True,
        },
    )
    view = prepared(
        h, "followup.edit", {"task_id": old["id"], "expected_version": 1, "clear_plan": True, "disable_reminder": True}
    )
    port = harness(h)
    values = TaskUpdate.model_validate({**view["visible_fields"]["care_review"]["payload"], "confirmed": True})
    assert values.medication_id is None and "medication_id" in values.model_fields_set
    command = api("UpdateFollowup")(
        binding=binding(h, port, view), task_id=UUID(old["id"]), expected_version=1, values=values, confirmed=True
    )
    actual = port.apply(owner, command)
    assert (
        actual.result.medication_id is None
        and actual.result.regimen_id is None
        and actual.result.reminder_minutes is None
    )
    assert actual.result.title == old["title"] and actual.result.notes == old["notes"]
    assert actual.result.history[0].model_dump(mode="json") == old["history"][0]
    assert actual.result.version == 2 and port.apply(owner, command).receipt == actual.receipt


def test_stock_failure_also_rolls_back_automatic_refill_followup(workflow, monkeypatch):
    h, owner = workflow, workflow.owner_ids["A"]
    medicine = active_plan(h)
    view = prepared(h, "inventory.count", {**fields(h, "inventory.count", medicine), "quantity": 0})
    port = harness(h)
    values = StockInput.model_validate({**view["visible_fields"]["care_review"]["payload"], "confirmed": True})
    command = api("RecordStock")(
        binding=binding(h, port, view), medication_id=UUID(medicine["medication_id"]), values=values, confirmed=True
    )
    before_tasks = h.container.long_term.tasks(owner)
    seen = []

    def fail(*args, **kwargs):
        seen.extend(h.container.long_term.tasks(owner))
        assert any(row.source == "stock_estimate" for row in seen)
        raise StaleVersionError("DEMO fail after low-stock reconciliation")

    monkeypatch.setattr(h.container.assistant_workflows._repository, "cas", fail)
    with pytest.raises(StaleVersionError):
        port.apply(owner, command)
    assert h.container.long_term.tasks(owner) == before_tasks
    assert seen
    assert not h.container.long_term.inventory(owner, UUID(medicine["medication_id"]), "Asia/Singapore").transactions


def test_barrier_and_followup_keep_native_patient_reported_semantics(workflow):
    from app.contracts.long_term import BarrierInput, CareTaskInput

    h, owner = workflow, workflow.owner_ids["A"]
    barrier = prepared(
        h,
        "barrier.add",
        {
            **fields(h, "barrier.add"),
            "category": "side_effect_concern",
            "description": "DEMO patient describes a concern without verified causality",
            "chosen_action": "DEMO ask pharmacist",
        },
    )
    port = harness(h)
    values = BarrierInput.model_validate({**barrier["visible_fields"]["care_review"]["payload"], "confirmed": True})
    saved = port.apply(owner, api("RecordBarrier")(binding=binding(h, port, barrier), values=values, confirmed=True))
    assert saved.result.description == values.description and saved.result.source == "patient_reported"
    assert saved.result.chosen_action == "DEMO ask pharmacist" and saved.result.follow_up_task_id is None
    followup = prepared(h, "followup.add", fields(h, "followup.add"))
    task = CareTaskInput.model_validate({**followup["visible_fields"]["care_review"]["payload"], "confirmed": True})
    created = port.apply(owner, api("CreateFollowup")(binding=binding(h, port, followup), values=task, confirmed=True))
    assert (
        created.result.source == "patient_reported" and created.result.status == "open" and created.result.version == 1
    )
    assert len(created.result.history) == 1 and created.receipt.business_ref == BusinessRef(
        kind="care_task", id=task.id, version=1
    )


def test_pause_resume_requires_a_fresh_care_review_even_with_the_current_header(workflow):
    h, owner = workflow, workflow.owner_ids["A"]
    view = prepared(h, "observation.add", fields(h, "observation.add"))
    port = harness(h)
    old = save_observation(h, view, port)
    h.event(view["task_id"], "pause")
    current = h.event(view["task_id"], "resume")
    with pytest.raises(StaleVersionError):
        port.apply(
            owner,
            old.model_copy(
                update={
                    "binding": old.binding.model_copy(
                        update={"task_revision": current["revision"], "expected_domain_revision": port.revision(owner)}
                    )
                }
            ),
        )
    action = uuid4()
    port.prepare(
        owner,
        api("PrepareCareReview")(
            binding=WorkflowWriteBinding(
                task_id=UUID(view["task_id"]),
                task_revision=current["revision"],
                capability_id="observation.add",
                action_key=action,
                prepared_ref=BusinessRef(kind="care_review", id=action, version=1),
                expected_domain_revision=port.revision(owner),
            )
        ),
    )
    fresh = h.view(view["task_id"])
    result = port.apply(owner, save_observation(h, fresh, port))
    assert result.result.id == action and result.receipt.outcome == "applied"


def test_refreshed_domain_counter_cannot_adopt_an_old_native_snapshot(workflow):
    h, owner = workflow, workflow.owner_ids["A"]
    original = h._request(
        "PUT",
        "/api/me/health-observations",
        json={
            "id": str(uuid4()),
            "occurred_at": h.clock.now().isoformat(),
            "description": "DEMO old note",
            "confirmed": True,
        },
    )
    view = prepared(
        h,
        "observation.edit",
        {
            "observation_id": original["id"],
            "description": "DEMO reviewed replacement",
            "occurred_at": h.clock.now().isoformat(),
        },
    )
    port = harness(h)
    command = save_observation(h, view, port)
    h.container.observations.save(
        owner,
        ObservationInput(
            id=UUID(original["id"]),
            occurred_at=h.clock.now(),
            description="DEMO another independently confirmed edit",
            confirmed=True,
        ),
    )
    refreshed = command.model_copy(
        update={"binding": command.binding.model_copy(update={"expected_domain_revision": port.revision(owner)})}
    )
    with pytest.raises(StaleVersionError):
        port.apply(owner, refreshed)
    assert (
        h.container.observations.get(owner, UUID(original["id"])).description
        == "DEMO another independently confirmed edit"
    )
    assert port.lookup(owner, command.binding.action_key) is None
    action = uuid4()
    port.prepare(
        owner,
        api("PrepareCareReview")(
            binding=command.binding.model_copy(
                update={
                    "action_key": action,
                    "prepared_ref": BusinessRef(kind="care_review", id=action, version=1),
                    "expected_domain_revision": port.revision(owner),
                }
            )
        ),
    )
    fresh = h.view(view["task_id"])
    actual = port.apply(owner, save_observation(h, fresh, port))
    assert actual.result.description == "DEMO reviewed replacement"


def test_expired_run_rolls_back_native_care_work_before_publishing_completion(workflow, monkeypatch):
    from app.contracts.workflow_persistence import RunWriteBinding
    from app.infrastructure.durable_agent_runs import MemoryDurableRunControl

    from .test_durable_agent_runs import claimed

    h, owner = workflow, workflow.owner_ids["A"]
    view = prepared(h, "observation.add", fields(h, "observation.add"))
    port = harness(h)
    command = save_observation(h, view, port)
    state = h.container.assistant_workflows._repository._state
    run = claimed(MemoryDurableRunControl(clock=h.clock, state=state), owner)
    command = command.model_copy(
        update={
            "binding": command.binding.model_copy(
                update={"run_binding": RunWriteBinding(run_id=run.run_id, epoch=run.epoch)}
            )
        }
    )
    native_save = h.container.observations.save

    def slow_native_save(*args, **kwargs):
        result = native_save(*args, **kwargs)
        h.clock.advance(seconds=46)
        return result

    monkeypatch.setattr(h.container.observations, "save", slow_native_save)
    with pytest.raises(StaleVersionError):
        port.apply(owner, command)
    assert h.container.observations.get(owner, command.values.id) is None
    assert port.lookup(owner, command.binding.action_key) is None
    assert (
        h.container.assistant_workflows._repository.get(owner, command.binding.task_id).state == "awaiting_confirmation"
    )


@pytest.mark.parametrize("mismatch", [None, "patient_id", "description"])
def test_remote_care_uses_fixed_write_and_rejects_unrelated_native_results(workflow, mismatch):
    import httpx
    from app.domain.errors import AuthenticationRequiredError, ProviderUnavailableError

    h, owner = workflow, workflow.owner_ids["A"]
    view = prepared(h, "observation.add", fields(h, "observation.add"))
    local = harness(h)
    command = save_observation(h, view, local)
    applied = local.apply(owner, command)
    if mismatch:
        wrong = h.owner_ids["B"] if mismatch == "patient_id" else "DEMO unrelated note"
        applied = applied.model_copy(update={"result": applied.result.model_copy(update={mismatch: wrong})})
    calls = []

    def respond(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json=[] if request.method == "GET" else {"result": applied.model_dump(mode="json")})

    remote = remote_port(h, respond)
    if mismatch:
        with pytest.raises(ProviderUnavailableError):
            remote.apply(owner, command)
    else:
        assert remote.apply(owner, command) == applied
    assert calls == [("GET", "/rest/v1/assistant_business_receipts"), ("POST", "/rest/v1/rpc/assistant_care_write")]
    calls.clear()
    with pytest.raises(AuthenticationRequiredError):
        remote.apply(h.owner_ids["B"], command)
    assert calls == []


def test_remote_care_response_loss_reads_without_repeating_a_write(workflow):
    import httpx
    from app.domain.errors import ProviderUnavailableError

    h, owner = workflow, workflow.owner_ids["A"]
    view = prepared(h, "observation.add", fields(h, "observation.add"))
    local = harness(h)
    command = save_observation(h, view, local)
    applied = local.apply(owner, command)
    calls = []

    def respond(request):
        calls.append(request.url.path)
        if request.method == "GET":
            return httpx.Response(200, json=[applied.receipt.model_dump(mode="json")])
        assert request.url.path == "/rest/v1/rpc/assistant_care_read"
        return httpx.Response(200, json={"result": applied.model_dump(mode="json"), "replayed": True})

    remote = remote_port(h, respond)
    before = h.snapshot()
    assert remote.apply(owner, command) == applied and h.snapshot() == before
    assert len(calls) == 2
    calls.clear()

    def unavailable(request):
        if request.method == "GET":
            return respond(request)
        calls.append(request.url.path)
        return httpx.Response(200, json={"error": "unavailable"})

    with pytest.raises(ProviderUnavailableError):
        remote_port(h, unavailable).apply(owner, command)
    assert calls == ["/rest/v1/assistant_business_receipts", "/rest/v1/rpc/assistant_care_read"]


def test_remote_care_preparation_and_revision_use_owned_fixed_rpcs(workflow):
    import json

    import httpx

    h, owner = workflow, workflow.owner_ids["A"]
    view = h.start("observation.add", fields(h, "observation.add"))
    local = harness(h)
    action = uuid4()
    command = api("PrepareCareReview")(
        binding=WorkflowWriteBinding(
            task_id=UUID(view["task_id"]),
            task_revision=view["revision"],
            capability_id="observation.add",
            action_key=action,
            prepared_ref=BusinessRef(kind="care_review", id=action, version=1),
            expected_domain_revision=local.revision(owner),
        )
    )
    actual = local.prepare(owner, command)
    calls = []

    def respond(request):
        calls.append(request.url.path)
        if request.method == "GET":
            return httpx.Response(200, json=[])
        if request.url.path == "/rest/v1/rpc/assistant_care_revision":
            assert json.loads(request.content) == {}
            return httpx.Response(200, json={"revision": local.revision(owner)})
        assert request.url.path == "/rest/v1/rpc/assistant_care_prepare"
        assert json.loads(request.content) == {"p_command": command.model_dump(mode="json")}
        return httpx.Response(200, json={"result": actual.model_dump(mode="json")})

    remote = remote_port(h, respond)
    assert remote.revision(owner) == local.revision(owner)
    assert remote.prepare(owner, command) == actual
    assert len(calls) == 3


@pytest.mark.parametrize(
    "capability", ["inventory.count", "barrier.add", "followup.add", "followup.edit", "observation.delete"]
)
def test_remote_care_preserves_each_native_result_family(workflow, capability):
    from datetime import timedelta

    import httpx

    h, owner = workflow, workflow.owner_ids["A"]
    medicine = active_plan(h) if capability == "inventory.count" else None
    task = (
        h._request(
            "POST",
            "/api/me/care-tasks",
            json={
                "id": str(uuid4()),
                "title": "DEMO follow-up before edit",
                "category": "medication_review",
                "due_at": (h.clock.now() + timedelta(days=2)).isoformat(),
                "confirmed": True,
            },
        )
        if capability == "followup.edit"
        else None
    )
    observation = (
        h._request(
            "PUT",
            "/api/me/health-observations",
            json={
                "id": str(uuid4()),
                "description": "DEMO note before deletion",
                "occurred_at": h.clock.now().isoformat(),
                "confirmed": True,
            },
        )
        if capability == "observation.delete"
        else None
    )
    view = prepared(h, capability, fields(h, capability, medicine=medicine, task=task, observation=observation))
    local = harness(h)
    review = view["visible_fields"]["care_review"]
    kwargs = {"binding": binding(h, local, view), "confirmed": True}
    name, model = {
        "inventory.count": ("RecordStock", "StockInput"),
        "barrier.add": ("RecordBarrier", "BarrierInput"),
        "followup.add": ("CreateFollowup", "CareTaskInput"),
        "followup.edit": ("UpdateFollowup", "TaskUpdate"),
        "observation.delete": ("DeleteObservation", None),
    }[capability]
    if model:
        from app.contracts import long_term

        kwargs["values"] = getattr(long_term, model).model_validate({**review["payload"], "confirmed": True})
    if capability == "inventory.count":
        kwargs["medication_id"] = UUID(review["target_id"])
    elif capability == "followup.edit":
        kwargs.update(task_id=UUID(review["target_id"]), expected_version=1)
    elif capability == "observation.delete":
        kwargs["observation_id"] = UUID(review["target_id"])
    command = api(name)(**kwargs)
    actual = local.apply(owner, command)

    def respond(request):
        return httpx.Response(200, json=[] if request.method == "GET" else {"result": actual.model_dump(mode="json")})

    assert remote_port(h, respond).apply(owner, command) == actual


def test_care_sql_candidate_source_inventory_preserves_native_policy_boundaries():
    from pathlib import Path

    folder = Path(__file__).resolve().parents[2] / "supabase/review/assistant_workflows"
    up = (folder / "care.up.sql").read_text(encoding="utf-8")
    down = (folder / "care.down.sql").read_text(encoding="utf-8")
    assert up.strip().endswith("COMMIT;") and down.strip().endswith("COMMIT;")
    for name in ("assistant_care_prepare", "assistant_care_write", "assistant_care_read", "assistant_care_revision"):
        assert "CREATE FUNCTION public." + name + "(" in up
    for name in (
        "assistant_care_native_projection",
        "assistant_care_inventory",
        "assistant_care_reconcile_refill",
        "assistant_care_epoch_changed",
        "assistant_care_apply",
    ):
        assert "CREATE FUNCTION public." + name + "(" in up
    assert "assistant_run_assert_current" in up and "assistant_care_owner_first" in up
    assert "assistant_care_inventory_legacy_022" in up and "assistant_care_create_legacy_034" in up
    assert "Nonempty care transaction metadata must be retained" in down
    assert not any(
        "DROP TABLE public." + name in down
        for name in ("health_observations", "inventory_transactions", "medication_care_tasks", "adherence_barriers")
    )


def test_remote_followup_accepts_native_empty_reminder_array_for_disabled_scalar(workflow):
    import httpx

    h, owner = workflow, workflow.owner_ids["A"]
    view = prepared(h, "followup.add", fields(h, "followup.add"))
    local = harness(h)
    command = api("CreateFollowup")(
        binding=binding(h, local, view),
        confirmed=True,
        values=api("CareTaskInput").model_validate(
            {**view["visible_fields"]["care_review"]["payload"], "confirmed": True}
        ),
    )
    result = local.apply(owner, command)
    # Native034 materializes [] for an explicitly disabled scalar reminder.
    row = result.result.model_copy(update={"reminder_offsets": []})
    actual = result.model_copy(update={"result": row})

    def respond(request):
        return httpx.Response(200, json=[] if request.method == "GET" else {"result": actual.model_dump(mode="json")})

    assert remote_port(h, respond).apply(owner, command) == actual
