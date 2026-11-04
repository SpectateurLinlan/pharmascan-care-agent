"""DEMO_ONLY photo acquisition through actual private-original and gallery services."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from .test_workflow_medication_management import active_plan

PHOTO = Path(__file__).with_name("fixtures").joinpath("DEMO_workflow_photo.png").read_bytes()


def start(h, *, save=True):
    med = active_plan(h)
    return h.start("gallery.photo.add", {"medication_id": med["medication_id"], "image_kind": "package",
                                       "source_description": "DEMO reference package"}, save=save)


def original(h, task):
    return h._request("PUT", f"/api/agent/workflows/tasks/{task['task_id']}/attachments/{uuid4()}",
                      params={"expected_revision": task["revision"], "source_kind": "reference_photo"},
                      content=PHOTO, headers={"Content-Type": "image/png", "X-Stage2-Consent": "true"})


def ready(h):
    task = start(h)
    uploaded = original(h, task)
    assert uploaded["attachment"]["extraction_status"] == "not_requested"
    task = uploaded["workflow"]
    assert task["state"] == "ready_for_review"
    reviewed = h.event(task["task_id"], "prepare_confirmation")
    assert reviewed["result_ref"]["kind"] == "media_review"
    return reviewed, uploaded["attachment"]


def upload(h, task, *, content=PHOTO, params=None, headers=None):
    fields = task["input_fields"]
    return h.client.post(f"/api/evidence/gallery/{fields['medication_id']}/images", params={
        "client_id": "DEMO-workflow-A", "image_kind": fields["image_kind"],
        "source_description": fields["source_description"], "reviewed": "true", "for_comparison": "false",
        **(params or {}),
    }, content=content, headers={"Content-Type": "image/png", "X-Stage2-Consent": "true",
                                "X-Assistant-Task": task["task_id"],
                                "X-Assistant-Revision": str(task["revision"]), **(headers or {})})


def test_reference_original_is_store_only_and_independent_native_upload_reads_real_result(workflow):
    h = workflow
    task, attachment = ready(h)
    assert not h.source_calls
    assert all(not row["images"] for row in h._request("GET", "/api/evidence/gallery"))
    body = h.client.get(f"/api/agent/workflows/tasks/{task['task_id']}/attachments/{attachment['id']}",
                        params={"client_id": "DEMO-workflow-A"})
    assert body.content == PHOTO
    result = upload(h, task)
    assert result.status_code == 200, result.text
    assert result.json()["photo"]["eligibility"] != "eligible"
    assert upload(h, task).json() == result.json()
    completed = h.event(task["task_id"], "report_business_result")
    assert completed["state"] == "completed"
    assert completed["result_ref"] == {"kind": "file", "id": result.json()["photo"]["id"], "version": 1}
    assert sum(len(row["images"]) for row in h._request("GET", "/api/evidence/gallery")) == 1
    assert "storage_path" not in str(completed["visible_fields"])


def test_failed_native_upload_retains_the_exact_original_and_fields(workflow, monkeypatch):
    from app.domain.errors import ProviderUnavailableError

    h = workflow
    task, attachment = ready(h)

    def fail(**kwargs):
        raise ProviderUnavailableError("DEMO native gallery unavailable")

    monkeypatch.setattr(h.container.gallery, "upload_with_status", fail)
    assert upload(h, task).status_code == 503
    pending = h.event(task["task_id"], "report_business_result")
    assert pending["state"] != "completed"
    assert pending["input_fields"]["source_description"] == "DEMO reference package"
    content = h.client.get(f"/api/agent/workflows/tasks/{task['task_id']}/attachments/{attachment['id']}",
                           params={"client_id": "DEMO-workflow-A"})
    assert content.content == PHOTO and not h.source_calls


@pytest.mark.parametrize("change", ["bytes", "metadata", "confirmation", "consent", "comparison", "revision"])
def test_bound_photo_upload_rejects_unreviewed_or_substituted_inputs(workflow, change):
    h = workflow
    task, _ = ready(h)
    options = {}
    if change == "bytes":
        options["content"] = (Path(__file__).with_name("fixtures")
                              .joinpath("DEMO_workflow_photo_unavailable.png").read_bytes())
    elif change == "metadata":
        options["params"] = {"source_description": "DEMO substituted description"}
    elif change == "confirmation":
        options["params"] = {"reviewed": "false"}
    elif change == "comparison":
        options["params"] = {"for_comparison": "true"}
    else:
        options["headers"] = {"X-Stage2-Consent": "false"} if change == "consent" else {"X-Assistant-Revision": "1"}
    response = upload(h, task, **options)
    assert response.status_code in {409, 422}, response.text
    assert all(not row["images"] for row in h._request("GET", "/api/evidence/gallery"))


@pytest.mark.parametrize("save_business", [False, True])
def test_cancel_saving_removes_raw_draft_but_keeps_independently_saved_gallery_copy(workflow, save_business):
    h = workflow
    task, attachment = ready(h)
    if save_business:
        assert upload(h, task).status_code == 200
    h.event(task["task_id"], "cancel_save")
    status = h.container.assistant_cleanup.status(h.owner_ids["A"], UUID(task["task_id"]))
    assert status.pending is False and status.protected is False
    assert sum(len(row["images"]) for row in h._request("GET", "/api/evidence/gallery")) == int(save_business)
    assert not h.container.assistant_attachments.originals(h.owner_ids["A"])


def test_reference_original_never_calls_an_available_source_provider():
    from .test_workflow_photo_enrollment import label
    from .workflow_support import WorkflowHarness

    with WorkflowHarness(source_results=[label()]) as h:
        task, attachment = ready(h)
        assert not h.source_calls
        denied = h.client.post(f"/api/agent/workflows/tasks/{task['task_id']}/attachments/{attachment['id']}/preview",
                               params={"client_id": "DEMO-workflow-A"},
                               json={"expected_revision": task["revision"], "event_id": str(uuid4())},
                               headers={"X-Stage2-Consent": "true"})
        assert denied.status_code == 422 and not h.source_calls


def test_reference_original_is_denied_before_any_unaccepted_sql_transport(workflow):
    from app.domain.errors import ProviderUnavailableError
    from app.infrastructure.workflow_repos import SupabaseOriginalRepository

    h = workflow
    task, _ = ready(h)
    row = h.container.assistant_attachments.originals(h.owner_ids["A"])[0]
    calls = []

    class Data:
        def check_patient(self, owner):
            assert owner == h.owner_ids["A"]

        def request(self, *args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("Reference originals must not reach the old SQL contract")

    context = h.container.assistant_attachments.context(h.owner_ids["A"], UUID(task["task_id"]), task["revision"])
    with pytest.raises(ProviderUnavailableError):
        SupabaseOriginalRepository(Data()).reserve(context, row)
    assert not calls


def test_explicit_retry_after_missing_success_receipt_creates_no_second_photo(workflow, monkeypatch):
    from app.domain.errors import ProviderUnavailableError

    h = workflow
    task, _ = ready(h)
    actions = h.container.assistant_photo_upload.adapter.actions
    complete = actions.complete

    def missing_once(context, receipt):
        if receipt.safe_reason == "photo_uploaded":
            raise ProviderUnavailableError("DEMO lost receipt after real gallery save")
        return complete(context, receipt)

    monkeypatch.setattr(actions, "complete", missing_once)
    assert upload(h, task).status_code == 503
    checked = h.event(task["task_id"], "report_business_result")
    assert checked["state"] != "completed"
    monkeypatch.setattr(actions, "complete", complete)
    retried = upload(h, checked)
    assert retried.status_code == 200 and retried.json()["duplicate"] is True
    assert h.event(task["task_id"], "report_business_result")["state"] == "completed"
    assert sum(len(row["images"]) for row in h._request("GET", "/api/evidence/gallery")) == 1


def test_lost_original_store_acknowledgement_recovers_same_bytes_without_another_upload_or_ocr():
    from app.domain.errors import ProviderUnavailableError
    from app.infrastructure.memory_workflows import MemoryWorkflowObjects, MemoryWorkflowState

    from .workflow_support import WorkflowHarness

    class LostAcknowledgement(MemoryWorkflowObjects):
        calls = 0

        def put_original(self, *args, **kwargs):
            result = super().put_original(*args, **kwargs)
            self.calls += 1
            if self.calls == 1:
                raise ProviderUnavailableError("DEMO original stored but acknowledgement lost")
            return result

    storage = LostAcknowledgement(state=MemoryWorkflowState())
    with WorkflowHarness(original_storage=storage) as h:
        task = start(h)
        response = h.client.put(f"/api/agent/workflows/tasks/{task['task_id']}/attachments/{uuid4()}",
                                params={"client_id": "DEMO-workflow-A", "expected_revision": task["revision"],
                                        "source_kind": "reference_photo"},
                                content=PHOTO, headers={"Content-Type": "image/png"})
        assert response.status_code == 503
        attachment = h.container.assistant_attachments.originals(h.owner_ids["A"])[0]
        h.clock.advance(minutes=10)
        current = h.view(task["task_id"])
        route = f"/api/agent/workflows/tasks/{task['task_id']}/attachments/{attachment.id}"
        recovered = h._request("POST", f"{route}/recover", json={
            "expected_revision": current["revision"], "event_id": str(uuid4()),
        })
        assert recovered["attachment"]["extraction_status"] == "not_requested"
        assert recovered["workflow"]["state"] == "ready_for_review"
        assert h.client.get(route, params={"client_id": "DEMO-workflow-A"}).content == PHOTO
        assert storage.calls == 1 and not h.source_calls


@pytest.mark.parametrize("text", ["add a reference photo", "添加药物照片"])
def test_bilingual_reference_entry_starts_only_the_upload_draft(workflow, text):
    result = workflow._request("POST", "/api/agent/workflows/messages", json={
        "text": text, "workspace_id": workflow.workspace_id, "client_turn_id": str(uuid4()),
    })
    assert result["workflow"]["capability_id"] == "gallery.photo.add"
    assert result["workflow"]["result_ref"] is None
    assert not workflow.source_calls


def test_reference_original_cannot_be_sent_to_source_ocr(workflow):
    h = workflow
    task, attachment = ready(h)
    response = h.client.post(f"/api/agent/workflows/tasks/{task['task_id']}/attachments/{attachment['id']}/preview",
                             params={"client_id": "DEMO-workflow-A"},
                             json={"expected_revision": task["revision"], "event_id": str(uuid4())},
                             headers={"X-Stage2-Consent": "true"})
    assert response.status_code == 422 and not h.source_calls
    assert h.view(task["task_id"])["revision"] == task["revision"]


def test_no_save_reference_photo_draft_stores_no_original_or_business_record(workflow):
    h = workflow
    task = start(h, save=False)
    assert task["save_mode"] == "ephemeral"
    assert not h.container.assistant_attachments.originals(h.owner_ids["A"])
    response = h.client.put(f"/api/agent/workflows/tasks/{task['task_id']}/attachments/{uuid4()}",
                            params={"client_id": "DEMO-workflow-A", "expected_revision": task["revision"],
                                    "source_kind": "reference_photo"},
                            content=PHOTO, headers={"Content-Type": "image/png"})
    assert response.status_code in {409, 422}
