"""DEMO_ONLY actual workflow/original/visual services; no live provider or patient writes."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from .test_medication_evidence import Vision, evidence  # noqa: F401
from .test_workflow_medication_management import active_plan
from .test_workflow_records import clinical

PHOTO = Path(__file__).with_name("fixtures").joinpath("DEMO_workflow_photo.png").read_bytes()


def ready(h, *, intent="identify", save=True):
    task = h.start("image.compare", {"intent": intent}, save=save)
    if not save:
        return task, None
    uploaded = h._request("PUT", f"/api/agent/workflows/tasks/{task['task_id']}/attachments/{uuid4()}", params={
        "expected_revision": task["revision"], "source_kind": "comparison_photo",
    }, content=PHOTO, headers={"Content-Type": "image/png", "X-Stage2-Consent": "true"})
    return uploaded["workflow"], uploaded["attachment"]


def configure(h, *, fail=False, ambiguous=False, during=None, gallery=None):
    from app.application.visual_check import VisualCheckService
    from app.application.workflow_image_compare import WorkflowImageCompareService
    from app.contracts.vision import PillCandidate, ScanDiagnostics
    from app.contracts.visual_check import VisualEvidence
    from app.domain.errors import ProviderUnavailableError
    from app.infrastructure.evidence_images import patient_source_image

    calls = []

    class Replay:
        def inspect(self, data):
            calls.append(data)
            if during:
                during()
            if fail:
                raise ProviderUnavailableError("DEMO visual provider unavailable")
            return VisualEvidence(model=Vision.model, detection=ScanDiagnostics(pill_count=2 if ambiguous else 1),
                                  candidates=[PillCandidate(external_catalogue_id="DEMO-public-candidate",
                                                           display_name="DEMO catalogue name", strength="DEMO 1 mg",
                                                           visual_similarity=0.99)])

    h.container.assistant_image_compare = WorkflowImageCompareService(
        workflows=h.container.assistant_workflows, attachments=h.container.assistant_attachments,
        enrollment=h.container.enrollment, gallery=gallery or h.container.gallery,
        visual=VisualCheckService(provider=Replay()), normalize=patient_source_image,
        clinical=h.container.assistant_image_compare.clinical,
    )
    return calls


def query(h, task, *, content=PHOTO, consent=True, params=None, owner="A"):
    return h.client.post(f"/api/agent/workflows/tasks/{task['task_id']}/compare", params={
        "client_id": "DEMO-workflow-" + owner, "expected_revision": task["revision"], **(params or {}),
    }, content=content, headers={"Content-Type": "image/png", "X-Stage2-Consent": str(consent).lower()})


def test_task_preparation_and_reopening_never_process_images_or_persist_results(workflow):
    h = workflow
    before = clinical(h)
    task, attachment = ready(h)
    calls = configure(h)
    h.view(task["task_id"])
    h.container.assistant_workflows.list_views(h.owner_ids["A"])
    assert not calls
    assert attachment["extraction_status"] == "not_requested"
    result = query(h, task)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["decision"] == "unknown" and body["reason_key"] == "no_reviewed_reference"
    assert body["candidates"][0]["name"] == "DEMO catalogue name"
    assert not body["safe_to_take"] and not body["ingestion_proven"] and not body["count_reliable"]
    assert calls == [PHOTO] and clinical(h) == before
    assert "0.99" not in str(body) and "external_catalogue_id" not in str(body)
    assert "candidates" not in h.view(task["task_id"])["visible_fields"]


@pytest.mark.parametrize("ambiguous,fail,decision,reason", [
    (True, False, "ambiguous", "image_unclear"), (False, True, "unavailable", "service_unavailable"),
])
def test_real_provider_outcome_remains_distinct_and_original_survives(workflow, ambiguous, fail, decision, reason):
    h = workflow
    task, attachment = ready(h)
    configure(h, fail=fail, ambiguous=ambiguous)
    result = query(h, task)
    assert result.status_code == 200, result.text
    assert (result.json()["decision"], result.json()["reason_key"]) == (decision, reason)
    saved = h.client.get(f"/api/agent/workflows/tasks/{task['task_id']}/attachments/{attachment['id']}",
                         params={"client_id": "DEMO-workflow-A"})
    assert saved.content == PHOTO


def test_no_save_compare_requires_page_values_and_saves_no_original_or_history(workflow):
    h = workflow
    task, _ = ready(h, save=False)
    calls = configure(h)
    assert query(h, task).status_code == 422 and not calls
    result = query(h, task, params={"ephemeral_intent": "identify"})
    assert result.status_code == 200 and result.json()["decision"] == "unknown"
    assert not h.container.assistant_attachments.originals(h.owner_ids["A"])
    assert not h.source_calls


@pytest.mark.parametrize("change", ["consent", "revision", "owner", "bytes", "page_override"])
def test_comparison_rejects_unbound_or_changed_inputs_before_provider(workflow, change):
    h = workflow
    task, _ = ready(h)
    calls = configure(h)
    options = {"consent": {"consent": False}, "revision": {"params": {"expected_revision": 1}},
               "owner": {"owner": "B"}, "bytes": {"content": PHOTO + b"DEMO altered"},
               "page_override": {"params": {"ephemeral_intent": "personal"}}}[change]
    result = query(h, task, **options)
    assert result.status_code in {404, 409, 422}, result.text
    assert not calls


def test_saved_comparison_requires_a_retained_original_before_processing(workflow):
    h = workflow
    task = h.start("image.compare", {"intent": "identify"})
    calls = configure(h)
    assert query(h, task).status_code == 422 and not calls


def test_comparison_original_is_denied_to_source_recognition_and_old_sql(workflow):
    from app.domain.errors import ProviderUnavailableError
    from app.infrastructure.workflow_repos import SupabaseOriginalRepository

    h = workflow
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
            raise AssertionError("Old SQL cannot accept comparison originals")

    row = h.container.assistant_attachments.originals(h.owner_ids["A"])[0]
    context = h.container.assistant_attachments.context(h.owner_ids["A"], UUID(task["task_id"]), task["revision"])
    with pytest.raises(ProviderUnavailableError):
        SupabaseOriginalRepository(Data()).reserve(context, row)
    assert not calls


def test_query_authority_does_not_expand_to_other_device_or_write_capabilities(workflow):
    from app.domain.errors import ValidationError

    h = workflow
    task, _ = ready(h)
    for capability in ("source.preview", "speech.input", "dose.report", "gallery.photo.add"):
        with pytest.raises(ValidationError):
            h.container.assistant_workflows.read_only_input(h.owner_ids["A"], UUID(task["task_id"]),
                                                           task["revision"], capability)


def test_no_save_comparison_cannot_use_source_recognition_endpoint():
    from .test_workflow_photo_enrollment import label
    from .workflow_support import WorkflowHarness

    with WorkflowHarness(source_results=[label()]) as h:
        task, _ = ready(h, save=False)
        response = h.client.post(f"/api/agent/workflows/tasks/{task['task_id']}/preview-image/{uuid4()}", params={
            "client_id": "DEMO-workflow-A", "expected_revision": task["revision"], "source_kind": "pharmacy_label",
        }, content=PHOTO, headers={"Content-Type": "image/png", "X-Stage2-Consent": "true"})
        assert response.status_code == 422 and not h.source_calls


def test_configured_demo_reuses_its_existing_visual_service_without_new_provider_configuration(monkeypatch):
    from app.application.visual_check import VisualCheckService
    from app.config import Settings
    from app.contracts.vision import ScanDiagnostics
    from app.contracts.visual_check import VisualEvidence
    from app.transport import container as composition
    from app.transport.app_factory import create_app
    from fastapi.testclient import TestClient

    class Provider:
        def inspect(self, image):
            return VisualEvidence(model=Vision.model, detection=ScanDiagnostics(pill_count=1), candidates=[])

    monkeypatch.setattr(composition, "build_visual_check", lambda **kwargs: VisualCheckService(provider=Provider()))
    settings = Settings(database_url=None, supabase_url=None, supabase_publishable_key=None, supabase_secret_key=None,
                        app_env="development", app_origin=None, vision_api_base_url=None, enable_demo_seed=False,
                        persistence="in_memory", auth_mode="demo", source="DEMO_ONLY explicit settings",
                        assistant_workflows_enabled=True)
    root = composition.build_container_from_settings(settings)
    try:
        with TestClient(create_app(container=root)) as client:
            started = client.post("/api/agent/workflows/tasks", params={"client_id": "DEMO-configured"}, json={
                "capability_id": "image.compare", "workspace_id": str(uuid4()), "client_event_id": str(uuid4()),
                "values": {"intent": "identify"}, "save_mode": "ephemeral",
            })
            assert started.status_code == 200, started.text
            task = started.json()
            response = client.post(f"/api/agent/workflows/tasks/{task['task_id']}/compare", params={
                "client_id": "DEMO-configured", "expected_revision": task["revision"], "ephemeral_intent": "identify",
            }, content=PHOTO, headers={"Content-Type": "image/png", "X-Stage2-Consent": "true"})
            assert response.status_code == 200 and response.json()["decision"] == "unknown"
    finally:
        if root.close_request:
            root.close_request()


def test_revoking_save_during_provider_discards_result_and_cleans_raw_original(workflow):
    h = workflow
    task, _ = ready(h)
    calls = configure(h, during=lambda: h.event(task["task_id"], "cancel_save"))
    assert query(h, task).status_code in {409, 422}
    assert calls and not h.container.assistant_attachments.originals(h.owner_ids["A"])


def test_concurrent_medication_change_discards_the_inflight_visual_result(workflow):
    h = workflow
    task, _ = ready(h)
    configure(h, during=lambda: active_plan(h))
    assert query(h, task).status_code == 409


def test_compare_rejects_foreign_or_inactive_regimen_before_provider(workflow):
    h = workflow
    med = active_plan(h)
    task = h.start("image.compare", {"intent": "personal", "regimen_id": med["regimen_id"]})
    assert h.client.post("/api/agent/workflows/tasks", params={"client_id": "DEMO-workflow-B"}, json={
        "capability_id": "image.compare", "workspace_id": str(uuid4()), "values": task["input_fields"],
        "save_mode": "allowed", "client_event_id": str(uuid4()),
    }).status_code == 404


def test_personal_preview_keeps_native_recognition_history_unchanged(workflow, evidence):  # noqa: F811
    from .test_medication_evidence import PATIENT

    h = workflow
    _, gallery, repo, _, vision = evidence
    task, _ = ready(h, intent="personal", save=False)
    configure(h, gallery=gallery)
    assert not repo.list(h.owner_ids["A"], "runs")
    result = query(h, task, params={"ephemeral_intent": "personal"})
    assert result.status_code == 200 and result.json()["decision"] == "missing_reference"
    assert not repo.list(h.owner_ids["A"], "runs") and vision.calls == 0
    native = gallery.check(patient_id=PATIENT, regimen_id=None, image=PHOTO, consent=True, demo_only=True)
    assert repo.get(PATIENT, "runs", native.id) == native


@pytest.mark.parametrize("text", ["compare a pill photo", "比对药片照片"])
def test_bilingual_entry_opens_comparison_without_processing(workflow, text):
    result = workflow._request("POST", "/api/agent/workflows/messages", json={
        "text": text, "workspace_id": workflow.workspace_id, "client_turn_id": str(uuid4()),
    })
    assert result["workflow"]["capability_id"] == "image.compare" and not workflow.source_calls
