"""DEMO_ONLY actual original retention and native PDF library boundary."""

from uuid import UUID, uuid4

import pytest

from .test_workflow_medication_management import active_plan

PDF = b"%PDF-1.7\n% DEMO_ONLY original document\n%%EOF"


def start(h, *, save=True):
    med = active_plan(h)
    return h.start("library.pdf.add", {"medication_id": med["medication_id"], "filename": "DEMO_original.pdf",
                                      "category": "prescription", "description": "DEMO unextracted PDF"}, save=save)


def original(h, task, data=PDF, kind="library_pdf", mime="application/pdf"):
    return h.client.put(f"/api/agent/workflows/tasks/{task['task_id']}/attachments/{uuid4()}", params={
        "client_id": "DEMO-workflow-A", "expected_revision": task["revision"], "source_kind": kind,
    }, content=data, headers={"Content-Type": mime, "X-Stage2-Consent": "true"})


def ready(h):
    task = start(h)
    response = original(h, task)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["attachment"]["extraction_status"] == "not_requested"
    return h.event(task["task_id"], "prepare_confirmation"), result["attachment"]


def upload(h, task, *, content=PDF, params=None, headers=None, owner="A"):
    fields = task["input_fields"]
    return h.client.post(f"/api/evidence/gallery/{fields['medication_id']}/pdfs", params={
        "client_id": "DEMO-workflow-" + owner, "filename": fields["filename"], "category": fields["category"],
        "description": fields["description"], "confirmed": "true", **(params or {}),
    }, content=content, headers={"Content-Type": "application/pdf", "X-Assistant-Task": task["task_id"],
                               "X-Assistant-Revision": str(task["revision"]), **(headers or {})})


def raw(h, task, attachment):
    return h.client.get(f"/api/agent/workflows/tasks/{task['task_id']}/attachments/{attachment['id']}",
                        params={"client_id": "DEMO-workflow-A"})


def test_saved_pdf_original_is_store_only_and_separate_native_confirmation_completes(workflow):
    h = workflow
    task, attachment = ready(h)
    assert task["result_ref"]["kind"] == "media_review"
    assert h.container.library_files.list(h.owner_ids["A"], UUID(task["input_fields"]["medication_id"])) == []
    assert raw(h, task, attachment).content == PDF and not h.source_calls
    response = upload(h, task)
    assert response.status_code == 200, response.text
    assert upload(h, task).json() == response.json()
    complete = h.event(task["task_id"], "report_business_result")
    assert complete["state"] == "completed"
    assert complete["result_ref"] == {"kind": "file", "id": response.json()["file"]["id"], "version": 1}
    assert not h.source_calls
    assert "storage_path" not in str(complete["visible_fields"])


@pytest.mark.parametrize("change", [
    "bytes", "filename", "category", "description", "confirmation", "revision", "owner",
])
def test_bound_pdf_rejects_substitution_or_missing_patient_authority(workflow, change):
    h = workflow
    task, attachment = ready(h)
    options = {}
    if change == "bytes":
        options["content"] = b"%PDF-1.7\n% DEMO other bytes\n%%EOF"
    elif change == "owner":
        options["owner"] = "B"
    elif change == "revision":
        options["headers"] = {"X-Assistant-Revision": "1"}
    else:
        options["params"] = {
            "filename": {"filename": "DEMO_other.pdf"}, "category": {"category": "other"},
            "description": {"description": "DEMO substituted"}, "confirmation": {"confirmed": "false"},
        }[change]
    response = upload(h, task, **options)
    assert response.status_code in {404, 409, 422}, response.text
    assert h.container.library_files.list(h.owner_ids["A"], UUID(task["input_fields"]["medication_id"])) == []
    assert raw(h, task, attachment).content == PDF


def test_native_pdf_failure_retains_exact_original_and_draft(workflow, monkeypatch):
    from app.domain.errors import ProviderUnavailableError

    h = workflow
    task, attachment = ready(h)

    def unavailable(**kwargs):
        raise ProviderUnavailableError("DEMO native PDF unavailable")

    monkeypatch.setattr(h.container.library_files, "upload", unavailable)
    assert upload(h, task).status_code == 503
    checked = h.event(task["task_id"], "report_business_result")
    assert checked["state"] != "completed" and checked["input_fields"]["filename"] == "DEMO_original.pdf"
    assert raw(h, task, attachment).content == PDF and not h.source_calls


@pytest.mark.parametrize("save_business", [False, True])
def test_revoke_pdf_saving_cleans_raw_only_and_preserves_confirmed_library_copy(workflow, save_business):
    h = workflow
    task, attachment = ready(h)
    if save_business:
        assert upload(h, task).status_code == 200
    h.event(task["task_id"], "cancel_save")
    status = h.container.assistant_cleanup.status(h.owner_ids["A"], UUID(task["task_id"]))
    assert not status.pending and not status.protected
    assert not h.container.assistant_attachments.originals(h.owner_ids["A"])
    files = h.container.library_files.list(h.owner_ids["A"], UUID(task["input_fields"]["medication_id"]))
    assert len(files) == int(save_business)
    if save_business:
        assert h.container.library_files.content(h.owner_ids["A"], files[0].id)[1] == PDF


def test_no_save_pdf_has_no_server_original_or_native_record(workflow):
    h = workflow
    task = start(h, save=False)
    assert original(h, task).status_code == 422
    assert not h.container.assistant_attachments.originals(h.owner_ids["A"])
    assert h.container.library_files.list(h.owner_ids["A"], UUID(task["input_fields"]["medication_id"])) == []


def test_pdf_cannot_reach_source_provider_or_old_sql_transport():
    from app.domain.errors import ProviderUnavailableError
    from app.infrastructure.workflow_repos import SupabaseOriginalRepository

    from .test_workflow_photo_enrollment import label
    from .workflow_support import WorkflowHarness

    with WorkflowHarness(source_results=[label()]) as h:
        task, attachment = ready(h)
        denied = h.client.post(
            f"/api/agent/workflows/tasks/{task['task_id']}/attachments/{attachment['id']}/preview",
            params={"client_id": "DEMO-workflow-A"}, headers={"X-Stage2-Consent": "true"},
            json={"expected_revision": task["revision"], "event_id": str(uuid4())},
        )
        assert denied.status_code == 422 and not h.source_calls
        calls = []

        class Data:
            def check_patient(self, owner):
                assert owner == h.owner_ids["A"]

            def request(self, *args, **kwargs):
                calls.append((args, kwargs))
                raise AssertionError("Old SQL must never receive PDF originals")

        row = h.container.assistant_attachments.originals(h.owner_ids["A"])[0]
        context = h.container.assistant_attachments.context(h.owner_ids["A"], UUID(task["task_id"]), task["revision"])
        with pytest.raises(ProviderUnavailableError):
            SupabaseOriginalRepository(Data()).reserve(context, row)
        assert not calls


def test_pdf_original_acknowledgement_loss_recovers_exact_bytes_without_image_decode():
    from app.domain.errors import ProviderUnavailableError
    from app.infrastructure.memory_workflows import MemoryWorkflowObjects, MemoryWorkflowState

    from .workflow_support import WorkflowHarness

    class LostAcknowledgement(MemoryWorkflowObjects):
        calls = 0

        def put_original(self, *args, **kwargs):
            result = super().put_original(*args, **kwargs)
            self.calls += 1
            if self.calls == 1:
                raise ProviderUnavailableError("DEMO PDF saved but acknowledgement lost")
            return result

    storage = LostAcknowledgement(state=MemoryWorkflowState())
    with WorkflowHarness(original_storage=storage) as h:
        task = start(h)
        assert original(h, task).status_code == 503
        row = h.container.assistant_attachments.originals(h.owner_ids["A"])[0]
        h.clock.advance(minutes=10)
        current = h.view(task["task_id"])
        recovered = h._request("POST", f"/api/agent/workflows/tasks/{task['task_id']}/attachments/{row.id}/recover",
                               json={"expected_revision": current["revision"], "event_id": str(uuid4())})
        assert recovered["attachment"]["extraction_status"] == "not_requested"
        assert raw(h, task, recovered["attachment"]).content == PDF
        assert storage.calls == 1 and not h.source_calls


def test_pdf_retry_after_lost_native_receipt_has_one_real_file(workflow, monkeypatch):
    from app.domain.errors import ProviderUnavailableError

    h = workflow
    task, _ = ready(h)
    actions = h.container.assistant_pdf_upload.adapter.actions
    complete = actions.complete

    def fail_once(context, receipt):
        if receipt.safe_reason == "pdf_uploaded":
            raise ProviderUnavailableError("DEMO receipt lost after save")
        return complete(context, receipt)

    monkeypatch.setattr(actions, "complete", fail_once)
    assert upload(h, task).status_code == 503
    pending = h.event(task["task_id"], "report_business_result")
    assert pending["state"] != "completed"
    monkeypatch.setattr(actions, "complete", complete)
    retried = upload(h, pending)
    assert retried.status_code == 200 and retried.json()["duplicate"] is True
    assert h.event(task["task_id"], "report_business_result")["state"] == "completed"
    assert len(h.container.library_files.list(h.owner_ids["A"], UUID(task["input_fields"]["medication_id"]))) == 1


def test_pdf_original_preserves_native_ten_mib_limit_without_image_decode(workflow):
    h = workflow
    task = start(h)
    big = b"%PDF-1.7\n" + b"D" * 8_000_000 + b"\n%%EOF"
    response = original(h, task, big)
    assert response.status_code == 200, response.text
    assert raw(h, task, response.json()["attachment"]).content == big
    updated = response.json()["workflow"]
    too_big = b"%PDF-1.7\n" + b"D" * (10 * 1024 * 1024) + b"\n%%EOF"
    assert original(h, updated, too_big).status_code == 422


@pytest.mark.parametrize("data,kind,mime", [(b"DEMO invalid PDF", "library_pdf", "application/pdf"),
                                             (PDF, "prescription", "application/pdf"),
                                             (PDF, "library_pdf", "image/png")])
def test_invalid_pdf_or_role_never_stores_bytes(workflow, data, kind, mime):
    h = workflow
    task = start(h)
    assert original(h, task, data, kind, mime).status_code == 422
    assert not h.container.assistant_attachments.originals(h.owner_ids["A"])


@pytest.mark.parametrize("text", ["upload a medication PDF", "上传药物PDF"])
def test_bilingual_pdf_entry_opens_upload_draft_without_processing(workflow, text):
    response = workflow._request("POST", "/api/agent/workflows/messages", json={
        "text": text, "workspace_id": workflow.workspace_id, "client_turn_id": str(uuid4()),
    })
    assert response["workflow"]["capability_id"] == "library.pdf.add"
    assert response["workflow"]["result_ref"] is None and not workflow.source_calls
