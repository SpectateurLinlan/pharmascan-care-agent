"""DEMO_ONLY source preview over real workflow/original/native preview services."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from .test_workflow_medication_management import active_plan
from .test_workflow_photo_enrollment import label
from .test_workflow_records import clinical
from .workflow_support import WorkflowHarness

PHOTO = Path(__file__).with_name("fixtures").joinpath("DEMO_workflow_photo.png").read_bytes()


def ready(h, *, save=True, kind="pharmacy_label"):
    task = h.start("source.preview", {"source_kind": kind}, save=save)
    if not save:
        return task, None
    uploaded = h._request("PUT", f"/api/agent/workflows/tasks/{task['task_id']}/attachments/{uuid4()}", params={
        "expected_revision": task["revision"], "source_kind": "source_preview_photo",
    }, content=PHOTO, headers={"Content-Type": "image/png", "X-Stage2-Consent": "true"})
    return uploaded["workflow"], uploaded["attachment"]


def query(h, task, *, consent=True, content=PHOTO, params=None, owner="A", mime="image/png"):
    return h.client.post(f"/api/agent/workflows/tasks/{task['task_id']}/source-preview", params={
        "client_id": "DEMO-workflow-" + owner, "expected_revision": task["revision"], **(params or {}),
    }, content=content, headers={"Content-Type": mime, "X-Stage2-Consent": str(consent).lower()})


def raw(h, task, attachment):
    return h.client.get(f"/api/agent/workflows/tasks/{task['task_id']}/attachments/{attachment['id']}",
                        params={"client_id": "DEMO-workflow-A"}).content


def test_source_preview_is_explicit_and_never_creates_reviewed_records_or_saved_extraction():
    with WorkflowHarness(source_results=[label()]) as h:
        before = clinical(h)
        task, attachment = ready(h)
        h.view(task["task_id"])
        h.container.assistant_workflows.list_views(h.owner_ids["A"])
        assert not h.source_calls and attachment["extraction_status"] == "not_requested"
        result = query(h, task)
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["outcome"] == "success" and body["preview"]["review_required"] is True
        candidate = body["preview"]["candidates"][0]
        assert candidate["can_activate_regimen"] is False and candidate["review_status"] == "extracted"
        assert candidate["product"]["source_lines"]
        assert candidate["regimen_evidence"]["dose_amount"] is None
        assert len(h.source_calls) == 1 and h.source_calls[0]["image_bytes"] == PHOTO
        assert clinical(h) == before and raw(h, task, attachment) == PHOTO
        original = h.container.assistant_attachments.originals(h.owner_ids["A"])[0]
        assert original.extraction is None and original.extraction_status == "not_requested"
        assert "candidates" not in h.view(task["task_id"])["visible_fields"]


@pytest.mark.parametrize("change", ["consent", "owner", "revision", "bytes", "page_override", "mime"])
def test_source_preview_rejects_changed_or_unconfirmed_request_before_provider(change):
    with WorkflowHarness(source_results=[label()]) as h:
        task, attachment = ready(h)
        options = {"consent": {"consent": False}, "owner": {"owner": "B"},
                   "revision": {"params": {"expected_revision": 1}}, "bytes": {"content": PHOTO + b"DEMO altered"},
                   "page_override": {"params": {"ephemeral_source_kind": "package"}}, "mime": {"mime": "image/jpeg"}}
        response = query(h, task, **options[change])
        assert response.status_code in {404, 409, 422}, response.text
        assert not h.source_calls and raw(h, task, attachment) == PHOTO


def test_source_preview_failure_keeps_original_and_reports_provider_unavailability_distinctly():
    from app.domain.errors import ProviderUnavailableError

    with WorkflowHarness(source_results=[ProviderUnavailableError("DEMO no source service")]) as h:
        task, attachment = ready(h)
        response = query(h, task)
        assert response.status_code == 200 and response.json()["outcome"] == "unavailable"
        assert response.json()["preview"] is None and raw(h, task, attachment) == PHOTO


def test_no_save_preview_requires_typed_page_kind_and_retains_no_result_or_original():
    with WorkflowHarness(source_results=[label()]) as h:
        task, _ = ready(h, save=False)
        before = clinical(h)
        assert query(h, task).status_code == 422 and not h.source_calls
        result = query(h, task, params={"ephemeral_source_kind": "pharmacy_label"})
        assert result.status_code == 200 and result.json()["outcome"] == "success"
        assert clinical(h) == before and not h.container.assistant_attachments.originals(h.owner_ids["A"])


def test_saved_preview_requires_raw_original_before_any_source_call():
    with WorkflowHarness(source_results=[label()]) as h:
        task = h.start("source.preview", {"source_kind": "pharmacy_label"})
        assert query(h, task).status_code == 422 and not h.source_calls


@pytest.mark.parametrize("change", ["revoke", "clinical"])
def test_changed_context_discards_the_completed_source_preview(change, monkeypatch):
    with WorkflowHarness(source_results=[label()]) as h:
        task, _ = ready(h)
        service = h.container.assistant_source_preview.preview
        original = service.preview

        def during(**kwargs):
            result = original(**kwargs)
            h.event(task["task_id"], "cancel_save") if change == "revoke" else active_plan(h)
            return result

        monkeypatch.setattr(service, "preview", during)
        assert query(h, task).status_code in {409, 422}
        if change == "revoke":
            assert not h.container.assistant_attachments.originals(h.owner_ids["A"])


def test_readable_empty_preview_does_not_invent_a_candidate():
    with WorkflowHarness(source_results=[label().model_copy(update={"candidates": [], "label_kind": "none"})]) as h:
        task, _ = ready(h)
        result = query(h, task)
        assert result.status_code == 200 and result.json()["outcome"] == "success"
        assert result.json()["preview"]["candidates"] == []


def test_preview_only_task_cannot_call_the_legacy_ephemeral_recognition_path():
    with WorkflowHarness(source_results=[label()]) as h:
        task, _ = ready(h, save=False)
        response = h.client.post(f"/api/agent/workflows/tasks/{task['task_id']}/preview-image/{uuid4()}", params={
            "client_id": "DEMO-workflow-A", "expected_revision": task["revision"], "source_kind": "pharmacy_label",
        }, content=PHOTO, headers={"Content-Type": "image/png", "X-Stage2-Consent": "true"})
        assert response.status_code == 422 and not h.source_calls


def test_configured_demo_reuses_its_native_source_service_without_provider_settings_changes(monkeypatch):
    from app.application.source_preview import SourcePreviewService
    from app.config import Settings
    from app.transport import container as composition
    from app.transport.app_factory import create_app
    from fastapi.testclient import TestClient

    class Provider:
        def extract_medication_source(self, **kwargs):
            return label().model_copy(update={"source_document_id": kwargs["source_document_id"],
                                              "source_kind": kwargs["source_kind"]})

    monkeypatch.setattr(composition, "build_source_preview", lambda **kwargs: SourcePreviewService(
        provider=Provider(), ids=kwargs["ids"],
    ))
    settings = Settings(database_url=None, supabase_url=None, supabase_publishable_key=None, supabase_secret_key=None,
                        app_env="development", app_origin=None, vision_api_base_url=None, enable_demo_seed=False,
                        persistence="in_memory", auth_mode="demo", source="DEMO_ONLY explicit settings",
                        assistant_workflows_enabled=True)
    root = composition.build_container_from_settings(settings)
    try:
        with TestClient(create_app(container=root)) as client:
            started = client.post("/api/agent/workflows/tasks", params={"client_id": "DEMO-source-configured"}, json={
                "capability_id": "source.preview", "workspace_id": str(uuid4()), "client_event_id": str(uuid4()),
                "values": {"source_kind": "pharmacy_label"}, "save_mode": "ephemeral",
            })
            assert started.status_code == 200, started.text
            task = started.json()
            response = client.post(f"/api/agent/workflows/tasks/{task['task_id']}/source-preview", params={
                "client_id": "DEMO-source-configured", "expected_revision": task["revision"],
                "ephemeral_source_kind": "pharmacy_label",
            }, content=PHOTO, headers={"Content-Type": "image/png", "X-Stage2-Consent": "true"})
            assert response.status_code == 200 and response.json()["outcome"] == "success"
            assert root.assistant_source_preview.preview is root.source_preview
    finally:
        if root.close_request:
            root.close_request()


@pytest.mark.parametrize("bad", ["wrong_kind", "pdf"])
def test_mismatched_provider_source_is_rejected_without_persisting_it(bad, monkeypatch):
    with WorkflowHarness(source_results=[label()]) as h:
        task, attachment = ready(h)
        wrong = label().model_copy(update={"source_kind": "package"} if bad == "wrong_kind"
                                  else {"provider_source": "pdf_text"})
        monkeypatch.setattr(h.container.assistant_source_preview.preview, "preview", lambda **kwargs: wrong)
        result = query(h, task)
        assert result.status_code == 200 and result.json()["outcome"] == "rejected"
        assert result.json()["preview"] is None and raw(h, task, attachment) == PHOTO


def test_new_preview_role_cannot_enter_old_source_extraction_or_sql():
    from app.domain.errors import ProviderUnavailableError
    from app.infrastructure.workflow_repos import SupabaseOriginalRepository

    with WorkflowHarness(source_results=[label()]) as h:
        task, attachment = ready(h)
        denied = h.client.post(f"/api/agent/workflows/tasks/{task['task_id']}/attachments/{attachment['id']}/preview",
                               params={"client_id": "DEMO-workflow-A"}, headers={"X-Stage2-Consent": "true"},
                               json={"expected_revision": task["revision"], "event_id": str(uuid4())})
        assert denied.status_code == 422 and not h.source_calls
        calls = []

        class Data:
            def check_patient(self, owner):
                assert owner == h.owner_ids["A"]

            def request(self, *args, **kwargs):
                calls.append((args, kwargs))
                raise AssertionError("Old SQL cannot accept source preview originals")

        row = h.container.assistant_attachments.originals(h.owner_ids["A"])[0]
        context = h.container.assistant_attachments.context(h.owner_ids["A"], UUID(task["task_id"]), task["revision"])
        with pytest.raises(ProviderUnavailableError):
            SupabaseOriginalRepository(Data()).reserve(context, row)
        assert not calls


@pytest.mark.parametrize("text", ["preview a medication label", "预览药物标签"])
def test_bilingual_source_entry_never_runs_recognition(workflow, text):
    result = workflow._request("POST", "/api/agent/workflows/messages", json={
        "text": text, "workspace_id": workflow.workspace_id, "client_turn_id": str(uuid4()),
    })
    assert result["workflow"]["capability_id"] == "source.preview" and not workflow.source_calls
