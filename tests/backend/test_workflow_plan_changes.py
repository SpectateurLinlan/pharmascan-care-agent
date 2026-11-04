"""DEMO plan-version changes use actual enrollment policy and memory transactions."""

from uuid import UUID, uuid4

import pytest

from .test_workflow_enrollment_operations import services
from .test_workflow_medication_management import active_plan


def update_input(h, old, **changes):
    from app.contracts.enrollment_operations import PlanChangeOperationInput

    return PlanChangeOperationInput(
        action_key=uuid4(),
        workflow_task_id=uuid4(),
        workflow_revision=1,
        predecessor_id=UUID(old["regimen_id"]),
        expected_version=1,
        expected_state="active",
        fields={"frequency_rule": {"kind": "daily", "local_times": ["21:00"]}, **changes},
    )


def test_successor_preparation_preserves_old_plan_sources_and_reports_until_independent_activation(workflow):
    h = workflow
    old = active_plan(h)
    service, _ = services(h)
    before = h.snapshot()
    result = service.prepare_plan_change_once(h.owner_ids["A"], update_input(h, old))
    assert result.medication.id == UUID(old["medication_id"])
    assert result.regimen.supersedes_id == UUID(old["regimen_id"]) and result.regimen.version_no == 2
    assert result.regimen.state.value == "draft" and result.regimen.patient_edited
    assert result.regimen.frequency_rule["local_times"] == ["21:00"]
    after = h.snapshot()
    assert next(row for row in after["regimens"] if row["id"] == old["regimen_id"]) == before["regimens"][0]
    for row in before["sources"]:
        assert row in after["sources"]
    assert after["dose_events"] == before["dose_events"] and len(after["medications"]) == 1


def test_plan_change_receipt_handles_response_loss_and_refuses_changed_same_key_inputs(workflow):
    from app.domain.errors import DuplicateEventError

    h = workflow
    old = active_plan(h)
    service, _ = services(h)
    values = update_input(h, old)
    first = service.prepare_plan_change_once(h.owner_ids["A"], values)
    replay = service.prepare_plan_change_once(h.owner_ids["A"], values)
    assert first.regimen.id == replay.regimen.id and len(h.snapshot()["regimens"]) == 2
    changed = values.model_copy(update={"fields": values.fields.model_copy(update={"dose_amount": 2})})
    with pytest.raises(DuplicateEventError):
        service.prepare_plan_change_once(h.owner_ids["A"], changed)


@pytest.mark.parametrize("failure", ["owner", "version", "stopped"])
def test_update_preparation_rejects_a_foreign_stale_or_changed_predecessor_without_new_rows(workflow, failure):
    from app.domain.errors import NotFoundError, StaleVersionError

    h = workflow
    old = active_plan(h)
    service, _ = services(h)
    values = update_input(h, old)
    if failure == "version":
        values = values.model_copy(update={"expected_version": 2})
    if failure == "stopped":
        h.container.enrollment.end_regimen(patient_id=h.owner_ids["A"], regimen_id=UUID(old["regimen_id"]))
    before = h.snapshot()
    with pytest.raises((NotFoundError, StaleVersionError)):
        service.prepare_plan_change_once(h.owner_ids["B" if failure == "owner" else "A"], values)
    assert h.snapshot()["sources"] == before["sources"] and h.snapshot()["regimens"] == before["regimens"]


def test_explicit_null_change_survives_closed_task_serialization_and_clears_optional_instruction(workflow):
    from app.contracts.assistant_workflows import validate_workflow_values

    fields = validate_workflow_values(
        "medication.plan.change",
        {
            "regimen_id": str(uuid4()),
            "expected_version": 1,
            "expected_state": "active",
            "details": {"food_instruction": None},
        },
    )
    serialized = fields.model_dump(mode="json", exclude_none=True)
    assert "food_instruction" in serialized["details"] and serialized["details"]["food_instruction"] is None
    assert validate_workflow_values("medication.plan.change", serialized) == fields


def bound_successor(h):
    from app.contracts.assistant_workflows import BusinessRef, WorkflowTask

    old = active_plan(h)
    operation, _ = services(h)
    values = update_input(h, old)
    result = operation.prepare_plan_change_once(h.owner_ids["A"], values)
    h.container.assistant_workflows._repository.create(
        WorkflowTask(
            id=values.workflow_task_id,
            owner=h.owner_ids["A"],
            workspace_id=uuid4(),
            capability_id="medication.plan.change",
            state="awaiting_confirmation",
            save_mode="allowed",
            storage_state="saved",
            updated_at=h.clock.now(),
            business_refs=(BusinessRef(kind="regimen", id=result.regimen.id, version=result.regimen.version_no),),
        )
    )
    return old, result


def test_failed_activation_rolls_back_old_plan_retirement_rules_challenge_and_new_plan(workflow, monkeypatch):
    from .test_workflow_draft_recovery import challenge

    h = workflow
    old, successor = bound_successor(h)
    owner = h.owner_ids["A"]
    confirm = challenge(h, {"id": str(successor.regimen.id)}, old["session_id"])
    h.container.enrollment.confirm_challenge(patient_id=owner, challenge_id=UUID(confirm["challenge_id"]))
    before = h.snapshot()
    store = h.container.store
    rules = dict(store.dose_rules.items())
    challenges = dict(store.challenges.items())
    revision = store.clinical.revisions.copy()

    def unavailable(**kwargs):
        raise OSError("DEMO schedule publication unavailable")

    monkeypatch.setattr(h.container.enrollment, "_persist_dose_rules", unavailable)
    with pytest.raises(OSError, match="DEMO schedule publication unavailable"):
        h.container.enrollment.activate_regimen(
            patient_id=owner,
            regimen_id=successor.regimen.id,
            challenge_id=UUID(confirm["challenge_id"]),
            session_state=confirm["session_state"],
            session_state_version=confirm["session_state_version"],
        )
    assert h.snapshot()["regimens"] == before["regimens"] and h.snapshot()["medications"] == before["medications"]
    assert dict(store.dose_rules.items()) == rules and dict(store.challenges.items()) == challenges
    assert store.clinical.revisions == revision and h.snapshot()["dose_events"] == before["dose_events"]


def plan_engine(h):
    from app.application.assistant_capabilities.plan_changes import PlanChangeAdapter
    from app.application.assistant_workflows import WorkflowService

    old = h.container.assistant_workflows
    adapter = PlanChangeAdapter(
        enrollment=h.container.enrollment,
        operations=services(h)[0],
        delegate=old._adapters["medication.enroll"],
        tasks=old._repository,
    )
    return WorkflowService(
        repository=old._repository,
        registry=old._registry,
        adapters={**old._adapters, "medication.plan.change": adapter},
        writers={**old._writers, "medication.plan.change": adapter},
        clock=h.clock,
        ids=h.container.ids,
        conversations=h.container.conversation_threads,
        preferences=h.container.preferences,
        controls=old._controls,
        attachments=h.container.assistant_attachments,
        cleanup=h.container.assistant_cleanup,
    )


def event(service, owner, view, kind, values=None, event_id=None):
    from app.contracts.assistant_workflows import WorkflowEvent

    return service.advance(
        owner,
        view.task_id,
        WorkflowEvent(event_id=event_id or uuid4(), expected_revision=view.revision, kind=kind, values=values or {}),
    )


def selected_plan(h, service, old, save="allowed"):
    return service.start(
        h.owner_ids["A"],
        "medication.plan.change",
        uuid4(),
        None,
        {"regimen_id": old["regimen_id"], "expected_version": 1, "expected_state": "active"},
        save,
    )


def test_plan_workflow_prefills_recorded_values_but_cannot_save_unchanged_inputs(workflow):
    from app.domain.errors import ValidationError

    h = workflow
    old = active_plan(h)
    service = plan_engine(h)
    view = selected_plan(h, service, old)
    assert view.state == "collecting" and "changed_instructions" in view.missing_fields
    assert view.visible_fields["frequency_rule"]["local_times"] == ["20:00"]
    assert view.visible_fields["original_plan"]["regimen_id"] == old["regimen_id"]
    assert any(action.kind == "fields" for action in view.actions)
    with pytest.raises(ValidationError):
        event(service, h.owner_ids["A"], view, "prepare_confirmation")
    assert len(h.snapshot()["regimens"]) == 1


def test_chat_plan_change_uses_independent_activation_and_real_superseded_readback(workflow):
    from .test_workflow_draft_recovery import activate, challenge

    h = workflow
    old = active_plan(h)
    service = plan_engine(h)
    owner = h.owner_ids["A"]
    before = h.snapshot()
    view = selected_plan(h, service, old)
    ready = event(
        service,
        owner,
        view,
        "provide_fields",
        {"details": {"frequency_rule": {"kind": "daily", "local_times": ["21:00"]}}},
    )
    assert ready.state == "ready_for_review" and h.snapshot()["regimens"] == before["regimens"]
    saved = event(service, owner, ready, "prepare_confirmation")
    assert saved.actions[0].component_key == "existing_activation"
    assert h.container.enrollment.get_regimen(owner, UUID(old["regimen_id"])).state.value == "active"
    confirm = challenge(h, saved.result_ref.model_dump(mode="json"), old["session_id"])
    assert activate(h, saved.result_ref.model_dump(mode="json"), confirm).status_code == 200
    result = event(service, owner, saved, "report_business_result")
    assert (
        result.state == "completed"
        and h.container.enrollment.get_regimen(owner, UUID(old["regimen_id"])).state.value == "superseded"
    )
    assert h.snapshot()["sources"][: len(before["sources"])] == before["sources"]
    assert h.snapshot()["dose_events"] == before["dose_events"]


def test_no_save_change_never_creates_a_business_successor_and_keeps_closed_page_inputs(workflow):
    from app.contracts.assistant_workflows import WorkflowEvent, validate_workflow_values

    h = workflow
    old = active_plan(h)
    service = plan_engine(h)
    owner = h.owner_ids["A"]
    view = selected_plan(h, service, old, "ephemeral")
    before = h.snapshot()
    payload = {"capability_id": view.capability_id, "fields": view.input_fields}
    ready = service.advance(
        owner,
        view.task_id,
        WorkflowEvent(
            event_id=uuid4(),
            expected_revision=view.revision,
            kind="provide_fields",
            values={"details": {"frequency_rule": {"kind": "daily", "local_times": ["21:00"]}}},
        ),
        ephemeral=payload,
    )
    validate_workflow_values(ready.capability_id, ready.input_fields)
    assert ready.save_mode == "ephemeral" and h.snapshot()["regimens"] == before["regimens"]
    assert all(str(view.task_id) != row["id"] for row in h.snapshot()["tasks"])


@pytest.mark.parametrize(
    "forged",
    [
        {"medication_name": "other"},
        {"supersedes_regimen_id": str(uuid4())},
        {"patient_edited": True},
        {"dose_basis": {"patient_checked": True}},
    ],
)
def test_changed_instructions_reject_identity_confirmation_and_linkage_overrides(forged):
    from app.contracts.medication_plan_changes import PlanChangeDetails
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PlanChangeDetails.model_validate(forged)


def test_ended_plan_creates_only_an_unactivated_new_course_without_resuming_it(workflow):
    h = workflow
    old = active_plan(h)
    owner = h.owner_ids["A"]
    h.container.enrollment.end_regimen(patient_id=owner, regimen_id=UUID(old["regimen_id"]))
    operation, _ = services(h)
    values = update_input(h, old).model_copy(update={"expected_state": "ended"})
    result = operation.prepare_plan_change_once(owner, values)
    assert result.regimen.supersedes_id is None and result.regimen.state.value == "draft"
    assert h.container.enrollment.get_regimen(owner, UUID(old["regimen_id"])).state.value == "ended"


def test_stopping_original_after_preparation_refuses_review_challenge_and_activation(workflow):
    from .test_workflow_draft_recovery import activate, challenge

    h = workflow
    old, result = bound_successor(h)
    owner = h.owner_ids["A"]
    confirm = challenge(h, {"id": str(result.regimen.id)}, old["session_id"])
    h.container.enrollment.end_regimen(patient_id=owner, regimen_id=UUID(old["regimen_id"]))
    before = h.snapshot()
    assert activate(h, {"id": str(result.regimen.id)}, confirm).status_code == 409
    assert h.snapshot()["regimens"] == before["regimens"]
    response = h.client.post(
        f"/api/medications/drafts/{result.regimen.id}/challenge",
        params={"client_id": "DEMO-workflow-A", "session_id": old["session_id"]},
        json={},
    )
    assert response.status_code == 409


def test_concurrent_same_key_preparations_create_one_successor(workflow):
    from concurrent.futures import ThreadPoolExecutor

    h = workflow
    old = active_plan(h)
    operation, _ = services(h)
    values = update_input(h, old)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: operation.prepare_plan_change_once(h.owner_ids["A"], values), range(2)))
    assert results[0].regimen.id == results[1].regimen.id and len(h.snapshot()["regimens"]) == 2


def test_explicit_clear_is_not_replaced_with_original_values_and_prn_has_no_fixed_schedule(workflow):
    from app.contracts.medication_plan_changes import PlanChangeDetails

    h = workflow
    old = active_plan(h)
    owner = h.owner_ids["A"]
    operation, _ = services(h)
    result = operation.prepare_plan_change_once(owner, update_input(h, old, food_instruction="with food"))
    # Pure preview of the successor's recorded instructions is only valid after
    # activation; use the existing independent patient flow, never mutate a row.
    # The original itself has no food instruction, so first verify the set patch.
    assert result.regimen.food_instruction == "with food"
    proposed = operation.plan_change_preview(
        owner,
        UUID(old["regimen_id"]),
        1,
        "active",
        PlanChangeDetails(
            is_prn=True,
            frequency_rule=None,
            food_instruction="Only when needed per original instructions",
            course_end_date=None,
        ),
    )
    assert proposed.changed and not proposed.preview.missing_fields
    assert proposed.preview.normalized_draft.frequency_rule is None
    assert proposed.preview.normalized_draft.is_prn


@pytest.mark.parametrize("phrase", ["change a medication plan", "修改用药计划"])
def test_plan_change_chat_entry_selects_owned_plans_without_creating_a_version(workflow, phrase):
    from .test_workflow_enrollment import message

    h = workflow
    active_plan(h)
    before = h.snapshot()
    response = message(h, phrase)
    assert response["reply"]["mode"] == "workflow"
    assert response["workflow"]["capability_id"] == "medication.plan.change"
    assert response["workflow"]["actions"][0]["action_id"] == "medication.change_target"
    assert h.snapshot()["regimens"] == before["regimens"]


def test_prepared_plan_change_recovers_its_original_task_and_retains_confirmation_authority(workflow):
    h = workflow
    old = active_plan(h)
    task = h.start(
        "medication.plan.change",
        {
            "regimen_id": old["regimen_id"],
            "expected_version": 1,
            "expected_state": "active",
            "details": {"dose_amount": 2},
        },
    )
    saved = h.event(task["task_id"], "prepare_confirmation")
    recovery = h.start("medication.draft.resume", {"regimen_id": saved["result_ref"]["id"], "expected_version": 2})
    assert recovery["actions"][0]["kind"] == "resume_task"
    resumed = h._request(
        "POST",
        f"/api/agent/workflows/tasks/{recovery['task_id']}/resume-draft",
        json={"expected_revision": recovery["revision"]},
    )
    assert resumed["task_id"] == task["task_id"] and resumed["state"] == "awaiting_confirmation"
    assert h.container.enrollment.get_regimen(h.owner_ids["A"], UUID(old["regimen_id"])).state.value == "active"


@pytest.mark.parametrize("language,text", [("en", "dose: 2 tablets; 21:00"), ("zh", "每次2片；21:00")])
def test_chat_collects_changed_dose_and_time_into_closed_details(workflow, language, text):
    from .test_workflow_enrollment import message

    h = workflow
    old = active_plan(h)
    h._request("PUT", "/api/me/preferences", json={"preferred_language": language})
    task = h.start(
        "medication.plan.change", {"regimen_id": old["regimen_id"], "expected_version": 1, "expected_state": "active"}
    )
    result = message(h, text, task, language=language)
    assert result["workflow"]["visible_fields"]["dose_amount"] == 2
    assert result["workflow"]["visible_fields"]["frequency_rule"]["local_times"] == ["21:00"]
    assert result["workflow"]["input_fields"]["details"]["dose_amount"] == 2
    assert result["workflow"]["state"] == "ready_for_review" and len(h.snapshot()["regimens"]) == 1


def test_null_clear_changes_the_actual_successor_instead_of_restoring_old_instruction(workflow):
    from .test_workflow_draft_recovery import activate, challenge

    h = workflow
    old = active_plan(h)
    task = h.start(
        "medication.plan.change",
        {
            "regimen_id": old["regimen_id"],
            "expected_version": 1,
            "expected_state": "active",
            "details": {"food_instruction": "with food"},
        },
    )
    saved = h.event(task["task_id"], "prepare_confirmation")
    confirm = challenge(h, saved["result_ref"], old["session_id"])
    assert activate(h, saved["result_ref"], confirm).status_code == 200
    h.event(task["task_id"], "report_business_result")
    operation, _ = services(h)
    from app.contracts.enrollment_operations import PlanChangeOperationInput

    actual = operation.prepare_plan_change_once(
        h.owner_ids["A"],
        PlanChangeOperationInput(
            action_key=uuid4(),
            workflow_task_id=uuid4(),
            workflow_revision=1,
            predecessor_id=UUID(saved["result_ref"]["id"]),
            expected_version=2,
            expected_state="active",
            fields={"food_instruction": None},
        ),
    )
    assert actual.regimen.food_instruction is None


def test_pause_and_resume_invalidates_an_already_issued_change_challenge(workflow):
    from .test_workflow_draft_recovery import activate, challenge

    h = workflow
    old = active_plan(h)
    task = h.start(
        "medication.plan.change",
        {
            "regimen_id": old["regimen_id"],
            "expected_version": 1,
            "expected_state": "active",
            "details": {"dose_amount": 2},
        },
    )
    saved = h.event(task["task_id"], "prepare_confirmation")
    confirm = challenge(h, saved["result_ref"], old["session_id"])
    h.event(task["task_id"], "pause")
    h.event(task["task_id"], "resume")
    before = h.snapshot()
    assert activate(h, saved["result_ref"], confirm).status_code == 409
    assert h.snapshot()["regimens"] == before["regimens"]


def test_lost_workflow_metadata_reconciles_real_successor_before_predecessor_revalidation(workflow, monkeypatch):
    from app.domain.errors import ProviderUnavailableError

    h = workflow
    old = active_plan(h)
    task = h.start(
        "medication.plan.change",
        {
            "regimen_id": old["regimen_id"],
            "expected_version": 1,
            "expected_state": "active",
            "details": {"dose_amount": 2},
        },
    )
    repository = h.container.assistant_workflows._repository
    original = repository.cas

    def lost(*args, **kwargs):
        raise ProviderUnavailableError("DEMO metadata unavailable")

    monkeypatch.setattr(repository, "cas", lost)
    with pytest.raises(AssertionError):
        h.event(task["task_id"], "prepare_confirmation")
    assert len(h.snapshot()["regimens"]) == 2
    monkeypatch.setattr(repository, "cas", original)
    h.container.enrollment.end_regimen(patient_id=h.owner_ids["A"], regimen_id=UUID(old["regimen_id"]))
    recovered = h.event(task["task_id"], "report_business_result", revision=task["revision"])
    assert recovered["result_ref"] and recovered["state"] == "failed_recoverable"
    assert not recovered["actions"] and len(h.snapshot()["regimens"]) == 2


def test_independent_change_preserves_an_existing_self_report_and_reported_occurrence(workflow):
    from .test_workflow_draft_recovery import activate, challenge

    h = workflow
    old = active_plan(h)
    h.clock.advance(hours=13)
    due = h._request("GET", "/api/doses/due", params={"regimen_id": old["regimen_id"]})
    occurrence = due["occurrence_id"]
    assert occurrence
    report = {"regimen_id": old["regimen_id"], "intake_status": "taken", "idempotency_key": str(uuid4())}
    confirmation = h._request("POST", f"/api/doses/{occurrence}/report/challenge", json=report)
    h._request("POST", f"/api/doses/{occurrence}/report", json={**report, "challenge_id": confirmation["challenge_id"]})
    before = h.snapshot()
    assert len(before["dose_events"]) == 1
    stored_occurrence = h.container.store.occurrences[(h.owner_ids["A"], UUID(occurrence))]
    task = h.start(
        "medication.plan.change",
        {
            "regimen_id": old["regimen_id"],
            "expected_version": 1,
            "expected_state": "active",
            "details": {"frequency_rule": {"kind": "daily", "local_times": ["21:00"]}},
        },
    )
    saved = h.event(task["task_id"], "prepare_confirmation")
    summary = challenge(h, saved["result_ref"], old["session_id"])
    assert activate(h, saved["result_ref"], summary).status_code == 200
    assert h.snapshot()["dose_events"] == before["dose_events"]
    assert h.container.store.occurrences[(h.owner_ids["A"], UUID(occurrence))] == stored_occurrence


def test_separate_instruction_replies_retain_prior_changes_and_explicit_clears(workflow):
    h = workflow
    old = active_plan(h)
    task = h.start(
        "medication.plan.change",
        {
            "regimen_id": old["regimen_id"],
            "expected_version": 1,
            "expected_state": "active",
        },
    )
    first = h.event(task["task_id"], "provide_fields", {"details": {"dose_amount": 2, "food_instruction": None}})
    second = h.event(
        task["task_id"],
        "provide_fields",
        {
            "details": {"frequency_rule": {"kind": "daily", "local_times": ["21:00"]}},
        },
        revision=first["revision"],
    )
    assert second["visible_fields"]["dose_amount"] == 2
    assert "food_instruction" in second["input_fields"]["details"]
    assert second["input_fields"]["details"]["food_instruction"] is None


def test_interval_change_preserves_the_server_default_first_time_provenance(workflow):
    from app.contracts.medication_plan_changes import PlanChangeDetails

    h = workflow
    session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})
    old = h._request(
        "POST",
        "/api/medications/drafts",
        json={
            "medication_name": "DEMO interval plan",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_kind": "interval",
            "frequency_every_hours": 6,
            "course_start_date": "2026-10-13",
        },
    )
    from .test_workflow_draft_recovery import activate, challenge

    ref = {"id": old["regimen_id"]}
    summary = challenge(h, ref, session["session_id"])
    assert activate(h, ref, summary).status_code == 200
    operation, _ = services(h)
    preview = operation.plan_change_preview(h.owner_ids["A"], UUID(old["regimen_id"]), 1, "active", None)
    assert preview.changed is False
    proposed = operation.plan_change_preview(
        h.owner_ids["A"], UUID(old["regimen_id"]), 1, "active", PlanChangeDetails(dose_amount=2)
    )
    assert proposed.preview.normalized_draft.frequency_rule.interval_anchor.time_source == "default_0800"
