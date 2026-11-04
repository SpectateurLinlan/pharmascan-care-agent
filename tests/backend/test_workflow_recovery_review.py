"""Review regressions: interrupted extraction and original writes stay recoverable."""

from uuid import UUID, uuid4

import pytest
from app.application.source_preview import SourcePreviewService
from app.domain.errors import DuplicateEventError, ProviderUnavailableError
from app.infrastructure.memory_workflows import MemoryWorkflowObjects, MemoryWorkflowState

from .conftest import CountingIdGenerator
from .test_workflow_originals import original_png
from .workflow_support import WorkflowHarness


def upload(h, first, upload_id):
    return h.client.put(
        f"/api/agent/workflows/tasks/{first['task_id']}/attachments/{upload_id}",
        params={"client_id": "DEMO-workflow-A", "expected_revision": h.view(first["task_id"])["revision"]},
        content=original_png(),
        headers={"Content-Type": "image/png", "X-Stage2-Consent": "true"},
    )


def test_saved_original_recovery_releases_expired_extraction_without_repeating_provider():
    received = []

    class SlowProvider:
        def extract_medication_source(self, **kwargs):
            received.append(kwargs["image_bytes"])
            if len(received) == 1:
                h.clock.advance(seconds=46)
            raise ProviderUnavailableError("DEMO recognition unavailable")

    with WorkflowHarness(source_preview=SourcePreviewService(provider=SlowProvider(), ids=CountingIdGenerator())) as h:
        first = h.start("medication.enroll", {"method": "photo"})
        assert upload(h, first, uuid4()).status_code == 409
        before = h.view(first["task_id"])
        row = h.container.assistant_attachments.originals(h.owner_ids["A"])[0]
        recovered = h._request(
            "POST",
            f"/api/agent/workflows/tasks/{row.task_id}/attachments/{row.id}/recover",
            json={"expected_revision": before["revision"], "event_id": str(uuid4())},
        )
        assert recovered["workflow"]["state"] != "outcome_unknown"
        assert recovered["attachment"]["extraction_status"] == "interrupted" and len(received) == 1
        retry = h._request(
            "POST",
            f"/api/agent/workflows/tasks/{row.task_id}/attachments/{row.id}/preview",
            json={"expected_revision": recovered["workflow"]["revision"], "event_id": str(uuid4())},
            headers={"X-Stage2-Consent": "true"},
        )
        assert retry["attachment"]["extraction_status"] == "failed" and len(received) == 2
        assert h.read_original(str(row.id)) == original_png()


def test_explicit_file_retry_observes_absence_and_reuses_the_same_immutable_original_intent():
    class FailedOnce(MemoryWorkflowObjects):
        attempts = 0
        keys = []

        def put_original(self, *args, **kwargs):
            self.attempts += 1
            self.keys.append(kwargs["object_ref"])
            if self.attempts == 1:
                raise ProviderUnavailableError("DEMO response unknown before put")
            return super().put_original(*args, **kwargs)

    objects = FailedOnce(state=MemoryWorkflowState())
    with WorkflowHarness(original_storage=objects) as h:
        first = h.start("medication.enroll", {"method": "photo"})
        upload_id = uuid4()
        assert upload(h, first, upload_id).status_code == 503
        row = h.container.assistant_attachments.originals(h.owner_ids["A"])[0]
        h.clock.advance(seconds=46)
        retried = upload(h, first, upload_id)
        assert retried.status_code == 200
        assert retried.json()["attachment"]["id"] == str(row.id)
        assert objects.attempts == 2 and objects.keys[0] == objects.keys[1]
        assert h.read_original(str(row.id)) == original_png() and len(h.snapshot()["originals"]) == 1


def test_explicit_file_retry_observes_an_existing_object_without_another_put():
    class LostAcknowledgement(MemoryWorkflowObjects):
        attempts = 0

        def put_original(self, *args, **kwargs):
            self.attempts += 1
            super().put_original(*args, **kwargs)
            raise ProviderUnavailableError("DEMO lost acknowledgement")

    objects = LostAcknowledgement(state=MemoryWorkflowState())
    with WorkflowHarness(original_storage=objects) as h:
        first = h.start("medication.enroll", {"method": "photo"})
        upload_id = uuid4()
        assert upload(h, first, upload_id).status_code == 503
        h.clock.advance(seconds=46)
        retried = upload(h, first, upload_id)
        assert retried.status_code == 200 and objects.attempts == 1
        assert retried.json()["attachment"]["extraction_status"] == "consent_required"


def test_interrupted_no_save_preview_recovers_page_fields_without_storing_or_repeating_the_photo():
    received = []

    class SlowProvider:
        def extract_medication_source(self, **kwargs):
            received.append(kwargs["image_bytes"])
            h.clock.advance(seconds=46)
            raise ProviderUnavailableError("DEMO delayed unavailable recognition")

    with WorkflowHarness(source_preview=SourcePreviewService(provider=SlowProvider(), ids=CountingIdGenerator())) as h:
        first = h.start("medication.enroll", {"method": "photo"}, save=False)
        failed = h.client.post(
            f"/api/agent/workflows/tasks/{first['task_id']}/preview-image/{uuid4()}",
            params={"client_id": "DEMO-workflow-A", "expected_revision": first["revision"]},
            content=original_png(),
            headers={"Content-Type": "image/png", "X-Stage2-Consent": "true"},
        )
        assert failed.status_code == 409
        recovered = h._request(
            "POST",
            f"/api/agent/workflows/tasks/{first['task_id']}/events",
            json={
                "event_id": str(uuid4()),
                "expected_revision": first["revision"],
                "kind": "retry",
                "values": {},
                "ephemeral": {"capability_id": "medication.enroll", "fields": {"method": "photo"}},
            },
        )
        assert recovered["visible_fields"] == {"method": "photo"} and recovered["state"] == "collecting"
        assert len(received) == 1 and h.snapshot()["tasks"] == [] and h.snapshot()["originals"] == []


def test_refreshed_page_can_explicitly_retry_the_same_original_by_attachment_id():
    class FailedOnce(MemoryWorkflowObjects):
        attempts = 0

        def put_original(self, *args, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise ProviderUnavailableError("DEMO dropped upload")
            return super().put_original(*args, **kwargs)

    with WorkflowHarness(original_storage=FailedOnce(state=MemoryWorkflowState())) as h:
        first = h.start("medication.enroll", {"method": "photo"})
        assert upload(h, first, uuid4()).status_code == 503
        row = h.container.assistant_attachments.originals(h.owner_ids["A"])[0]
        h.clock.advance(seconds=46)
        retry = h.client.put(
            f"/api/agent/workflows/tasks/{row.task_id}/attachments/{row.id}/retry",
            params={"client_id": "DEMO-workflow-A", "expected_revision": first["revision"]},
            content=original_png(),
            headers={"Content-Type": "image/png"},
        )
        assert retry.status_code == 200 and retry.json()["attachment"]["id"] == str(row.id)
        assert retry.json()["attachment"]["extraction_status"] == "consent_required"
        assert h.read_original(str(row.id)) == original_png()


def test_recovery_cannot_clear_an_interrupted_request_belonging_to_another_original():
    class FailSecond(MemoryWorkflowObjects):
        attempts = 0

        def put_original(self, *args, **kwargs):
            self.attempts += 1
            if self.attempts == 2:
                raise ProviderUnavailableError("DEMO second original write unknown")
            return super().put_original(*args, **kwargs)

    with WorkflowHarness(original_storage=FailSecond(state=MemoryWorkflowState())) as h:
        first = h.start("medication.enroll", {"method": "photo"})
        saved = h.upload(first["task_id"], original_png())
        assert upload(h, first, uuid4()).status_code == 503
        h.clock.advance(seconds=46)
        before = h.view(first["task_id"])
        wrong = h.client.post(
            f"/api/agent/workflows/tasks/{first['task_id']}/attachments/{saved['attachment']['id']}/recover",
            params={"client_id": "DEMO-workflow-A"},
            json={"expected_revision": before["revision"], "event_id": str(uuid4())},
        )
        assert wrong.status_code == 409
        assert h.view(first["task_id"])["revision"] == before["revision"]


def test_original_protection_cannot_replace_a_previously_reviewed_source(workflow):
    h = workflow
    first_source = h.seed_reviewed_medication()["source_id"]
    second_source = h.seed_reviewed_medication()["source_id"]
    first = h.start("medication.enroll", {"method": "photo"})
    uploaded = h.upload(first["task_id"], original_png())
    service = h.container.assistant_attachments
    owner = h.owner_ids["A"]
    attachment = UUID(uploaded["attachment"]["id"])
    service.protect_for_source(
        service.context(owner, UUID(first["task_id"]), uploaded["workflow"]["revision"]), attachment, UUID(first_source)
    )
    with pytest.raises(DuplicateEventError):
        service.protect_for_source(
            service.context(owner, UUID(first["task_id"]), h.view(first["task_id"])["revision"]),
            attachment,
            UUID(second_source),
        )
    assert service.originals(owner)[0].source_ref.id == UUID(first_source)


def test_cancellation_after_retry_keeps_old_writer_pending_until_its_late_acknowledgement():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from app.domain.errors import NotFoundError

    started, release = Event(), Event()

    class DelayedFirst(MemoryWorkflowObjects):
        attempts = 0

        def put_original(self, *args, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                started.set()
                assert release.wait(timeout=10)
            return super().put_original(*args, **kwargs)

    objects = DelayedFirst(state=MemoryWorkflowState())
    with WorkflowHarness(original_storage=objects) as h:
        first = h.start("medication.enroll", {"method": "photo"})
        upload_id = uuid4()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(upload, h, first, upload_id)
            assert started.wait(timeout=5)
            try:
                h.clock.advance(seconds=46)
                retried = upload(h, first, upload_id)
                assert retried.status_code == 200
                original_id = retried.json()["attachment"]["id"]
                cancelled = h.event(first["task_id"], "cancel_save")
                assert cancelled["cleanup_pending"] is True
                receipt = h.container.assistant_cleanup.retry_cleanup(h.owner_ids["A"], UUID(first["task_id"]))[0]
                assert receipt.writer_pending is True and receipt.state != "deleted"
            finally:
                release.set()
            assert pending.result(timeout=10).status_code in {404, 409}
        final = h.container.assistant_cleanup.retry_cleanup(h.owner_ids["A"], UUID(first["task_id"]))[0]
        assert final.state == "deleted" and final.writer_pending is False
        with pytest.raises(NotFoundError):
            objects.read(h.owner_ids["A"], f"{h.owner_ids['A']}/workflow-originals/{first['task_id']}/{original_id}")
