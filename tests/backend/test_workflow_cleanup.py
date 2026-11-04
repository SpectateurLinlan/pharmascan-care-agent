"""Cancellation and external-object races use actual shared task/control repositories."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID, uuid4

import pytest
from app.domain.errors import NotFoundError, ProviderUnavailableError
from app.infrastructure.memory_workflows import MemoryOriginalRepository, MemoryWorkflowObjects, MemoryWorkflowState

from .test_workflow_originals import original_png
from .workflow_support import WorkflowHarness


def test_cancel_save_removes_the_exclusive_object_and_all_workflow_content():
    objects = MemoryWorkflowObjects(state=MemoryWorkflowState())
    with WorkflowHarness(original_storage=objects) as h:
        first = h.start("medication.enroll", {"method": "photo"})
        h.upload(first["task_id"], original_png())
        row = h.container.assistant_attachments.originals(h.owner_ids["A"])[0]
        assert objects.read(row.owner, row.object_ref) == original_png()
        cancelled = h.event(first["task_id"], "cancel_save")
        assert cancelled["save_mode"] == "ephemeral"
        assert h.snapshot()["originals"] == [] and h.snapshot()["tasks"] == []
        with pytest.raises(NotFoundError):
            objects.read(row.owner, row.object_ref)


def test_storage_delete_failure_stays_pending_and_retries_only_on_request():
    class UnavailableDelete(MemoryWorkflowObjects):
        available = False

        def delete(self, owner, key):
            if not self.available:
                raise ProviderUnavailableError("DEMO storage delete unavailable")
            return super().delete(owner, key)

    objects = UnavailableDelete(state=MemoryWorkflowState())
    with WorkflowHarness(original_storage=objects) as h:
        first = h.start("medication.enroll", {"method": "photo"})
        h.upload(first["task_id"], original_png())
        row = h.container.assistant_attachments.originals(h.owner_ids["A"])[0]
        cancelled = h.event(first["task_id"], "cancel_save")
        assert cancelled["storage_state"] == "cleanup_pending"
        assert h.view(first["task_id"])["storage_state"] == "cleanup_pending"
        assert objects.read(row.owner, row.object_ref) == original_png()
        objects.available = True
        receipts = h.container.assistant_cleanup.retry_cleanup(row.owner, row.task_id)
        assert receipts and all(receipt.state == "deleted" for receipt in receipts)
        with pytest.raises(NotFoundError):
            objects.read(row.owner, row.object_ref)


def test_late_upload_after_revocation_cannot_reattach_and_is_cleaned():
    started, finish = Event(), Event()

    class DelayedPut(MemoryWorkflowObjects):
        def put_original(self, *args, **kwargs):
            started.set()
            assert finish.wait(timeout=10), "DEMO test upload release missing"
            return super().put_original(*args, **kwargs)

    objects = DelayedPut(state=MemoryWorkflowState())
    with WorkflowHarness(original_storage=objects) as h:
        first = h.start("medication.enroll", {"method": "photo"})
        upload = uuid4()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(
                h.client.put,
                f"/api/agent/workflows/tasks/{first['task_id']}/attachments/{upload}",
                params={"client_id": "DEMO-workflow-A", "expected_revision": first["revision"]},
                content=original_png(),
                headers={"Content-Type": "image/png", "X-Stage2-Consent": "true"},
            )
            assert started.wait(timeout=5), "DEMO upload did not reach the external object boundary"
            row = h.container.assistant_attachments.originals(h.owner_ids["A"])[0]
            try:
                cancelled = h.event(first["task_id"], "cancel_save")
                assert cancelled["storage_state"] == "cleanup_pending"
            finally:
                finish.set()
            assert pending.result(timeout=10).status_code in {404, 409}
        assert not h.snapshot()["tasks"] and not h.snapshot()["originals"]
        with pytest.raises(NotFoundError):
            objects.read(row.owner, row.object_ref)


def test_original_referenced_by_an_existing_reviewed_source_is_protected():
    objects = MemoryWorkflowObjects(state=MemoryWorkflowState())
    with WorkflowHarness(original_storage=objects) as h:
        owner = h.owner_ids["A"]
        medication = h.seed_reviewed_medication()
        source = h.container.enrollment.get_regimen(owner, UUID(medication["regimen_id"])).source_id
        first = h.start("medication.enroll", {"method": "photo"})
        result = h.upload(first["task_id"], original_png())
        row = h.container.assistant_attachments.originals(owner)[0]
        context = h.container.assistant_attachments.context(owner, row.task_id, result["workflow"]["revision"])
        h.container.assistant_attachments.protect_for_source(context, row.id, source)
        cancelled = h.event(first["task_id"], "cancel_save")
        assert cancelled["prompt_key"] == "assistant.workflow.source_retained"
        assert objects.read(owner, row.object_ref) == original_png()
        assert h.snapshot()["originals"] == [] and h.container.enrollment.get_source(owner, source) is not None
        receipts = h.container.assistant_cleanup.retry_cleanup(owner, row.task_id)
        assert receipts[0].state == "protected" and receipts[0].reason == "formal_source"


def test_metadata_failure_after_object_write_has_an_owned_receipt_and_explicit_recovery(monkeypatch):
    objects = MemoryWorkflowObjects(state=MemoryWorkflowState())
    publish = MemoryOriginalRepository.publish
    failures = [True]

    def unavailable_once(self, *args, **kwargs):
        if failures:
            failures.pop()
            raise ProviderUnavailableError("DEMO metadata commit unavailable")
        return publish(self, *args, **kwargs)

    monkeypatch.setattr(MemoryOriginalRepository, "publish", unavailable_once)
    with WorkflowHarness(original_storage=objects) as h:
        first = h.start("medication.enroll", {"method": "photo"})
        response = h.client.put(
            f"/api/agent/workflows/tasks/{first['task_id']}/attachments/{uuid4()}",
            params={"client_id": "DEMO-workflow-A", "expected_revision": first["revision"]},
            content=original_png(),
            headers={"Content-Type": "image/png", "X-Stage2-Consent": "true"},
        )
        assert response.status_code == 503
        row = h.container.assistant_attachments.originals(h.owner_ids["A"])[0]
        assert row.state == "reserved" and objects.read(row.owner, row.object_ref) == original_png()
        interrupted = h.view(first["task_id"])
        assert interrupted["state"] == "outcome_unknown" and interrupted["storage_state"] == "saved"
        h.clock.advance(seconds=46)
        recovered = h._request(
            "POST",
            f"/api/agent/workflows/tasks/{first['task_id']}/attachments/{row.id}/recover",
            json={"expected_revision": first["revision"], "event_id": str(uuid4())},
        )
        assert recovered["attachment"]["id"] == str(row.id) and recovered["attachment"]["state"] == "saved"
        assert h.read_original(str(row.id)) == original_png()
        assert len(h.snapshot()["originals"]) == 1 and not h.snapshot()["medications"]


@pytest.mark.parametrize("reference_kind", ["other_task", "pending_action", "succeeded_action"])
def test_an_original_referenced_by_another_owned_task_is_not_physically_deleted(workflow, reference_kind):
    import hashlib

    from app.application.workflow_cleanup import ExistingSourceProtection, WorkflowCleanupService
    from app.contracts.assistant_workflows import BusinessRef, WorkflowContext, WorkflowTask
    from app.contracts.workflow_attachments import OriginalAttachment
    from app.infrastructure.memory_workflows import (
        MemoryActionRepository,
        MemoryCleanupRepository,
        MemoryControlRepository,
        MemoryWorkflowRepository,
    )

    h = workflow
    owner, task_id, attachment_id, upload_id = h.owner_ids["A"], uuid4(), uuid4(), uuid4()
    state = MemoryWorkflowState()
    tasks = MemoryWorkflowRepository(h.clock, state=state)
    controls = MemoryControlRepository(h.clock, state=state)
    originals = MemoryOriginalRepository(state=state, tasks=tasks, controls=controls)
    receipts = MemoryCleanupRepository(state=state)
    objects = MemoryWorkflowObjects(state=state)
    tasks.create(
        WorkflowTask(
            id=task_id,
            owner=owner,
            workspace_id=uuid4(),
            capability_id="medication.enroll",
            storage_state="saved",
            updated_at=h.clock.now(),
        )
    )
    context = WorkflowContext(owner=owner, task_id=task_id, capability_id="medication.enroll", revision=1)
    row = originals.reserve(
        context,
        OriginalAttachment(
            id=attachment_id,
            owner=owner,
            task_id=task_id,
            upload_id=upload_id,
            binding_revision=1,
            object_ref=f"{owner}/workflow-originals/{task_id}/{attachment_id}",
            original_checksum=hashlib.sha256(original_png()).hexdigest(),
            content_type="image/png",
            source_kind="pharmacy_label",
            byte_size=len(original_png()),
        ),
    )
    objects.put_original(owner, task_id, upload_id, original_png(), "image/png", object_ref=row.object_ref)
    originals.note_written(owner, task_id, attachment_id)
    originals.publish(context, row)
    other = tasks.create(
        WorkflowTask(
            id=uuid4(),
            owner=owner,
            workspace_id=uuid4(),
            capability_id="medication.enroll",
            business_refs=(BusinessRef(kind="file", id=attachment_id),) if reference_kind == "other_task" else (),
            storage_state="saved",
            updated_at=h.clock.now(),
        )
    )
    actions = MemoryActionRepository(h.clock, state=state)
    if reference_kind != "other_task":
        operation_context = context.model_copy(update={"revision": tasks.get(owner, task_id).revision})
        receipt = actions.reserve(operation_context, uuid4())
        if reference_kind == "succeeded_action":
            medication = h.seed_reviewed_medication()
            source = h.container.enrollment.get_regimen(owner, UUID(medication["regimen_id"])).source_id
            actions.complete(
                operation_context,
                receipt.model_copy(
                    update={
                        "state": "succeeded",
                        "business_ref": BusinessRef(kind="source", id=source),
                    }
                ),
            )
    cleanup = WorkflowCleanupService(
        controls=controls,
        repository=receipts,
        originals=originals,
        storage=objects,
        ids=h.container.ids,
        protection=ExistingSourceProtection(
            receipts=receipts, enrollment=h.container.enrollment, tasks=tasks, actions=actions
        ),
    )
    cleanup.cancel_save(owner, task_id, controls.get(owner, task_id).revision)
    assert cleanup.retry_cleanup(owner, task_id)[0].state == "protected"
    assert objects.read(owner, row.object_ref) == original_png()
    if reference_kind == "other_task":
        assert tasks.get(owner, other.id).business_refs[0].id == attachment_id


def test_storage_ack_loss_is_observed_before_cleanup_without_a_second_put():
    class LostAcknowledgement(MemoryWorkflowObjects):
        def put_original(self, *args, **kwargs):
            super().put_original(*args, **kwargs)
            raise ProviderUnavailableError("DEMO lost storage acknowledgement")

    objects = LostAcknowledgement(state=MemoryWorkflowState())
    with WorkflowHarness(original_storage=objects) as h:
        first = h.start("medication.enroll", {"method": "photo"})
        response = h.client.put(
            f"/api/agent/workflows/tasks/{first['task_id']}/attachments/{uuid4()}",
            params={"client_id": "DEMO-workflow-A", "expected_revision": first["revision"]},
            content=original_png(),
            headers={"Content-Type": "image/png", "X-Stage2-Consent": "true"},
        )
        assert response.status_code == 503
        row = h.container.assistant_attachments.originals(h.owner_ids["A"])[0]
        assert objects.read(row.owner, row.object_ref) == original_png()
        h.event(first["task_id"], "cancel_save")
        h.container.assistant_cleanup.retry_cleanup(row.owner, row.task_id)
        with pytest.raises(NotFoundError):
            objects.read(row.owner, row.object_ref)


def test_allowing_a_new_save_does_not_hide_pending_old_cleanup():
    class UnavailableDelete(MemoryWorkflowObjects):
        def delete(self, owner, key):
            raise ProviderUnavailableError("DEMO storage delete unavailable")

    with WorkflowHarness(original_storage=UnavailableDelete(state=MemoryWorkflowState())) as h:
        first = h.start("medication.enroll", {"method": "photo"})
        h.upload(first["task_id"], original_png())
        cancelled = h.event(first["task_id"], "cancel_save")
        saved = h._request(
            "POST",
            f"/api/agent/workflows/tasks/{first['task_id']}/events",
            json={
                "event_id": str(uuid4()),
                "expected_revision": cancelled["revision"],
                "kind": "allow_save",
                "ephemeral": {"capability_id": "medication.enroll", "fields": {"method": "manual"}},
            },
        )
        assert saved["storage_state"] == "saved" and saved["cleanup_pending"]
        assert h.view(first["task_id"])["cleanup_pending"]


def test_cleanup_retry_http_is_owner_bound_and_does_not_expose_object_keys(workflow):
    h = workflow
    first = h.start("medication.enroll", {"method": "photo"})
    h.upload(first["task_id"], original_png())
    h.event(first["task_id"], "cancel_save")
    path = f"/api/agent/workflows/tasks/{first['task_id']}/cleanup"
    response = h.client.post(path, params={"client_id": "DEMO-workflow-A"}, json={})
    assert response.status_code == 200 and response.json()[0]["state"] == "deleted"
    assert set(response.json()[0]) == {"attachment_id", "state", "reason", "writer_pending"}
    assert h.client.post(path, params={"client_id": "DEMO-workflow-B"}, json={}).status_code == 404
