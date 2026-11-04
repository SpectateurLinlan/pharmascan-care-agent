"""DEMO_ONLY actual native lifecycle with separate patient confirmation."""

from uuid import UUID, uuid4

import pytest

from .test_workflow_media import seed_media
from .test_workflow_medication_management import active_plan

CHANGE_IDS = ("gallery.photo.edit", "gallery.photo.remove", "gallery.photo.delete", "gallery.photo.retire",
              "library.pdf.edit", "library.pdf.delete")


def fields(capability, medication_id, photo, pdf):
    result = {"medication_id": medication_id, "expected_version": 1}
    if capability.startswith("gallery."):
        result["image_id"] = photo["id"]
        if capability.endswith("edit"):
            result.update(image_kind="blister", source_description="DEMO revised photo")
    else:
        result["file_id"] = pdf["id"]
        if capability.endswith("edit"):
            result.update(title="DEMO revised PDF", category="other", description="DEMO patient description")
    return result


def prepare(h, capability, inputs):
    task = h.start(capability, inputs)
    assert task["state"] == "ready_for_review"
    assert task["result_ref"] is None
    task = h.event(task["task_id"], "prepare_confirmation")
    assert task["result_ref"]["kind"] == "media_review"
    assert task["state"] == "awaiting_confirmation"
    return task


def request(h, task, *, headers=None, target=None, body=None, confirmed=True):
    capability = task["capability_id"]
    review = task["visible_fields"]["media_review"]
    target = target or review["target_id"]
    if headers is None:
        headers = {"X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(task["revision"])}
    payload = review["payload"] if body is None else body
    if capability.startswith("gallery."):
        path = f"/api/evidence/images/{target}"
        method = "PATCH"
        if capability.endswith("retire"):
            path += "/retire"
            method = "POST"
    else:
        path = f"/api/evidence/library-files/{target}"
        method = "DELETE" if capability.endswith("delete") else "PATCH"
    return h.client.request(method, path, params={"client_id": "DEMO-workflow-A", "confirmed": str(confirmed).lower()},
                            headers=headers, **({"json": payload} if method == "PATCH" else {}))


@pytest.mark.parametrize("capability", CHANGE_IDS)
def test_six_real_lifecycle_operations_need_review_then_independent_native_confirmation(workflow, capability):
    h = workflow
    med, photo, pdf = seed_media(h)
    task = prepare(h, capability, fields(capability, med, photo, pdf))
    assert len(h.container.library_files.list(h.owner_ids["A"], UUID(med))) == 1
    original = h.client.get(f"/api/evidence/images/{photo['id']}", params={"client_id": "DEMO-workflow-A"})
    assert original.status_code == 200
    before = h._request("GET", f"/api/evidence/gallery/{med}/files")
    assert "DEMO revised" not in str(before)
    assert not task["visible_fields"].get("saved_record")
    response = request(h, task)
    assert response.status_code == 200, response.text
    replay = request(h, task)
    assert replay.status_code == 200 and replay.json() == response.json()
    saved = h.event(task["task_id"], "report_business_result")
    assert saved["state"] == "completed"
    assert saved["result_ref"]["kind"] == "file"
    assert saved["result_ref"]["id"] == (photo["id"] if capability.startswith("gallery.") else pdf["id"])
    actual = saved["visible_fields"]["saved_record"]
    assert actual["version"] == 2
    content = h.client.get(f"/api/evidence/images/{photo['id']}", params={"client_id": "DEMO-workflow-A"})
    if capability == "gallery.photo.delete":
        assert content.status_code == 404 and actual["deleted"] is True
    else:
        assert content.content == original.content
    gallery = h._request("GET", "/api/evidence/gallery")
    image_ids = {image["id"] for row in gallery for image in row["images"]}
    if capability == "gallery.photo.remove":
        assert photo["id"] not in image_ids and actual["gallery_removed"] is True
    if capability == "gallery.photo.retire":
        assert photo["id"] in image_ids and actual["eligibility"] == "ineligible"
    if capability == "library.pdf.delete":
        assert not h.container.library_files.list(h.owner_ids["A"], UUID(med))
    assert "storage_path" not in str(saved["visible_fields"])


@pytest.mark.parametrize("capability", CHANGE_IDS)
def test_changed_owned_metadata_invalidates_prepared_review(workflow, capability):
    h = workflow
    med, photo, pdf = seed_media(h)
    task = prepare(h, capability, fields(capability, med, photo, pdf))
    if capability.startswith("gallery."):
        h._request("PATCH", f"/api/evidence/images/{photo['id']}", json={
            "action": "edit", "expected_version": 1, "image_kind": "package", "source_description": "DEMO newer edit",
        })
    else:
        h._request("PATCH", f"/api/evidence/library-files/{pdf['id']}", json={
            "expected_version": 1, "title": "DEMO newer edit", "category": "other", "description": "",
        })
    response = request(h, task)
    assert response.status_code == 409, response.text
    assert h.event(task["task_id"], "report_business_result")["state"] != "completed"


@pytest.mark.parametrize("guard", ["paused", "revoked", "revision", "half_header", "target", "payload", "confirmation"])
def test_patient_media_boundary_rejects_changed_or_unauthorized_review(workflow, guard):
    h = workflow
    med, photo, pdf = seed_media(h)
    cap = "gallery.photo.edit" if guard == "payload" else "library.pdf.delete"
    task = prepare(h, cap, fields(cap, med, photo, pdf))
    kwargs = {}
    if guard == "paused":
        h.event(task["task_id"], "pause")
    elif guard == "revoked":
        h.event(task["task_id"], "cancel_save")
    elif guard == "revision":
        kwargs["headers"] = {"X-Assistant-Task": task["task_id"], "X-Assistant-Revision": "1"}
    elif guard == "half_header":
        kwargs["headers"] = {"X-Assistant-Task": task["task_id"]}
    elif guard == "target":
        kwargs["target"] = str(uuid4())
    elif guard == "payload":
        kwargs["body"] = {**task["visible_fields"]["media_review"]["payload"], "source_description": "DEMO tampered"}
    else:
        kwargs["confirmed"] = False
    denied = request(h, task, **kwargs)
    assert denied.status_code in {404, 409, 422}, denied.text
    assert len(h._request("GET", f"/api/evidence/gallery/{med}/files")["files"]) == 2


def test_failed_native_write_keeps_draft_and_never_fabricates_success(workflow, monkeypatch):
    h = workflow
    med, photo, pdf = seed_media(h)
    task = prepare(h, "library.pdf.edit", fields("library.pdf.edit", med, photo, pdf))

    def unavailable(*args, **kwargs):
        from app.domain.errors import ProviderUnavailableError
        raise ProviderUnavailableError("DEMO native save unavailable")

    monkeypatch.setattr(h.container.library_files, "update", unavailable)
    assert request(h, task).status_code == 503
    checked = h.event(task["task_id"], "report_business_result")
    assert checked["state"] != "completed"
    assert checked["input_fields"]["title"] == "DEMO revised PDF"
    corrected = h.event(task["task_id"], "provide_fields", {"title": "DEMO corrected PDF"})
    assert corrected["input_fields"]["title"] == "DEMO corrected PDF"


def test_media_no_save_never_retains_sensitive_fields_or_prepared_receipts(workflow):
    h = workflow
    med, photo, pdf = seed_media(h)
    before = len(h.snapshot()["tasks"])
    task = h.start("library.pdf.edit", fields("library.pdf.edit", med, photo, pdf), save=False)
    assert task["save_mode"] == "ephemeral" and task["state"] == "ready_for_review"
    assert len(h.snapshot()["tasks"]) == before
    assert "DEMO revised PDF" not in str(h.snapshot()["workflow_controls"])
    assert not h.container.assistant_media.adapter.actions.list(h.owner_ids["A"], UUID(task["task_id"]))


def test_revoking_an_unexecuted_media_review_keeps_only_content_free_receipt_metadata(workflow):
    h = workflow
    med, photo, pdf = seed_media(h)
    task = prepare(h, "library.pdf.edit", fields("library.pdf.edit", med, photo, pdf))
    h.event(task["task_id"], "cancel_save")
    rows = h.container.assistant_media.adapter.actions.list(h.owner_ids["A"], UUID(task["task_id"]))
    assert all(row.safe_reason == "media_prepared" for row in rows)
    assert "DEMO revised PDF" not in str(rows)


@pytest.mark.parametrize("capability", ["gallery.photo.delete", "library.pdf.delete"])
def test_actual_partial_file_cleanup_stays_pending_and_explicit_retry_completes_once(workflow, monkeypatch, capability):
    from app.domain.errors import ProviderUnavailableError

    h = workflow
    med, photo, pdf = seed_media(h)
    task = prepare(h, capability, fields(capability, med, photo, pdf))
    # Synthetic infrastructure outage only; the real native tombstone and cleanup execute.
    service = h.container.gallery if capability.startswith("gallery.") else h.container.library_files
    original = service._storage.delete
    calls = []

    def fail_once(path):
        calls.append(path)
        if len(calls) == 1:
            raise ProviderUnavailableError("DEMO object cleanup unavailable")
        return original(path)

    monkeypatch.setattr(service._storage, "delete", fail_once)
    assert request(h, task).status_code == 503
    checked = h.event(task["task_id"], "report_business_result")
    assert checked["state"] == "awaiting_confirmation"
    assert checked["visible_fields"]["media_review"]["cleanup_retry"] is True
    assert request(h, checked).status_code == 200
    saved = h.event(task["task_id"], "report_business_result")
    assert saved["state"] == "completed" and saved["visible_fields"]["saved_record"]["version"] == 2
    assert not saved["visible_fields"]["saved_record"]["cleanup_pending"]
    assert len(calls) == 2


def test_native_deletion_without_success_receipt_never_claims_completion_from_absence(workflow, monkeypatch):
    from app.domain.errors import ProviderUnavailableError

    h = workflow
    med, photo, pdf = seed_media(h)
    task = prepare(h, "library.pdf.delete", fields("library.pdf.delete", med, photo, pdf))
    adapter = h.container.assistant_media.adapter
    original = adapter.actions.complete

    def fail_receipt(context, receipt):
        if receipt.safe_reason == "media_saved":
            raise ProviderUnavailableError("DEMO receipt unavailable after native deletion")
        return original(context, receipt)

    monkeypatch.setattr(adapter.actions, "complete", fail_receipt)
    assert request(h, task).status_code == 503
    checked = h.event(task["task_id"], "report_business_result")
    assert checked["state"] != "completed" and not checked["visible_fields"].get("saved_record")
    assert h.client.get(f"/api/evidence/library-files/{pdf['id']}",
                        params={"client_id": "DEMO-workflow-A"}).status_code == 404


def test_foreign_patient_cannot_use_an_owned_media_review(workflow):
    h = workflow
    med, photo, pdf = seed_media(h)
    task = prepare(h, "library.pdf.delete", fields("library.pdf.delete", med, photo, pdf))
    denied = h.client.delete(f"/api/evidence/library-files/{pdf['id']}",
                             params={"client_id": "DEMO-workflow-B", "confirmed": "true"}, headers={
                                 "X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(task["revision"]),
                             })
    assert denied.status_code == 404
    assert h.container.library_files.metadata(h.owner_ids["A"], UUID(pdf["id"])).deleted_at is None


@pytest.mark.parametrize("capability", ["gallery.photo.delete", "library.pdf.delete"])
def test_lifecycle_draft_rejects_cross_medication_file_selection(workflow, capability):
    h = workflow
    med, photo, pdf = seed_media(h)
    other = active_plan(h, name="DEMO different file owner medication")
    selected = {**fields(capability, med, photo, pdf), "medication_id": other["medication_id"]}
    response = h.client.post("/api/agent/workflows/tasks", params={"client_id": "DEMO-workflow-A"}, json={
        "capability_id": capability, "workspace_id": h.workspace_id, "values": selected,
        "client_event_id": str(uuid4()), "save_mode": "allowed",
    })
    assert response.status_code == 404


@pytest.mark.parametrize("capability", ["gallery.photo.delete", "library.pdf.delete"])
def test_lifecycle_cannot_prepare_deletion_of_actual_source_linked_fixture_records(workflow, capability):
    import hashlib

    h = workflow
    med, photo, pdf = seed_media(h)
    owner = h.owner_ids["A"]
    source = h.container.enrollment.list_regimens(owner, UUID(med))[0].source_id
    assert source is not None
    # Infrastructure fixture setup only; the workflow then uses actual public services.
    if capability.startswith("gallery."):
        row = h.container.gallery.metadata(owner, UUID(photo["id"]))
        protected = row.model_copy(update={"id": uuid4(), "source_id": source})
        h.container.gallery._repo.add("images", protected)
        photo = {**photo, "id": str(protected.id)}
    else:
        row = h.container.library_files.metadata(owner, UUID(pdf["id"]))
        content = b"%PDF-1.7\nDEMO_ONLY_source_linked_fixture\n%%EOF"
        digest = hashlib.sha256(content).hexdigest()
        path = f"{owner}/library/{med}/{digest}.pdf"
        h.container.library_files._storage.put(path, content)
        protected = row.model_copy(update={"id": uuid4(), "source_document_id": source,
                                           "checksum": digest, "storage_path": path, "byte_size": len(content)})
        inserted, duplicate = h.container.library_files._repo.add_if_absent(protected)
        assert not duplicate and inserted.id == protected.id
        pdf = {**pdf, "id": str(protected.id)}
    assert (h.container.gallery.metadata(owner, UUID(photo["id"])).source_id == source
            if capability.startswith("gallery.") else
            h.container.library_files.metadata(owner, UUID(pdf["id"])).source_document_id == source)
    response = h.client.post("/api/agent/workflows/tasks", params={"client_id": "DEMO-workflow-A"}, json={
        "capability_id": capability, "workspace_id": h.workspace_id, "values": fields(capability, med, photo, pdf),
        "client_event_id": str(uuid4()), "save_mode": "allowed",
    })
    assert response.status_code == 422
    assert h.client.get(f"/api/evidence/images/{photo['id']}",
                        params={"client_id": "DEMO-workflow-A"}).status_code == 200


def test_concurrent_patient_confirmations_do_not_duplicate_a_metadata_change(workflow):
    from concurrent.futures import ThreadPoolExecutor

    h = workflow
    med, photo, pdf = seed_media(h)
    task = prepare(h, "library.pdf.edit", fields("library.pdf.edit", med, photo, pdf))
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: request(h, task), range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert h.container.library_files.metadata(h.owner_ids["A"], UUID(pdf["id"])).version == 2


def test_completed_file_action_keeps_its_receipt_when_the_native_file_later_changes(workflow):
    h = workflow
    med, photo, pdf = seed_media(h)
    task = prepare(h, "library.pdf.edit", fields("library.pdf.edit", med, photo, pdf))
    assert request(h, task).status_code == 200
    completed = h.event(task["task_id"], "report_business_result")
    h._request("PATCH", f"/api/evidence/library-files/{pdf['id']}", json={
        "expected_version": 2, "title": "DEMO later native title", "category": "other", "description": "",
    })
    previous = h.view(task["task_id"])
    assert previous["state"] == "completed" and previous["result_ref"] == completed["result_ref"]
    assert previous["visible_fields"]["historical_result"] is True
    assert "DEMO later native title" not in str(previous["visible_fields"])
    denied = h.client.post(f"/api/agent/workflows/tasks/{task['task_id']}/events",
                           params={"client_id": "DEMO-workflow-A"}, json={
                               "event_id": str(uuid4()), "expected_revision": previous["revision"],
                               "kind": "report_business_result", "values": {},
                           })
    assert denied.status_code == 422  # Completed workflows remain non-executable.
    assert h.view(task["task_id"])["result_ref"] == completed["result_ref"]


@pytest.mark.parametrize("text,capability", [
    ("edit a medication photo", "gallery.photo.edit"), ("编辑药物照片", "gallery.photo.edit"),
    ("remove a medication photo from gallery", "gallery.photo.remove"), ("移出药物图库照片", "gallery.photo.remove"),
    ("delete a medication photo", "gallery.photo.delete"), ("删除药物照片", "gallery.photo.delete"),
    ("stop comparing a medication photo", "gallery.photo.retire"), ("停用药物照片比对", "gallery.photo.retire"),
    ("edit a medication PDF", "library.pdf.edit"), ("编辑药物PDF", "library.pdf.edit"),
    ("delete a medication PDF", "library.pdf.delete"), ("删除药物PDF", "library.pdf.delete"),
])
def test_bilingual_media_change_entry_only_prepares_a_patient_workflow(workflow, text, capability):
    result = workflow._request("POST", "/api/agent/workflows/messages", json={
        "text": text, "workspace_id": workflow.workspace_id, "client_turn_id": str(uuid4()),
    })
    assert result["workflow"] is not None and result["workflow"]["capability_id"] == capability
    assert result["workflow"]["state"] == "collecting"
    assert result["workflow"]["result_ref"] is None
    assert "plan has not been activated" not in result["reply"]["message"]
