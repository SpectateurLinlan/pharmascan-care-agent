"""Actual saved raw originals feed source publication without recognition replay."""

from uuid import uuid4

import pytest
from app.contracts.assistant_workflows import BusinessRef, WorkflowTask
from app.domain.errors import ProviderUnavailableError, StaleVersionError, ValidationError

from .test_workflow_originals import original_png
from .test_workflow_photo_enrollment import label
from .workflow_support import WorkflowHarness


def original(h, target=None, version=1):
    # Source capabilities stay unavailable until their real adapter/UI is done.
    # Arrange a genuine repository/control task for this public-port integration.
    tasks = h.container.assistant_workflows._repository
    target = target or uuid4()
    task = tasks.create(
        WorkflowTask(
            id=uuid4(),
            owner=h.owner_ids["A"],
            workspace_id=uuid4(),
            capability_id="medication.source.add",
            state="awaiting_confirmation",
            save_mode="allowed",
            storage_state="saved",
            updated_at=h.clock.now(),
            business_refs=(BusinessRef(kind="enrollment_task", id=target, version=version),),
        )
    )
    attachments = h.container.assistant_attachments
    context = attachments.context(task.owner, task.id, task.revision)
    uploaded = attachments.accept(context, uuid4(), original_png(), "image/png", True)
    current = tasks.get(task.owner, task.id)
    return attachments.context(task.owner, task.id, current.revision), target, uploaded


def operations(h):
    from app.application.source_operations import SourceEnrollmentOperationService

    workflows = h.container.assistant_workflows
    return SourceEnrollmentOperationService(
        evidence=h.container.evidence_enrollment,
        originals=h.container.assistant_attachments,
        tasks=workflows._repository,
        controls=workflows._controls,
    )


def test_verified_original_is_prepared_then_saved_once_with_no_second_provider_call():
    with WorkflowHarness(source_results=[label()]) as h:
        context, target, uploaded = original(h)
        service = operations(h)
        prepared = service.prepare(context, target, uploaded.id)
        assert not h.snapshot()["sources"] and len(h.source_calls) == 1
        key = uuid4()
        saved = service.publish(context, prepared, key)
        replay = service.publish(context, prepared, key)
        assert saved == replay and saved.id == target and len(h.snapshot()["medications"]) == 1
        assert h.container.assistant_attachments.read(context.owner, context.task_id, uploaded.id)[0] == original_png()
        assert len(h.source_calls) == 1


def test_extraction_failure_keeps_exact_raw_original_without_any_clinical_source():
    with WorkflowHarness(source_results=[ProviderUnavailableError("DEMO source unavailable")]) as h:
        context, target, uploaded = original(h)
        assert uploaded.extraction_status == "failed"
        with pytest.raises(ValidationError):
            operations(h).prepare(context, target, uploaded.id)
        assert h.container.assistant_attachments.read(context.owner, context.task_id, uploaded.id)[0] == original_png()
        assert not h.snapshot()["sources"] and not h.snapshot()["medications"]


def test_no_save_revocation_after_preparation_prevents_source_publication():
    with WorkflowHarness(source_results=[label()]) as h:
        context, target, uploaded = original(h)
        service = operations(h)
        prepared = service.prepare(context, target, uploaded.id)
        h.container.assistant_cleanup.cancel_save(context.owner, context.task_id, context.revision)
        with pytest.raises((StaleVersionError, ValidationError)):
            service.publish(context, prepared, uuid4())
        assert not h.snapshot()["sources"] and not h.snapshot()["medications"]


def test_cancel_save_does_not_delete_an_original_already_referenced_by_a_clinical_source():
    with WorkflowHarness(source_results=[label()]) as h:
        context, target, uploaded = original(h)
        service = operations(h)
        service.publish(context, service.prepare(context, target, uploaded.id), uuid4())
        result = h.container.assistant_cleanup.cancel_save(context.owner, context.task_id, context.revision)
        assert result.protected_originals is True
        path = f"{context.owner}/workflow-originals/{context.task_id}/{uploaded.id}"
        assert h.container.assistant_attachments._storage.read(context.owner, path) == original_png()


def test_an_explicit_duplicate_source_save_retains_the_new_original_reference_without_duplicate_clinical_rows():
    with WorkflowHarness(source_results=[label(), label()]) as h:
        first, target, uploaded = original(h)
        service = operations(h)
        saved = service.publish(first, service.prepare(first, target, uploaded.id), uuid4())
        second, _, duplicate = original(h, target, saved.version)
        replay = service.publish(second, service.prepare(second, target, duplicate.id), uuid4())
        assert replay.id == saved.id and len(h.snapshot()["medications"]) == 1
        result = h.container.assistant_cleanup.cancel_save(second.owner, second.task_id, second.revision)
        assert result.protected_originals is True
        path = f"{second.owner}/workflow-originals/{second.task_id}/{duplicate.id}"
        assert h.container.assistant_attachments._storage.read(second.owner, path) == original_png()


def test_lost_save_response_can_reenter_the_patient_operation_without_repreparing_or_duplicating_sources():
    with WorkflowHarness(source_results=[label()]) as h:
        context, target, uploaded = original(h)
        service = operations(h)
        key = uuid4()
        first = service.save(context, target, uploaded.id, key)
        second = service.save(context, target, uploaded.id, key)
        assert second == first and len(h.snapshot()["sources"]) == len(h.snapshot()["medications"]) == 1
        assert len(h.source_calls) == 1


def test_another_workflow_can_retain_a_duplicate_original_but_cannot_append_new_source_evidence():
    from io import BytesIO

    from PIL import Image

    with WorkflowHarness(source_results=[label(), label(), label()]) as h:
        first, target, uploaded = original(h)
        service = operations(h)
        saved = service.save(first, target, uploaded.id, uuid4())
        second, _, _duplicate = original(h, target, saved.version)
        body = BytesIO()
        Image.new("RGB", (80, 80), "yellow").save(body, format="PNG")
        attachments = h.container.assistant_attachments
        added = attachments.accept(second, uuid4(), body.getvalue(), "image/png", True)
        task = h.container.assistant_workflows._repository.get(second.owner, second.task_id)
        current = attachments.context(second.owner, second.task_id, task.revision)
        before = h.snapshot()
        with pytest.raises(StaleVersionError):
            service.save(current, target, added.id, uuid4())
        assert h.snapshot()["sources"] == before["sources"]
        assert attachments.read(second.owner, second.task_id, added.id)[0] == body.getvalue()
