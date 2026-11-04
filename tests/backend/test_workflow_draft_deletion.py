"""Actual owned deletion receipts and independent patient APIs; DEMO only."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Event
from uuid import UUID, uuid4

import pytest
from app.application.source_preview import SourcePreviewService
from app.domain.errors import ProviderUnavailableError
from PIL import Image

from .test_medication_evidence import Label
from .test_workflow_enrollment import message
from .test_workflow_medication_management import active_plan
from .test_workflow_originals import original_png


def draft(h):
    return h._request("POST", "/api/medications/drafts", json={"medication_name": "DEMO deletable workflow draft"})


def source_task(h, monkeypatch, name="DEMO deletable source", strength="500 mg"):
    provider = Label()
    provider.name = name
    provider.strength = strength
    monkeypatch.setattr(
        h.container.evidence_enrollment, "_preview", SourcePreviewService(provider=provider, ids=h.container.ids)
    )
    return h._request(
        "POST",
        f"/api/evidence/tasks/{uuid4()}/sources?source_kind=pharmacy_label",
        content=original_png(),
        headers={"Content-Type": "image/png", "X-Stage2-Consent": "true", "X-Demo-Only": "true"},
    )


def delete(h, kind, target, task, *, owner="A"):
    return h._request(
        "DELETE",
        f"/api/medications/unfinished/{kind}/{target}",
        owner=owner,
        json={"confirmed": True},
        headers={"X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(task["revision"])},
    )


def test_public_receipt_reads_the_actual_deletion_without_disclosing_private_cleanup_paths(workflow):
    h = workflow
    saved = draft(h)
    receipt_path = f"/api/medications/unfinished/draft/{saved['regimen_id']}/receipt"
    h._request("DELETE", f"/api/medications/unfinished/draft/{saved['regimen_id']}", json={"confirmed": True})
    assert h._request("GET", receipt_path) == {"deleted": True, "medication_deleted": True, "cleanup_pending": False}
    assert h.client.get(receipt_path, params={"client_id": "DEMO-workflow-B"}).status_code == 404


def test_a_delete_review_cannot_delete_another_owned_draft_or_another_patients_record(workflow):
    h = workflow
    first = draft(h)
    second = h._request("POST", "/api/medications/drafts", json={"medication_name": "DEMO other draft"})
    task = h.start("medication.draft.delete", {"kind": "draft", "target_id": first["regimen_id"]})
    prepared = h.event(task["task_id"], "prepare_confirmation")
    for target, owner in ((second["regimen_id"], "A"), (first["regimen_id"], "B")):
        response = h.client.request(
            "DELETE",
            f"/api/medications/unfinished/draft/{target}",
            params={"client_id": "DEMO-workflow-" + owner},
            json={"confirmed": True},
            headers={"X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(prepared["revision"])},
        )
        assert response.status_code in {404, 409, 422}
    assert len(h.snapshot()["regimens"]) == 2


@pytest.mark.parametrize("kind", ["draft", "source"])
def test_deletion_preparation_never_deletes_and_patient_replay_reads_the_same_real_receipt(workflow, monkeypatch, kind):
    h = workflow
    saved = draft(h) if kind == "draft" else source_task(h, monkeypatch)
    target = saved["regimen_id"] if kind == "draft" else saved["id"]
    version = saved.get("version", 1)
    task = h.start("medication.draft.delete", {"kind": kind, "target_id": target, "expected_version": version})
    prepared = h.event(task["task_id"], "prepare_confirmation")
    assert prepared["actions"][0]["component_key"] == "existing_draft_delete"
    assert len(h.snapshot()["medications"]) == 1
    result = delete(h, kind, target, prepared)
    assert result["deleted"] and delete(h, kind, target, prepared) == result
    completed = h.event(task["task_id"], "report_business_result")
    assert completed["state"] == "completed" and completed["visible_fields"]["deleted"] is True
    assert not h.snapshot()["medications"] and not h.snapshot()["regimens"]


def test_missing_record_without_a_deletion_receipt_remains_unknown(workflow):
    h = workflow
    saved = draft(h)
    task = h.start(
        "medication.draft.delete", {"kind": "draft", "target_id": saved["regimen_id"], "expected_version": 1}
    )
    h.event(task["task_id"], "prepare_confirmation")
    # Storage-boundary fault, not a successful call to the application deletion service.
    h.container.store.regimens.pop((h.owner_ids["A"], UUID(saved["regimen_id"])))
    current = h.view(task["task_id"])
    assert current["state"] == "outcome_unknown"
    assert current["visible_fields"].get("deleted") is not True
    paused = message(h, "pause", current)
    assert "unknown" in paused["reply"]["message"].lower() or "unconfirmed" in paused["reply"]["message"].lower()
    assert "nothing has been deleted" not in paused["reply"]["message"].lower()


def test_revoked_delete_and_an_unrelated_target_cannot_use_an_old_patient_button(workflow):
    h = workflow
    saved = draft(h)
    task = h.start("medication.draft.delete", {"kind": "draft", "target_id": saved["regimen_id"]})
    prepared = h.event(task["task_id"], "prepare_confirmation")
    h.event(task["task_id"], "cancel_save")
    response = h.client.request(
        "DELETE",
        f"/api/medications/unfinished/draft/{saved['regimen_id']}",
        params={"client_id": "DEMO-workflow-A"},
        json={"confirmed": True},
        headers={"X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(prepared["revision"])},
    )
    assert response.status_code in {409, 422} and len(h.snapshot()["medications"]) == 1


def test_active_history_is_never_deletable_through_the_workflow(workflow):
    h = workflow
    saved = active_plan(h)
    before = h.snapshot()
    response = h.client.post(
        "/api/agent/workflows/tasks",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "capability_id": "medication.draft.delete",
            "workspace_id": h.workspace_id,
            "client_event_id": str(uuid4()),
            "values": {"kind": "draft", "target_id": saved["regimen_id"], "expected_version": 1},
        },
    )
    assert response.status_code == 422
    assert h.snapshot()["regimens"] == before["regimens"] and h.snapshot()["sources"] == before["sources"]


def test_source_registration_with_an_activated_plan_is_not_offered_as_a_deletable_draft(workflow, monkeypatch):
    h = workflow
    saved = source_task(h, monkeypatch)
    prepared = h._request(
        "POST",
        f"/api/evidence/tasks/{saved['id']}/review",
        json={
            "patient_reviewed": True,
            "draft": {
                "medication_name": saved["product"]["name"],
                "dose_amount": 1,
                "dose_unit": "tablet",
                "frequency_rule": {"kind": "daily", "local_times": ["08:00"]},
            },
        },
    )
    session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})
    regimen = prepared["draft_regimen_id"]
    challenge = h._request(
        "POST", f"/api/medications/drafts/{regimen}/challenge", params={"session_id": session["session_id"]}, json={}
    )
    h._request(
        "POST",
        "/api/medications/activate",
        json={
            "regimen_id": regimen,
            **{key: challenge[key] for key in ("challenge_id", "session_id", "session_state", "session_state_version")},
        },
    )
    response = h.client.post(
        "/api/agent/workflows/tasks",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "capability_id": "medication.draft.delete",
            "workspace_id": h.workspace_id,
            "client_event_id": str(uuid4()),
            "values": {"kind": "source", "target_id": saved["id"]},
        },
    )
    assert response.status_code == 422
    assert h.container.enrollment.get_regimen(h.owner_ids["A"], UUID(regimen)).state.value == "active"


def test_no_save_delete_preview_cannot_prepare_or_execute_the_patient_write(workflow):
    h = workflow
    saved = draft(h)
    values = {"kind": "draft", "target_id": saved["regimen_id"], "expected_version": 1}
    task = h.start("medication.draft.delete", values, save=False)
    response = h.client.post(
        f"/api/agent/workflows/tasks/{task['task_id']}/events",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "event_id": str(uuid4()),
            "expected_revision": task["revision"],
            "kind": "prepare_confirmation",
            "values": {},
            "ephemeral": {"capability_id": task["capability_id"], "fields": values},
        },
    )
    assert response.status_code == 422
    attempt = h.client.request(
        "DELETE",
        f"/api/medications/unfinished/draft/{saved['regimen_id']}",
        params={"client_id": "DEMO-workflow-A"},
        json={"confirmed": True},
        headers={"X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(task["revision"])},
    )
    assert attempt.status_code in {404, 409, 422} and len(h.snapshot()["medications"]) == 1


def test_valid_long_source_names_remain_selectable_and_full_identity_is_shown_for_review(workflow, monkeypatch):
    h = workflow
    name = "DEMO" + "a" * 156
    saved = source_task(h, monkeypatch, name=name, strength="s" * 100)
    task = h.start("medication.draft.delete")
    assert any(
        option["value"] == f"source:{saved['id']}:{saved['version']}"
        for action in task["actions"]
        for option in action.get("options", [])
    )
    selected = h.event(
        task["task_id"],
        "provide_fields",
        {"kind": "source", "target_id": saved["id"], "expected_version": saved["version"]},
    )
    assert selected["visible_fields"]["target_name"] == name + " " + "s" * 100


def test_failed_physical_cleanup_uses_the_same_deletion_receipt_until_retry(workflow, monkeypatch):
    h = workflow
    saved = source_task(h, monkeypatch)
    task = h.start(
        "medication.draft.delete", {"kind": "source", "target_id": saved["id"], "expected_version": saved["version"]}
    )
    prepared = h.event(task["task_id"], "prepare_confirmation")
    storage = h.container.evidence_enrollment._storage
    remove = storage.delete
    monkeypatch.setattr(
        storage, "delete", lambda _path: (_ for _ in ()).throw(ProviderUnavailableError("DEMO cleanup unavailable"))
    )
    assert delete(h, "source", saved["id"], prepared)["cleanup_pending"] is True
    pending = h.event(task["task_id"], "report_business_result")
    assert pending["state"] != "completed" and pending["visible_fields"]["cleanup_pending"] is True
    monkeypatch.setattr(storage, "delete", remove)
    assert delete(h, "source", saved["id"], pending)["cleanup_pending"] is False
    assert h.event(task["task_id"], "report_business_result")["state"] == "completed"


def test_a_new_sibling_draft_invalidates_the_old_delete_summary(workflow):
    h = workflow
    saved = draft(h)
    task = h.start(
        "medication.draft.delete", {"kind": "draft", "target_id": saved["regimen_id"], "expected_version": 1}
    )
    prepared = h.event(task["task_id"], "prepare_confirmation")
    newer = h._request(
        "POST",
        f"/api/medications/drafts?medication_id={saved['medication_id']}",
        json={"medication_name": "DEMO deletable workflow draft", "dose_amount": 2},
    )
    response = h.client.request(
        "DELETE",
        f"/api/medications/unfinished/draft/{saved['regimen_id']}",
        params={"client_id": "DEMO-workflow-A"},
        json={"confirmed": True},
        headers={"X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(prepared["revision"])},
    )
    assert response.status_code == 409
    assert len(h.snapshot()["regimens"]) == 2 and newer["regimen_id"] != saved["regimen_id"]
    fresh = h.event(task["task_id"], "provide_fields", {})
    assert fresh["visible_fields"].get("affected_plan_count") == 2


def test_changed_source_version_is_readable_and_requires_a_new_patient_review(workflow, monkeypatch):
    h = workflow
    saved = source_task(h, monkeypatch)
    task = h.start(
        "medication.draft.delete", {"kind": "source", "target_id": saved["id"], "expected_version": saved["version"]}
    )
    h.event(task["task_id"], "prepare_confirmation")
    with Image.open(BytesIO(original_png())) as image:
        image.putpixel((20, 20), (20, 80, 120))
        output = BytesIO()
        image.save(output, format="PNG")
    updated = h._request(
        "POST",
        f"/api/evidence/tasks/{saved['id']}/sources?source_kind=package",
        content=output.getvalue(),
        headers={"Content-Type": "image/png", "X-Stage2-Consent": "true", "X-Demo-Only": "true"},
    )
    assert updated["version"] == saved["version"] + 1
    changed = h.view(task["task_id"])
    assert changed["state"] == "failed_recoverable"
    fresh = h.event(task["task_id"], "provide_fields", {})
    assert fresh["state"] == "ready_for_review" and fresh["input_fields"]["expected_version"] == saved["version"] + 1


@pytest.mark.parametrize("text", ["删除药物草稿", "delete a medication draft"])
def test_chat_delete_intent_offers_real_drafts_without_deleting_them(workflow, text):
    h = workflow
    saved = draft(h)
    result = message(h, text)
    assert result["workflow"] is not None and result["workflow"]["capability_id"] == "medication.draft.delete"
    assert any(
        option["value"] == f"draft:{saved['regimen_id']}:1"
        for action in result["workflow"]["actions"]
        for option in action.get("options", [])
    )
    assert len(h.snapshot()["medications"]) == 1


def test_patient_delete_holds_the_clinical_fence_until_the_existing_writer_returns(workflow, monkeypatch):
    h = workflow
    saved = draft(h)
    task = h.start("medication.draft.delete", {"target_id": saved["regimen_id"]})
    prepared = h.event(task["task_id"], "prepare_confirmation")
    entered, release, writer_started, writer_done = Event(), Event(), Event(), Event()
    repository = h.container.draft_deletion._repository
    original = repository.delete

    def blocked(*args):
        entered.set()
        if not release.wait(5):
            raise AssertionError("DEMO blocked deletion was not released")
        return original(*args)

    monkeypatch.setattr(repository, "delete", blocked)

    def another_write():
        writer_started.set()
        try:
            return h._request(
                "POST", "/api/medications/drafts", json={"medication_name": "DEMO concurrent independent draft"}
            )
        finally:
            writer_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        removing = pool.submit(delete, h, "draft", saved["regimen_id"], prepared)
        try:
            assert entered.wait(5)
            writing = pool.submit(another_write)
            assert writer_started.wait(5) and not writer_done.wait(0.1)
        finally:
            release.set()
        assert removing.result(timeout=5)["deleted"] is True
        assert writing.result(timeout=5)["medication_id"] != saved["medication_id"]
    assert len(h.snapshot()["medications"]) == 1
