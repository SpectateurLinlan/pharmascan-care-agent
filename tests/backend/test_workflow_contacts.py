"""DEMO_ONLY independent native contact CRUD; no invitations or record sharing."""

from uuid import uuid4

import pytest

from .test_workflow_records import clinical


def details():
    return {"name": "DEMO care contact", "relationship": "DEMO relative", "contact_type": "email",
            "contact_value": "DEMO.Contact@example.invalid", "storage_consent": True}


def prepared(h, capability="caregiver.add", row=None):
    values = details() if capability == "caregiver.add" else {
        "contact_id": row["id"], "previous": {key: row[key] for key in details()},
        "previous_updated_at": row["updated_at"],
        **({**details(), "name": "DEMO updated contact"} if capability == "caregiver.edit" else {})}
    task = h.start(capability, values)
    return h.event(task["task_id"], "prepare_confirmation")


def save(h, task, *, owner="A", payload=None, confirmed=True):
    review = task["visible_fields"]["settings_review"]
    method = {"caregiver.add": "POST", "caregiver.edit": "PUT", "caregiver.delete": "DELETE"}[task["capability_id"]]
    path = "/api/me/caregivers" + (f"/{review['target_id']}" if method != "POST" else "")
    return h.client.request(method, path, params={"client_id": "DEMO-workflow-" + owner},
        **({"json": payload if payload is not None else review["payload"]} if method != "DELETE" else {}),
        headers={"X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(task["revision"]),
                 "X-Patient-Confirmed": str(confirmed).lower()})


def test_contact_crud_only_saves_after_independent_confirmation_and_retains_native_limits(workflow):
    h = workflow
    before = clinical(h)
    task = prepared(h)
    assert h.container.caregivers.list(h.owner_ids["A"]) == []
    result = save(h, task)
    assert result.status_code == 200, result.text
    row = result.json()
    assert row["contact_value"] == "demo.contact@example.invalid"
    assert row["notifications_enabled"] is False and row["sharing_enabled"] is False
    assert row["verification_status"] == "pending"
    assert save(h, task).json() == row
    assert h.event(task["task_id"], "report_business_result")["state"] == "completed"
    query = h.start("caregiver.list")
    assert query["visible_fields"]["contacts"][0]["name"] == row["name"]
    assert "patient_id" not in str(query["visible_fields"])
    task = prepared(h, "caregiver.edit", row)
    changed = save(h, task)
    assert changed.status_code == 200, changed.text
    assert changed.json()["name"] == "DEMO updated contact"
    h.event(task["task_id"], "report_business_result")
    task = prepared(h, "caregiver.delete", changed.json())
    assert save(h, task).json() == {"deleted": True}
    assert save(h, task).json() == {"deleted": True}
    assert h.event(task["task_id"], "report_business_result")["state"] == "completed"
    assert not h.container.caregivers.list(h.owner_ids["A"]) and clinical(h) == before


@pytest.mark.parametrize("consent", [False, None])
def test_contact_pii_without_storage_consent_is_rejected_before_draft_persistence(workflow, consent):
    h = workflow
    response = h.client.post("/api/agent/workflows/tasks", params={"client_id": "DEMO-workflow-A"}, json={
        "capability_id": "caregiver.add", "workspace_id": h.workspace_id, "client_event_id": str(uuid4()),
        "save_mode": "allowed", "values": {**details(), "storage_consent": consent}})
    assert response.status_code == 422
    assert "DEMO care contact" not in str(h.snapshot())


@pytest.mark.parametrize("change", ["owner", "payload", "confirm", "paused", "revoked"])
def test_contact_native_write_refuses_invalid_confirmation_or_authority(workflow, change):
    h = workflow
    task = prepared(h)
    options = {"owner": "B"} if change == "owner" else {"confirmed": False} if change == "confirm" else {}
    if change == "payload":
        options["payload"] = {**task["visible_fields"]["settings_review"]["payload"], "name": "DEMO injected"}
    if change in {"paused", "revoked"}:
        h.event(task["task_id"], "pause" if change == "paused" else "cancel_save")
    result = save(h, task, **options)
    assert result.status_code in {404, 409, 422}, result.text
    assert not h.container.caregivers.list(h.owner_ids["A"])


def test_stale_contact_delete_cannot_remove_a_later_native_edit(workflow):
    h = workflow
    row = h._request("POST", "/api/me/caregivers", json={"id": str(uuid4()), **details()})
    task = prepared(h, "caregiver.delete", row)
    changed = h._request("PUT", f"/api/me/caregivers/{row['id']}", json={**details(), "name": "DEMO later edit"})
    assert save(h, task).status_code == 409
    assert h.container.caregivers.list(h.owner_ids["A"])[0].name == changed["name"]


def test_contact_creation_failure_retains_fields_and_checks_before_correcting_duplicate(workflow):
    h = workflow
    original = h._request("POST", "/api/me/caregivers", json={"id": str(uuid4()), **details()})
    task = prepared(h)
    assert save(h, task).status_code == 422
    assert h.view(task["task_id"])["input_fields"]["name"] == "DEMO care contact"
    h.event(task["task_id"], "report_business_result")
    h.event(task["task_id"], "provide_fields", {"contact_value": "demo.new@example.invalid"})
    task = h.event(task["task_id"], "prepare_confirmation")
    assert save(h, task).status_code == 200
    assert len(h.container.caregivers.list(h.owner_ids["A"])) == 2
    assert any(str(row.id) == original["id"] for row in h.container.caregivers.list(h.owner_ids["A"]))


def test_contact_delete_without_a_success_receipt_is_uncertain_and_never_repeated(workflow, monkeypatch):
    from app.domain.errors import ProviderUnavailableError

    h = workflow
    row = h._request("POST", "/api/me/caregivers", json={"id": str(uuid4()), **details()})
    task = prepared(h, "caregiver.delete", row)
    adapter = h.container.assistant_workflows._adapters["caregiver.delete"]
    complete = adapter.actions.complete

    def fail(context, receipt):
        if receipt.safe_reason == "settings_saved":
            raise ProviderUnavailableError("DEMO missing native-success receipt")
        return complete(context, receipt)

    monkeypatch.setattr(adapter.actions, "complete", fail)
    assert save(h, task).status_code == 503
    assert not h.container.caregivers.list(h.owner_ids["A"])
    assert save(h, task).status_code == 409
    checked = h.event(task["task_id"], "report_business_result")
    assert checked["state"] != "completed"
    with pytest.raises(AssertionError, match="409"):
        h.event(task["task_id"], "provide_fields", {})


def test_no_save_contact_draft_retains_no_pii_in_saved_task_or_controls(workflow):
    h = workflow
    task = h.start("caregiver.add", details(), save=False)
    snapshot = h.snapshot()
    assert not snapshot["tasks"] and "DEMO care contact" not in str(snapshot["workflow_controls"])
    assert h.view(task["task_id"])["input_fields"] is None
    assert not h.container.caregivers.list(h.owner_ids["A"])
