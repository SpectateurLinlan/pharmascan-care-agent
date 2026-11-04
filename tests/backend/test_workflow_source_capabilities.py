"""Real source adapters in a test-only composition; public catalog remains gated."""

from uuid import uuid4

import pytest
from app.application.assistant_workflows import WorkflowService
from app.contracts.assistant_workflows import WorkflowEvent

from .test_workflow_source_transport import source_review
from .test_workflow_sources import inputs, provider


def source_engine(h):
    from app.application.assistant_capabilities.draft_recovery import DraftRecoveryAdapter
    from app.application.assistant_capabilities.sources import SourceAdapter
    from app.infrastructure.clinical_memory import MemoryClinicalMutationGuard
    from app.infrastructure.memory_workflows import MemoryActionRepository

    original = h.container.assistant_workflows
    adapter = SourceAdapter(
        enrollment=h.container.enrollment,
        evidence=h.container.evidence_enrollment,
        enrollment_adapter=original._adapters["medication.enroll"],
        operations=original._adapters["medication.enroll"]._operations,
        actions=MemoryActionRepository(h.clock, state=original._repository._state),
    )
    recovery = DraftRecoveryAdapter(
        h.container.enrollment,
        original._adapters["medication.enroll"]._operations,
        original._adapters["medication.enroll"],
        original._repository,
        original._controls,
        MemoryClinicalMutationGuard(h.container.store.clinical),
        source_capabilities=adapter.capability_ids,
    )
    return WorkflowService(
        repository=original._repository,
        registry=original._registry,
        adapters={
            **original._adapters,
            **dict.fromkeys(adapter.capability_ids, adapter),
            "medication.draft.resume": recovery,
        },
        writers={
            **original._writers,
            **dict.fromkeys(adapter.capability_ids, adapter),
            "medication.draft.resume": recovery,
        },
        patient_results=dict.fromkeys(adapter.capability_ids, adapter),
        clock=h.clock,
        ids=h.container.ids,
        conversations=h.container.conversation_threads,
        preferences=h.container.preferences,
        controls=original._controls,
        attachments=h.container.assistant_attachments,
        cleanup=h.container.assistant_cleanup,
        task_resumers={"medication.draft.resume": recovery},
        patient_guards={**original._patient_guards, **dict.fromkeys(adapter.capability_ids, recovery)},
    )


def event(service, owner, view, kind, values=None):
    return service.advance(
        owner,
        view.task_id,
        WorkflowEvent(
            event_id=uuid4(),
            expected_revision=view.revision,
            kind=kind,
            values=values or {},
        ),
    )


def test_source_review_captures_only_the_actual_patient_plan_and_waits_for_activation(workflow, monkeypatch):
    h = workflow
    provider(h, monkeypatch)
    target = h.container.evidence_enrollment.attach(**inputs(h))
    service = source_engine(h)
    owner = h.owner_ids["A"]
    started = service.start(
        owner,
        "medication.source.review",
        uuid4(),
        None,
        {"source_task_id": str(target.id), "expected_version": target.version},
        "allowed",
    )
    assert started.state == "ready_for_review" and not h.snapshot()["regimens"]
    prepared = event(service, owner, started, "prepare_confirmation")
    assert (
        prepared.result_ref.kind == "enrollment_task" and prepared.actions[0].component_key == "existing_source_review"
    )
    unchanged = event(service, owner, prepared, "report_business_result")
    assert unchanged.result_ref.kind == "enrollment_task" and not h.snapshot()["regimens"]
    response = source_review(h, service._context(service._repository.get(owner, unchanged.task_id)), target)
    assert response.status_code == 200, response.text
    captured = event(service, owner, unchanged, "report_business_result")
    assert captured.result_ref.kind == "regimen" and str(captured.result_ref.id) == response.json()["draft_regimen_id"]
    assert captured.state == "awaiting_confirmation" and captured.actions[0].component_key == "existing_activation"
    assert h.snapshot()["regimens"][0]["state"] == "draft" and not h.snapshot()["dose_events"]
    again = event(service, owner, captured, "report_business_result")
    assert again.result_ref == captured.result_ref and again.state == "awaiting_confirmation"


def test_result_event_rejects_client_supplied_success_or_result_ids(workflow, monkeypatch):
    h = workflow
    provider(h, monkeypatch)
    target = h.container.evidence_enrollment.attach(**inputs(h))
    service = source_engine(h)
    owner = h.owner_ids["A"]
    first = service.start(
        owner,
        "medication.source.review",
        uuid4(),
        None,
        {"source_task_id": str(target.id), "expected_version": target.version},
        "allowed",
    )
    prepared = event(service, owner, first, "prepare_confirmation")
    from app.domain.errors import ValidationError

    with pytest.raises(ValidationError):
        event(service, owner, prepared, "report_business_result", {"regimen_id": str(uuid4()), "success": True})
    assert service.view(owner, prepared.task_id).revision == prepared.revision


def test_source_preparation_never_creates_a_medication_before_patient_save(workflow):
    h = workflow
    service = source_engine(h)
    owner = h.owner_ids["A"]
    started = service.start(owner, "medication.source.add", uuid4(), None, {}, "allowed")
    assert "source_image" in started.missing_fields
    assert not h.snapshot()["medications"] and not h.snapshot()["sources"]
    from app.domain.errors import ValidationError

    with pytest.raises(ValidationError):
        event(service, owner, started, "prepare_confirmation")


def test_unbound_external_source_review_cannot_be_adopted_as_patient_success(workflow, monkeypatch):
    from .test_workflow_source_review import review

    h = workflow
    provider(h, monkeypatch)
    target = h.container.evidence_enrollment.attach(**inputs(h))
    service = source_engine(h)
    owner = h.owner_ids["A"]
    started = service.start(
        owner,
        "medication.source.review",
        uuid4(),
        None,
        {"source_task_id": str(target.id), "expected_version": target.version},
        "allowed",
    )
    prepared = event(service, owner, started, "prepare_confirmation")
    review(h, target)  # Explicit original app action, not this Assistant confirmation.
    current = event(service, owner, prepared, "report_business_result")
    assert current.result_ref.kind == "enrollment_task" and current.state != "completed"
    assert not current.actions


def test_photo_source_patient_save_then_review_produces_one_plan_without_second_recognition():
    from .test_workflow_originals import original_png
    from .test_workflow_photo_enrollment import label
    from .test_workflow_source_transport import save
    from .workflow_support import WorkflowHarness

    with WorkflowHarness(source_results=[label()]) as h:
        service = source_engine(h)
        owner = h.owner_ids["A"]
        start = service.start(owner, "medication.source.add", uuid4(), None, {}, "allowed")
        attachment_service = h.container.assistant_attachments
        uploaded = attachment_service.accept(
            attachment_service.context(owner, start.task_id, start.revision), uuid4(), original_png(), "image/png", True
        )
        ready = service.view(owner, start.task_id)
        assert ready.state == "ready_for_review" and not h.snapshot()["sources"]
        pending = event(service, owner, ready, "prepare_confirmation")
        assert pending.visible_fields["source_saved"] is False and not h.snapshot()["medications"]
        context = service._context(service._repository.get(owner, pending.task_id))
        saved = save(h, context, pending.result_ref.id, uploaded.id)
        assert saved.status_code == 200, saved.text
        saved_view = event(service, owner, pending, "report_business_result")
        assert (
            saved_view.result_ref.version == saved.json()["version"]
            and saved_view.visible_fields["source_saved"] is True
        )
        assert len(h.source_calls) == 1 and not h.snapshot()["regimens"]
        actual = h.container.evidence_enrollment.get(owner, pending.result_ref.id)
        context = service._context(service._repository.get(owner, saved_view.task_id))
        result = source_review(
            h,
            context,
            actual,
            draft={
                "medication_name": actual.product.name,
                "dose_amount": 1,
                "dose_unit": "tablet",
                "frequency_rule": {"kind": "daily", "local_times": ["08:00", "20:00"]},
            },
        )
        assert result.status_code == 200, result.text
        captured = event(service, owner, saved_view, "report_business_result")
        assert captured.result_ref.kind == "regimen" and captured.state == "awaiting_confirmation"
        assert captured.actions[0].component_key == "existing_activation"
        assert len(h.source_calls) == len(h.snapshot()["regimens"]) == 1
        assert attachment_service.read(owner, captured.task_id, uploaded.id)[0] == original_png()
        from .test_workflow_draft_recovery import activate, challenge

        session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})
        ref = captured.result_ref.model_dump(mode="json")
        old_challenge = challenge(h, ref, session["session_id"])
        paused = event(service, owner, captured, "pause")
        resumed = event(service, owner, paused, "resume")
        assert activate(h, ref, old_challenge).status_code in {409, 422}
        current = challenge(h, ref, session["session_id"])
        assert activate(h, ref, current).status_code == 200
        completed = event(service, owner, resumed, "report_business_result")
        assert completed.state == "completed"


def test_source_add_rejects_foreign_medication_before_requesting_a_photo(workflow):
    from app.contracts.dto import RegimenDraftInput
    from app.domain.errors import NotFoundError

    h = workflow
    h.container.enrollment.enroll_draft(
        patient_id=h.owner_ids["B"], draft=RegimenDraftInput(medication_name="DEMO foreign source medicine")
    )
    service = source_engine(h)
    medication = h.container.enrollment.list_medications(h.owner_ids["B"])[0]
    with pytest.raises(NotFoundError):
        service.start(
            h.owner_ids["A"], "medication.source.add", uuid4(), None, {"medication_id": str(medication.id)}, "allowed"
        )
    assert not h.container.assistant_workflows.saved_tasks(h.owner_ids["A"])


@pytest.mark.parametrize("capability", ["medication.source.add", "medication.source.review"])
def test_source_target_version_pair_and_patient_authority_fields_are_closed(capability):
    from app.contracts.assistant_workflows import validate_workflow_values
    from pydantic import ValidationError

    for values in (
        {"expected_version": 1},
        {"source_task_id": str(uuid4())},
        {"patient_reviewed": True},
        {"confirmed": True},
        {"patient_id": str(uuid4())},
    ):
        with pytest.raises(ValidationError):
            validate_workflow_values(capability, values)


@pytest.mark.parametrize("capture_first", [True, False])
def test_source_backed_draft_recovery_returns_to_original_task_even_after_lost_capture(
    workflow, monkeypatch, capture_first
):
    h = workflow
    provider(h, monkeypatch)
    target = h.container.evidence_enrollment.attach(**inputs(h))
    service = source_engine(h)
    owner = h.owner_ids["A"]
    started = service.start(
        owner,
        "medication.source.review",
        uuid4(),
        None,
        {"source_task_id": str(target.id), "expected_version": target.version},
        "allowed",
    )
    prepared = event(service, owner, started, "prepare_confirmation")
    response = source_review(h, service._context(service._repository.get(owner, prepared.task_id)), target)
    assert response.status_code == 200, response.text
    if capture_first:
        prepared = event(service, owner, prepared, "report_business_result")
    recovery = service.start(
        owner,
        "medication.draft.resume",
        uuid4(),
        None,
        {"regimen_id": response.json()["draft_regimen_id"], "expected_version": 1},
        "allowed",
    )
    assert any(action.kind == "resume_task" for action in recovery.actions)
    before = h.snapshot()
    resumed = service.resume_draft(owner, recovery.task_id, recovery.revision)
    assert resumed.task_id == prepared.task_id and resumed.result_ref.kind == "regimen"
    assert resumed.actions[0].component_key == "existing_activation"
    assert h.snapshot()["regimens"] == before["regimens"] and h.snapshot()["sources"] == before["sources"]


def test_source_prepared_plan_can_separately_review_its_original_manual_name(workflow, monkeypatch):
    from app.contracts.dto import RegimenDraftInput

    h = workflow
    previous = h.container.enrollment.enroll_draft(
        patient_id=h.owner_ids["A"], draft=RegimenDraftInput(medication_name="Metformin")
    )
    provider(h, monkeypatch)
    values = inputs(h)
    values["medication_id"] = previous.medication.id
    target = h.container.evidence_enrollment.attach(**values)
    service = source_engine(h)
    h.container.assistant_workflows = service
    owner = h.owner_ids["A"]
    start = service.start(
        owner,
        "medication.source.review",
        uuid4(),
        None,
        {"source_task_id": str(target.id), "expected_version": target.version},
        "allowed",
    )
    pending = event(service, owner, start, "prepare_confirmation")
    response = source_review(h, service._context(service._repository.get(owner, pending.task_id)), target)
    assert response.status_code == 200, response.text
    captured = event(service, owner, pending, "report_business_result")
    original_source = h.container.enrollment.get_source(owner, previous.regimen.source_id)
    response = h.client.post(
        f"/api/medications/drafts/{captured.result_ref.id}/identity-review",
        params={"client_id": "DEMO-workflow-A"},
        headers={"X-Assistant-Task": str(captured.task_id), "X-Assistant-Revision": str(captured.revision)},
        json={"confirmed": True},
    )
    assert response.status_code == 200, response.text
    assert h.container.enrollment.get_source(owner, original_source.id) == original_source
    assert h.container.enrollment.original_identity_review(owner, captured.result_ref.id) is None


@pytest.mark.parametrize("save_plan", [False, True])
def test_source_no_save_uses_closed_page_inputs_and_explicit_resave_reuses_existing_records(
    workflow, monkeypatch, save_plan
):
    from app.contracts.assistant_workflows import validate_workflow_values

    h = workflow
    provider(h, monkeypatch)
    target = h.container.evidence_enrollment.attach(**inputs(h))
    service = source_engine(h)
    owner = h.owner_ids["A"]
    current = service.start(
        owner,
        "medication.source.review",
        uuid4(),
        None,
        {"source_task_id": str(target.id), "expected_version": target.version},
        "allowed",
    )
    current = event(service, owner, current, "prepare_confirmation")
    if save_plan:
        response = source_review(h, service._context(service._repository.get(owner, current.task_id)), target)
        assert response.status_code == 200, response.text
        current = event(service, owner, current, "report_business_result")
    before = h.snapshot()
    revoked = event(service, owner, current, "cancel_save")
    fields = revoked.input_fields if revoked.input_fields is not None else revoked.visible_fields
    validate_workflow_values(revoked.capability_id, fields)
    payload = {"capability_id": revoked.capability_id, "fields": fields}
    resumed = service.advance(
        owner,
        revoked.task_id,
        WorkflowEvent(event_id=uuid4(), expected_revision=revoked.revision, kind="allow_save"),
        ephemeral=payload,
    )
    assert resumed.save_mode == "allowed" and resumed.state == "ready_for_review"
    prepared = event(service, owner, resumed, "prepare_confirmation")
    assert prepared.result_ref.kind == ("regimen" if save_plan else "enrollment_task")
    assert h.snapshot()["sources"] == before["sources"] and h.snapshot()["regimens"] == before["regimens"]


def test_unsaved_source_photo_preview_does_not_export_enrollment_fields_or_persist_contents():
    from .test_workflow_originals import original_png
    from .test_workflow_photo_enrollment import label
    from .workflow_support import WorkflowHarness

    with WorkflowHarness(source_results=[label()]) as h:
        service = source_engine(h)
        owner = h.owner_ids["A"]
        view = service.start(owner, "medication.source.add", uuid4(), None, {}, "ephemeral")
        attachments = h.container.assistant_attachments
        before = h.snapshot()
        result = attachments.preview_ephemeral(
            attachments.context(owner, view.task_id, view.revision), uuid4(), original_png(), "image/png", True
        )
        assert result.outcome == "success" and result.preview is not None and result.fields is None
        after = h.snapshot()
        for key in ("sources", "source_fields", "medications", "regimens", "originals", "history"):
            assert after[key] == before[key]
