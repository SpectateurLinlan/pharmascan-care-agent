"""DEMO_ONLY real memory media services; no provider, database or cloud calls."""

from pathlib import Path
from uuid import uuid4

import pytest

from .test_workflow_medication_management import active_plan

READ_IDS = ("gallery.list", "gallery.photo.view", "library.list", "library.pdf.view", "library.pdf.download")
PDF = b"%PDF-1.7\n1 0 obj<</Type/Catalog>>endobj\n%%EOF"


def seed_media(h):
    med = active_plan(h)
    medication_id = med["medication_id"]
    photo = h._request(
        "POST",
        f"/api/evidence/gallery/{medication_id}/images",
        params={"image_kind": "package", "source_description": "DEMO patient package", "reviewed": "true"},
        content=Path(__file__).with_name("fixtures").joinpath("DEMO_workflow_photo.png").read_bytes(),
        headers={"Content-Type": "image/png", "X-Stage2-Consent": "true", "X-Demo-Only": "true"},
    )["photo"]
    pdf = h._request(
        "POST",
        f"/api/evidence/gallery/{medication_id}/pdfs",
        params={"filename": "DEMO_original.pdf", "category": "prescription", "description": "DEMO unextracted PDF"},
        content=PDF,
        headers={"Content-Type": "application/pdf"},
    )["file"]
    return medication_id, photo, pdf


def values(capability, medication_id, photo, pdf):
    result = {} if capability == "gallery.list" else {"medication_id": medication_id}
    if capability == "gallery.photo.view":
        result["image_id"] = photo["id"]
    if capability in {"library.pdf.view", "library.pdf.download"}:
        result["file_id"] = pdf["id"]
    return result


@pytest.mark.parametrize("capability", READ_IDS)
def test_media_read_entry_uses_actual_owned_records_without_binary_or_provider_reads(workflow, monkeypatch, capability):
    h = workflow
    medication_id, photo, pdf = seed_media(h)

    def forbidden(*args, **kwargs):
        raise AssertionError("Task preparation must not read binary bytes or run a provider")

    monkeypatch.setattr(h.container.gallery, "image", forbidden)
    monkeypatch.setattr(h.container.library_files, "content", forbidden)
    task = h.start(capability, values(capability, medication_id, photo, pdf))
    assert task["state"] == "collecting"
    assert not task["result_ref"]
    visible = task["visible_fields"]
    if capability == "gallery.list":
        assert visible["records"][0]["medication_id"] == medication_id
        assert visible["records"][0]["photo_count"] == 1
    elif capability == "gallery.photo.view":
        assert visible["photo"]["id"] == photo["id"]
        assert visible["photo"]["eligibility"] != "eligible"
    elif capability == "library.list":
        assert visible["records"][0]["id"] == pdf["id"]
    else:
        assert visible["file"]["id"] == pdf["id"]
        assert visible["file"]["byte_size"] == len(PDF)
    assert visible.get("extracted_instructions") is None
    for hidden in ("storage_path", "object_ref", "patient_id", "checksum", "signed_url", "extraction_evidence"):
        assert hidden not in str(visible)
    assert not h.source_calls and not h.knowledge_requests
    assert h.view(task["task_id"])["visible_fields"] == visible


@pytest.mark.parametrize("capability", READ_IDS[1:])
def test_media_task_cannot_read_another_patients_medication(workflow, capability):
    h = workflow
    medication_id, photo, pdf = seed_media(h)
    response = h.client.post(
        "/api/agent/workflows/tasks",
        params={"client_id": "DEMO-workflow-B"},
        json={"capability_id": capability, "workspace_id": str(uuid4()), "save_mode": "allowed",
              "client_event_id": str(uuid4()), "values": values(capability, medication_id, photo, pdf)},
    )
    assert response.status_code in {403, 404}


@pytest.mark.parametrize("capability,key", [("gallery.photo.view", "image_id"), ("library.pdf.view", "file_id")])
def test_media_selection_must_belong_to_the_selected_medication(workflow, capability, key):
    h = workflow
    medication_id, photo, pdf = seed_media(h)
    other = active_plan(h, name="DEMO different media product")
    fields = values(capability, medication_id, photo, pdf)
    fields["medication_id"] = other["medication_id"]
    response = h.client.post(
        "/api/agent/workflows/tasks",
        params={"client_id": "DEMO-workflow-A"},
        json={"capability_id": capability, "workspace_id": str(uuid4()), "save_mode": "allowed",
              "client_event_id": str(uuid4()), "values": fields},
    )
    assert response.status_code == 404, (key, response.text)


def test_gallery_empty_state_and_partial_media_selections_are_real_not_fake_completion(workflow):
    h = workflow
    empty = h.start("gallery.list")
    assert empty["visible_fields"]["records"] == []
    assert empty["state"] == "collecting"
    medication_id, photo, pdf = seed_media(h)
    for capability in READ_IDS[1:]:
        task = h.start(capability)
        assert "medication_id" in task["missing_fields"]
        assert task["actions"][0]["action_id"] == "media.medication"
        selected = h.event(task["task_id"], "provide_fields", {"medication_id": medication_id})
        if capability == "gallery.photo.view":
            assert selected["actions"][0]["options"][0]["value"] == photo["id"]
        elif capability != "library.list":
            assert selected["actions"][0]["options"][0]["value"] == pdf["id"]


def test_media_no_save_keeps_no_body_and_actual_pdf_download_preserves_bytes(workflow):
    h = workflow
    medication_id, photo, pdf = seed_media(h)
    before = len(h.snapshot()["tasks"])
    task = h.start("library.pdf.download", values("library.pdf.download", medication_id, photo, pdf), save=False)
    assert len(h.snapshot()["tasks"]) == before
    assert task["save_mode"] == "ephemeral"
    action = next(row for row in task["actions"] if row["kind"] == "download")
    assert action["owned_ref"]["id"] == pdf["id"]
    result = h.client.get(f"/api/evidence/library-files/{pdf['id']}",
                          params={"client_id": "DEMO-workflow-A", "disposition": "attachment"})
    assert result.content == PDF
    assert result.headers["cache-control"] == "no-store"
    denied = h.client.get(f"/api/evidence/library-files/{pdf['id']}", params={"client_id": "DEMO-workflow-B"})
    assert denied.status_code == 404


def test_all_fifteen_t4_media_capabilities_are_available_in_opt_in_memory(workflow):
    catalog = workflow._request("GET", "/api/agent/workflows/capabilities")["capabilities"]
    by_id = {row["id"]: row for row in catalog}
    for capability in READ_IDS:
        assert by_id[capability]["available"] is True
    for capability in ("gallery.photo.add", "gallery.photo.edit", "gallery.photo.remove",
                       "gallery.photo.delete", "gallery.photo.retire",
                       "library.pdf.add", "library.pdf.edit", "library.pdf.delete", "image.compare", "source.preview"):
        assert by_id[capability]["available"] is True


@pytest.mark.parametrize("text,capability", [
    ("show my photo gallery", "gallery.list"), ("查看我的药物图库", "gallery.list"),
    ("view a medication photo", "gallery.photo.view"), ("查看药物照片", "gallery.photo.view"),
    ("show medication PDFs", "library.list"), ("查看药物PDF", "library.list"),
    ("preview a medication PDF", "library.pdf.view"), ("预览药物PDF", "library.pdf.view"),
    ("download a medication PDF", "library.pdf.download"), ("下载药物PDF", "library.pdf.download"),
])
def test_actual_english_and_chinese_messages_start_the_selected_media_query(workflow, text, capability):
    reply = workflow._request("POST", "/api/agent/workflows/messages", json={
        "text": text, "workspace_id": workflow.workspace_id, "client_turn_id": str(uuid4()),
    })
    assert reply["workflow"] is not None
    assert reply["workflow"]["capability_id"] == capability
    assert reply["reply"]["mode"] == "workflow"


def test_pdf_paging_and_deleted_target_refresh_never_reuse_stale_metadata(workflow):
    h = workflow
    medication_id, photo, pdf = seed_media(h)
    for index in range(10):
        h._request("POST", f"/api/evidence/gallery/{medication_id}/pdfs",
                   params={"filename": f"DEMO_{index}.pdf"},
                   content=PDF.replace(b"Catalog", f"Catalog{index}".encode()),
                   headers={"Content-Type": "application/pdf"})
    task = h.start("library.list", {"medication_id": medication_id})
    first = task["visible_fields"]
    assert (len(first["records"]), first["total"], first["page_count"]) == (10, 11, 2)
    second = h.event(task["task_id"], "provide_fields", {"page": 1})
    assert len(second["visible_fields"]["records"]) == 1
    assert {row["id"] for row in first["records"]}.isdisjoint(row["id"] for row in second["visible_fields"]["records"])
    reset = h.event(task["task_id"], "provide_fields", {"page": 100})
    assert reset["visible_fields"]["page"] == 0
    selected = h.start("library.pdf.view", values("library.pdf.view", medication_id, photo, pdf))
    h._request("DELETE", f"/api/evidence/library-files/{pdf['id']}", params={"confirmed": "true"})
    refreshed = h.view(selected["task_id"])
    assert not refreshed["visible_fields"].get("file")


@pytest.mark.parametrize("extra", [{"confirmed": True}, {"storage_path": "DEMO-private"}, {"page": True},
                                   {"image_id": str(uuid4())}])
def test_pdf_query_rejects_write_authority_paths_and_inapplicable_fields(workflow, extra):
    response = workflow.client.post("/api/agent/workflows/tasks", params={"client_id": "DEMO-workflow-A"}, json={
        "capability_id": "library.pdf.view", "workspace_id": workflow.workspace_id,
        "client_event_id": str(uuid4()), "save_mode": "allowed", "values": extra,
    })
    assert response.status_code == 422


@pytest.mark.parametrize("text,expected", [
    ("show my photo gallery", "saved medication photos"),
    ("查看我的药物图库", "已保存的药物照片"),
    ("preview a medication PDF", "only views saved files"),
    ("预览药物PDF", "只查看已保存文件"),
])
def test_media_reply_describes_files_instead_of_claiming_a_medication_plan_review(workflow, text, expected):
    from app.contracts.preferences import PreferenceUpdate

    workflow.container.preferences.save(workflow.owner_ids["A"], PreferenceUpdate(
        preferred_language="en" if text.isascii() else "zh",
    ))
    result = workflow._request("POST", "/api/agent/workflows/messages", json={
        "text": text, "workspace_id": workflow.workspace_id, "client_turn_id": str(uuid4()),
    })
    assert expected in result["reply"]["message"]
    assert "plan has not been activated" not in result["reply"]["message"]
    assert "尚未启用用药计划" not in result["reply"]["message"]
