"""DEMO_ONLY original bytes are retained independently of successful extraction."""

import hashlib
from io import BytesIO
from uuid import uuid4

import pytest
from app.application.source_preview import SourcePreviewService
from app.domain.errors import ProviderUnavailableError
from app.infrastructure.evidence_images import patient_source_image
from app.infrastructure.memory_workflows import MemoryWorkflowObjects, MemoryWorkflowState
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from .conftest import CountingIdGenerator
from .workflow_support import WorkflowHarness


def original_png():
    image = Image.new("RGB", (80, 80), "white")
    image.putpixel((10, 10), (0, 120, 70))
    metadata = PngInfo()
    metadata.add_text("DEMO_metadata", "ORIGINAL metadata must survive byte for byte")
    output = BytesIO()
    image.save(output, format="PNG", pnginfo=metadata)
    return output.getvalue()


def test_extraction_unavailable_keeps_the_original_without_inventing_a_medication(workflow):
    h = workflow
    original = original_png()
    first = h.start("medication.enroll", {"method": "photo"})
    response = h.upload(first["task_id"], original)
    attachment = response["attachment"]
    assert attachment["original_checksum"] == hashlib.sha256(original).hexdigest()
    assert attachment["extraction_status"] == "failed" and attachment["reason"] == "provider_unavailable"
    assert h.read_original(attachment["id"]) == original
    assert response["workflow"]["storage_state"] == "saved"
    assert response["workflow"]["state"] == "failed_recoverable"
    assert not h.snapshot()["medications"] and len(h.snapshot()["originals"]) == 1


@pytest.mark.parametrize(
    "mime,body",
    [
        pytest.param("application/pdf", b"%PDF-DEMO", id="unsupported_pdf"),
        pytest.param("image/png", b"DEMO not an image", id="invalid_png"),
        pytest.param("image/png", b"\x89PNG\r\n\x1a\n" + b"x" * 8_000_000, id="oversized_png"),
    ],
)
def test_invalid_images_leave_the_saved_fields_but_create_no_original(workflow, mime, body):
    h = workflow
    first = h.start("medication.enroll", {"method": "photo"})
    response = h.client.put(
        f"/api/agent/workflows/tasks/{first['task_id']}/attachments/{uuid4()}",
        params={
            "client_id": "DEMO-workflow-A",
            "expected_revision": first["revision"],
            "source_kind": "pharmacy_label",
        },
        content=body,
        headers={"Content-Type": mime, "X-Stage2-Consent": "true"},
    )
    assert response.status_code == 422 and h.snapshot()["originals"] == []
    assert h.view(first["task_id"])["storage_state"] == "saved"


def test_same_upload_receipt_is_idempotent_and_rejects_changed_bytes_and_foreign_owner(workflow):
    h = workflow
    first = h.start("medication.enroll", {"method": "photo"})
    upload = uuid4()
    path = f"/api/agent/workflows/tasks/{first['task_id']}/attachments/{upload}"
    params = {"client_id": "DEMO-workflow-A", "expected_revision": first["revision"], "source_kind": "pharmacy_label"}
    headers = {"Content-Type": "image/png", "X-Stage2-Consent": "true"}
    original = original_png()
    one = h.client.put(path, params=params, headers=headers, content=original)
    assert one.status_code == 200
    two = h.client.put(path, params=params, headers=headers, content=original)
    assert two.status_code == 200 and two.json()["attachment"]["id"] == one.json()["attachment"]["id"]
    changed = h.client.put(path, params=params, headers=headers, content=original + b"DEMO different bytes")
    assert changed.status_code == 409
    foreign = h.client.get(
        f"/api/agent/workflows/tasks/{first['task_id']}/attachments/{one.json()['attachment']['id']}",
        params={"client_id": "DEMO-workflow-B"},
    )
    assert foreign.status_code == 404 and len(h.snapshot()["originals"]) == 1


def test_no_processing_consent_still_keeps_an_allowed_original_without_claiming_analysis(workflow):
    h = workflow
    first = h.start("medication.enroll", {"method": "photo"})
    response = h.client.put(
        f"/api/agent/workflows/tasks/{first['task_id']}/attachments/{uuid4()}",
        params={
            "client_id": "DEMO-workflow-A",
            "expected_revision": first["revision"],
            "source_kind": "pharmacy_label",
        },
        content=original_png(),
        headers={"Content-Type": "image/png", "X-Stage2-Consent": "false"},
    )
    assert response.status_code == 200
    assert response.json()["attachment"]["extraction_status"] == "consent_required"
    assert h.read_original(response.json()["attachment"]["id"]) == original_png()


def test_provider_receives_a_sanitized_derivative_while_original_bytes_survive_failure():
    received = []

    class UnavailableProvider:
        def extract_medication_source(self, **kwargs):
            received.append(kwargs["image_bytes"])
            raise ProviderUnavailableError("DEMO extraction unavailable")

    preview = SourcePreviewService(provider=UnavailableProvider(), ids=CountingIdGenerator())
    with WorkflowHarness(source_preview=preview) as h:
        original = original_png()
        first = h.start("medication.enroll", {"method": "photo"})
        response = h.upload(first["task_id"], original)
        assert len(received) == 1 and received[0] != original
        assert "DEMO_metadata" not in Image.open(BytesIO(received[0])).info
        assert h.read_original(response["attachment"]["id"]) == original
        assert "object_ref" not in response["attachment"] and "owner" not in response["attachment"]


def test_storage_unavailable_does_not_create_an_attachment_or_report_success(workflow, monkeypatch):
    h = workflow
    first = h.start("medication.enroll", {"method": "photo"})
    monkeypatch.setattr(h.container.assistant_attachments, "_storage", None)
    response = h.client.put(
        f"/api/agent/workflows/tasks/{first['task_id']}/attachments/{uuid4()}",
        params={"client_id": "DEMO-workflow-A", "expected_revision": first["revision"]},
        content=original_png(),
        headers={"Content-Type": "image/png", "X-Stage2-Consent": "true"},
    )
    assert response.status_code == 503 and h.snapshot()["originals"] == []
    assert h.view(first["task_id"])["missing_fields"] == ["source_image"]


def test_ephemeral_upload_never_enters_original_storage(workflow):
    h = workflow
    first = h.start("medication.enroll", {"method": "photo"}, save=False)
    response = h.client.put(
        f"/api/agent/workflows/tasks/{first['task_id']}/attachments/{uuid4()}",
        params={"client_id": "DEMO-workflow-A", "expected_revision": first["revision"]},
        content=original_png(),
        headers={"Content-Type": "image/png", "X-Stage2-Consent": "true"},
    )
    assert response.status_code == 422 and h.snapshot()["originals"] == [] and h.snapshot()["tasks"] == []


def test_recognition_checks_original_checksum_before_sending_bytes_to_provider():
    received = []

    class TamperedRead(MemoryWorkflowObjects):
        def read(self, owner, key):
            return patient_source_image(super().read(owner, key))

    class UnavailableProvider:
        def extract_medication_source(self, **kwargs):
            received.append(kwargs["image_bytes"])
            raise ProviderUnavailableError("DEMO unavailable")

    objects = TamperedRead(state=MemoryWorkflowState())
    preview = SourcePreviewService(provider=UnavailableProvider(), ids=CountingIdGenerator())
    with WorkflowHarness(original_storage=objects, source_preview=preview) as h:
        first = h.start("medication.enroll", {"method": "photo"})
        h.upload(first["task_id"], original_png())
        assert received == []
