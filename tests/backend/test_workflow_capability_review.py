"""DEMO_ONLY regressions for the independent whole-P06 review findings."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from .test_workflow_care import fields, prepared, save
from .test_workflow_media import seed_media
from .test_workflow_media_lifecycle import fields as media_fields


def unrelated(h):
    previous = h.workspace_id
    h.workspace_id = str(uuid4())
    try:
        return h.start("medication.enroll", {"method": "manual", "medication_name": "DEMO unrelated retained"})
    finally:
        h.workspace_id = previous


@pytest.mark.parametrize("change", ["edit", "delete"])
@pytest.mark.parametrize("completed", [False, True])
@pytest.mark.parametrize("capability", ["observation.add", "observation.edit"])
def test_later_observation_changes_preserve_historical_success_and_unrelated_drafts(
        workflow, change, completed, capability):
    h = workflow
    values = fields(h, "observation.add")
    if capability == "observation.edit":
        old = h._request("PUT", "/api/me/health-observations", json={
            "id": str(uuid4()), **values, "confirmed": True})
        values = {**values, "observation_id": old["id"]}
    task = prepared(h, capability, values)
    original = save(h, task)
    if completed:
        h.event(task["task_id"], "report_business_result")
    draft = unrelated(h)
    if change == "edit":
        h._request("PUT", "/api/me/health-observations", json={
            **task["visible_fields"]["care_review"]["payload"], "description": "DEMO later native correction",
            "confirmed": True})
    else:
        h._request("DELETE", "/api/me/health-observations/" + original["id"])
    view = h.view(task["task_id"])
    assert view["visible_fields"]["historical_result"] is True
    assert view["visible_fields"]["record_available"] == (change == "edit")
    assert view["result_ref"]["id"] == (original["id"] if completed else task["result_ref"]["id"])
    if not completed:
        assert h.event(task["task_id"], "report_business_result")["state"] == "completed"
    rows = h._request("GET", "/api/agent/workflows/tasks")
    assert draft["task_id"] in {row["task_id"] for row in rows}


@pytest.mark.parametrize("capability", ["library.pdf.edit", "gallery.photo.edit"])
def test_stale_unprepared_media_selection_is_readable_and_explicitly_reselectable(workflow, capability):
    h = workflow
    med, photo, pdf = seed_media(h)
    values = media_fields(capability, med, photo, pdf)
    task = h.start(capability, values)
    draft = unrelated(h)
    if capability.startswith("library."):
        h._request("PATCH", f"/api/evidence/library-files/{pdf['id']}", params={"confirmed": "true"},
                   json={"expected_version": 1, "title": "DEMO later native title", "category": "other",
                         "description": "DEMO changed"})
    else:
        h._request("PATCH", f"/api/evidence/images/{photo['id']}", params={"confirmed": "true"},
                   json={"action": "edit", "expected_version": 1, "image_kind": "package",
                         "source_description": "DEMO later native photo"})
    stale = h.view(task["task_id"])
    assert stale["state"] == "failed_recoverable" and stale["input_fields"]["expected_version"] == 1
    assert stale["actions"][0]["kind"] == "choice" and stale["result_ref"] is None
    assert draft["task_id"] in {row["task_id"] for row in h._request("GET", "/api/agent/workflows/tasks")}
    updated = h.event(task["task_id"], "provide_fields", {"expected_version": 2})
    assert updated["state"] == "ready_for_review" and updated["input_fields"]["expected_version"] == 2


def test_followup_review_projects_owned_proposed_association_and_explicit_removal(workflow):
    from .test_workflow_medication_management import active_plan

    h = workflow
    med = active_plan(h)
    task = prepared(h, "followup.add", {"title": "DEMO linked followup", "regimen_id": med["regimen_id"],
        "due_at": (h.clock.now() + timedelta(days=2)).isoformat()})
    assert task["visible_fields"]["association_label"] == "DEMO-workflow-medicine · v1"
    assert task["visible_fields"]["association_state"] == "linked"
    saved = save(h, task)
    edit = prepared(h, "followup.edit", {"task_id": saved["id"], "expected_version": 1,
        "title": "DEMO updated title", "category": "monitoring", "clear_plan": True})
    assert edit["visible_fields"]["association_state"] == "removed"
    assert edit["visible_fields"]["proposal"]["task_update"]["title"] == "DEMO updated title"


def test_stale_unprepared_followup_is_readable_and_offers_current_selection(workflow):
    h = workflow
    old = h._request("POST", "/api/me/care-tasks", json={"id": str(uuid4()), "title": "DEMO old task",
        "category": "monitoring", "due_at": (h.clock.now() + timedelta(days=2)).isoformat(), "confirmed": True})
    task = h.start("followup.edit", {"task_id": old["id"], "expected_version": 1, "title": "DEMO proposed"})
    h._request("POST", "/api/me/care-tasks/" + old["id"], json={"id": str(uuid4()), "expected_version": 1,
        "status": "open", "title": "DEMO changed elsewhere", "confirmed": True})
    current = h.view(task["task_id"])
    assert current["state"] == "failed_recoverable" and current["input_fields"]["title"] == "DEMO proposed"
    assert current["actions"][0]["action_id"] == "care.task"
    assert current["actions"][0]["options"][0]["value"] == old["id"] + ":2"


def test_source_review_finishes_only_after_actual_independent_activation(workflow, monkeypatch):
    from .test_workflow_source_transport import source_review
    from .test_workflow_sources import inputs, provider

    h = workflow
    provider(h, monkeypatch)
    target = h.container.evidence_enrollment.attach(**inputs(h))
    task = h.start("medication.source.review", {"source_task_id": str(target.id), "expected_version": target.version})
    task = h.event(task["task_id"], "prepare_confirmation")
    from app.contracts.assistant_workflows import WorkflowContext
    preferences = h.container.preferences.get(h.owner_ids["A"])
    context = WorkflowContext(owner=h.owner_ids["A"], task_id=UUID(task["task_id"]),
        revision=task["revision"], capability_id=task["capability_id"], save_mode=task["save_mode"],
        language=preferences.preferred_language, timezone=preferences.timezone)
    response = source_review(h, context, target)
    assert response.status_code == 200, response.text
    captured = h.event(task["task_id"], "report_business_result")
    assert captured["state"] == "awaiting_confirmation"
    regimen_id = captured["result_ref"]["id"]
    session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})
    headers = {"X-Assistant-Task": captured["task_id"], "X-Assistant-Revision": str(captured["revision"])}
    challenge = h._request("POST", f"/api/medications/drafts/{regimen_id}/challenge",
                          params={"session_id": session["session_id"]}, headers=headers, json={})
    h._request("POST", "/api/medications/activate", headers=headers, json={"regimen_id": regimen_id,
        **{key: challenge[key] for key in ("challenge_id", "session_id", "session_state", "session_state_version")}})
    assert h.event(task["task_id"], "report_business_result")["state"] == "completed"
