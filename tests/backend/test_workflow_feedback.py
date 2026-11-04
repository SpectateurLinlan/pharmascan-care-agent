"""DEMO_ONLY feedback is independently confirmed, stored once and actually read back."""

from uuid import UUID, uuid4

import pytest


def prepared(h):
    task = h.start("feedback.submit", {"category": "issue", "message": "DEMO reproducible application issue"})
    return h.event(task["task_id"], "prepare_confirmation")


def save(h, task, *, confirmed=True, owner="A", payload=None):
    return h.client.post("/api/feedback", params={"client_id": "DEMO-workflow-" + owner},
        json=payload or task["visible_fields"]["settings_review"]["payload"], headers={
            "X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(task["revision"]),
            "X-Patient-Confirmed": str(confirmed).lower()})


def test_feedback_is_pure_until_confirmation_and_returns_actual_owned_readback(workflow):
    h = workflow
    task = prepared(h)
    target = task["visible_fields"]["settings_review"]["target_id"]
    assert not h.container.feedback.get(h.owner_ids["A"], UUID(target))
    assert save(h, task, confirmed=False).status_code in {409, 422}
    result = save(h, task)
    assert result.status_code == 200 and result.json()["status"] == "received", result.text
    assert save(h, task).json() == result.json()
    done = h.event(task["task_id"], "report_business_result")
    assert done["state"] == "completed"
    assert done["visible_fields"]["current_feedback"]["message"] == "DEMO reproducible application issue"
    assert "patient_id" not in str(done["visible_fields"])


@pytest.mark.parametrize("change", ["owner", "body", "paused", "revoked"])
def test_feedback_native_binding_refuses_wrong_or_changed_review(workflow, change):
    h = workflow
    task = prepared(h)
    if change in {"paused", "revoked"}:
        h.event(task["task_id"], "pause" if change == "paused" else "cancel_save")
    payload = {**task["visible_fields"]["settings_review"]["payload"], "message": "DEMO different message"} \
        if change == "body" else None
    result = save(h, task, owner="B" if change == "owner" else "A", payload=payload)
    assert result.status_code in {404, 409, 422}


def test_feedback_workflow_cannot_accept_caller_supplied_native_id(workflow):
    h = workflow
    response = h.client.post("/api/agent/workflows/tasks", params={"client_id": "DEMO-workflow-A"}, json={
        "capability_id": "feedback.submit", "workspace_id": h.workspace_id, "client_event_id": str(uuid4()),
        "save_mode": "allowed", "values": {"id": str(uuid4()), "category": "issue", "message": "DEMO feedback"}})
    assert response.status_code == 422


def test_native_failure_retains_feedback_then_checked_edit_gets_new_independent_review(workflow, monkeypatch):
    from app.domain.errors import ProviderUnavailableError

    h = workflow
    task = prepared(h)
    original = h.container.feedback.submit
    monkeypatch.setattr(h.container.feedback, "submit", lambda *args: (_ for _ in ()).throw(
        ProviderUnavailableError("DEMO failure before persistence")))
    assert save(h, task).status_code == 503
    assert h.view(task["task_id"])["input_fields"]["message"] == "DEMO reproducible application issue"
    assert save(h, task).status_code == 409
    checked = h.event(task["task_id"], "report_business_result")
    edited = h.event(task["task_id"], "provide_fields",
                     {"category": "suggestion", "message": "DEMO corrected feedback"})
    reviewed = h.event(task["task_id"], "prepare_confirmation")
    assert checked["state"] == "awaiting_confirmation" and edited["state"] == "ready_for_review"
    assert reviewed["result_ref"]["id"] != task["result_ref"]["id"]
    monkeypatch.setattr(h.container.feedback, "submit", original)
    assert save(h, reviewed).status_code == 200


def test_uncertain_feedback_persisted_without_receipt_cannot_be_resubmitted(workflow, monkeypatch):
    from app.domain.errors import ProviderUnavailableError

    h = workflow
    task = prepared(h)
    original = h.container.feedback.submit
    calls = []
    def uncertain(*args):
        calls.append(original(*args))
        raise ProviderUnavailableError("DEMO result lost before receipt")
    monkeypatch.setattr(h.container.feedback, "submit", uncertain)
    assert save(h, task).status_code == 503
    checked = h.event(task["task_id"], "report_business_result")
    assert checked["state"] == "failed_recoverable"
    assert save(h, checked, payload=task["visible_fields"]["settings_review"]["payload"]).status_code == 409
    assert len(calls) == 1
