"""Owner-scoped recovery metadata and request-only photo previews for the shared UI."""

import json
from uuid import uuid4

from app.application.source_preview import SourcePreviewService
from app.domain.errors import ProviderUnavailableError

from .conftest import CountingIdGenerator
from .test_workflow_originals import original_png
from .workflow_support import WorkflowHarness


def test_saved_views_include_the_owned_workspace_and_conversation_for_recovery(workflow):
    h = workflow
    first = h.start("medication.enroll", {"method": "manual"})
    assert first["workspace_id"] == h.workspace_id and first["conversation_id"] is None
    saved = h._request("GET", "/api/agent/workflows/tasks")
    assert saved[0]["workspace_id"] == h.workspace_id


def test_lost_ephemeral_control_listing_and_pure_page_revalidation_never_save_fields(workflow):
    h = workflow
    first = h.start("medication.enroll", {"method": "manual", "medication_name": "DEMO-page-secret"}, save=False)
    assert h._request("GET", "/api/agent/workflows/tasks") == []
    controls = h._request("GET", "/api/agent/workflows/tasks?include_ephemeral=true")
    assert len(controls) == 1 and controls[0]["visible_fields"] == {}
    assert controls[0]["prompt_key"] == "assistant.workflow.ephemeral_lost"
    preview = h._request(
        "POST",
        f"/api/agent/workflows/tasks/{first['task_id']}/preview",
        json={
            "ephemeral": {
                "capability_id": "medication.enroll",
                "fields": {"method": "manual", "medication_name": "DEMO-page-secret"},
            },
        },
    )
    assert preview["state"] == "collecting" and preview["visible_fields"]["medication_name"] == "DEMO-page-secret"
    assert "DEMO-page-secret" not in json.dumps(h.snapshot())
    forged = h.client.post(
        f"/api/agent/workflows/tasks/{first['task_id']}/preview",
        params={"client_id": "DEMO-workflow-A"},
        json={"ephemeral": {"capability_id": "medication.enroll", "fields": {"confirmed": True}}},
    )
    assert forged.status_code == 422


def test_no_save_photo_preview_uses_request_memory_and_never_creates_an_original():
    received = []

    class UnavailableProvider:
        def extract_medication_source(self, **kwargs):
            received.append(kwargs["image_bytes"])
            raise ProviderUnavailableError("DEMO source unavailable")

    with WorkflowHarness(
        source_preview=SourcePreviewService(provider=UnavailableProvider(), ids=CountingIdGenerator())
    ) as h:
        first = h.start("medication.enroll", {"method": "photo"}, save=False)
        event_id = uuid4()
        path = f"/api/agent/workflows/tasks/{first['task_id']}/preview-image/{event_id}"
        params = {
            "client_id": "DEMO-workflow-A",
            "expected_revision": first["revision"],
            "source_kind": "pharmacy_label",
        }
        response = h.client.post(
            path,
            params=params,
            content=original_png(),
            headers={"Content-Type": "image/png", "X-Stage2-Consent": "true"},
        )
        assert response.status_code == 200
        assert response.json()["storage_state"] == "ephemeral" and response.json()["outcome"] == "failed"
        assert received and received[0] != original_png()
        assert h.snapshot()["originals"] == [] and h.snapshot()["tasks"] == [] and h.snapshot()["history"] == []
        assert "DEMO_metadata" not in json.dumps(h.snapshot())
        duplicate = h.client.post(
            path,
            params={**params, "expected_revision": response.json()["revision"]},
            content=original_png(),
            headers={"Content-Type": "image/png", "X-Stage2-Consent": "true"},
        )
        assert duplicate.status_code == 409 and len(received) == 1


def test_saved_original_list_is_available_for_refresh_and_private_to_its_owner(workflow):
    h = workflow
    first = h.start("medication.enroll", {"method": "photo"})
    uploaded = h.upload(first["task_id"], original_png())
    path = f"/api/agent/workflows/tasks/{first['task_id']}/attachments"
    listed = h._request("GET", path)
    assert len(listed) == 1 and listed[0]["id"] == uploaded["attachment"]["id"]
    assert "object_ref" not in listed[0]
    assert h.client.get(path, params={"client_id": "DEMO-workflow-B"}).status_code == 404


def test_saved_original_recognition_is_explicit_and_duplicate_never_repeats_provider():
    received = []

    class UnavailableProvider:
        def extract_medication_source(self, **kwargs):
            received.append(kwargs["image_bytes"])
            raise ProviderUnavailableError("DEMO source unavailable")

    with WorkflowHarness(
        source_preview=SourcePreviewService(provider=UnavailableProvider(), ids=CountingIdGenerator())
    ) as h:
        first = h.start("medication.enroll", {"method": "photo"})
        uploaded = h._request(
            "PUT",
            f"/api/agent/workflows/tasks/{first['task_id']}/attachments/{uuid4()}?expected_revision={first['revision']}",
            content=original_png(),
            headers={"Content-Type": "image/png"},
        )
        path = f"/api/agent/workflows/tasks/{first['task_id']}/attachments/{uploaded['attachment']['id']}/preview"
        payload = {"expected_revision": uploaded["workflow"]["revision"], "event_id": str(uuid4())}
        denied = h.client.post(path, params={"client_id": "DEMO-workflow-A"}, json=payload)
        assert denied.status_code == 422 and not received
        result = h.client.post(
            path, params={"client_id": "DEMO-workflow-A"}, json=payload, headers={"X-Stage2-Consent": "true"}
        )
        assert result.status_code == 200
        assert result.json()["attachment"]["extraction_status"] == "failed"
        assert result.json()["attachment"]["reason"] == "provider_unavailable"
        assert result.json()["workflow"]["storage_state"] == "saved"
        duplicate = h.client.post(
            path, params={"client_id": "DEMO-workflow-A"}, json=payload, headers={"X-Stage2-Consent": "true"}
        )
        assert duplicate.status_code == 409 and len(received) == 1
        assert h.read_original(uploaded["attachment"]["id"]) == original_png()
        assert (
            h.client.post(
                path, params={"client_id": "DEMO-workflow-B"}, json=payload, headers={"X-Stage2-Consent": "true"}
            ).status_code
            == 404
        )
