"""Owned medication-management behavior through actual DEMO services."""

from uuid import uuid4

import pytest

from .test_workflow_enrollment import message


def active_plan(h, name=None):
    if name is None:
        saved = h.seed_reviewed_medication()
    else:
        session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})
        saved = h._request(
            "POST",
            "/api/medications/drafts",
            json={
                "medication_name": name,
                "dose_amount": 1,
                "dose_unit": "tablet",
                "frequency_kind": "daily",
                "frequency_local_times": ["20:00"],
            },
        )
        h._request("POST", f"/api/medications/drafts/{saved['source_id']}/review", json={"field_ids": None})
        saved = {**saved, "session_id": session["session_id"]}
    challenge = h._request(
        "POST",
        f"/api/medications/drafts/{saved['regimen_id']}/challenge",
        params={"session_id": saved["session_id"]},
        json={},
    )
    h._request(
        "POST",
        "/api/medications/activate",
        json={
            "regimen_id": saved["regimen_id"],
            **{key: challenge[key] for key in ("challenge_id", "session_id", "session_state", "session_state_version")},
        },
    )
    return saved


def test_stopping_a_plan_requires_the_patient_api_and_preserves_source_and_history(workflow):
    h = workflow
    saved = active_plan(h)
    before = h.snapshot()
    task = h.start("medication.plan.end", {"regimen_id": saved["regimen_id"], "expected_version": 1})
    prepared = h.event(task["task_id"], "prepare_confirmation")
    assert prepared["actions"][0]["component_key"] == "existing_plan_end"
    assert h.snapshot()["regimens"][0]["state"] == "active"
    actual = h._request(
        "POST",
        f"/api/medications/{saved['regimen_id']}/end",
        json={"confirmed": True},
        headers={
            "X-Assistant-Task": task["task_id"],
            "X-Assistant-Revision": str(prepared["revision"]),
        },
    )
    assert actual["state"] == "ended"
    completed = h.event(task["task_id"], "report_business_result")
    assert completed["state"] == "completed"
    after = h.snapshot()
    assert after["sources"] == before["sources"] and after["source_fields"] == before["source_fields"]
    assert after["dose_events"] == before["dose_events"]


def test_revoking_save_invalidates_a_prepared_stop_button(workflow):
    h = workflow
    saved = active_plan(h)
    task = h.start("medication.plan.end", {"regimen_id": saved["regimen_id"], "expected_version": 1})
    prepared = h.event(task["task_id"], "prepare_confirmation")
    h.event(task["task_id"], "cancel_save")
    response = h.client.post(
        f"/api/medications/{saved['regimen_id']}/end",
        params={"client_id": "DEMO-workflow-A"},
        json={"confirmed": True},
        headers={"X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(prepared["revision"])},
    )
    assert response.status_code in {409, 422}
    assert h.snapshot()["regimens"][0]["state"] == "active"


def test_no_save_stop_preview_keeps_query_inputs_separate_and_never_prepares_a_write(workflow):
    h = workflow
    saved = active_plan(h)
    values = {"regimen_id": saved["regimen_id"], "expected_version": 1}
    task = h.start("medication.plan.end", values, save=False)
    assert task.get("input_fields") == values
    h._request(
        "POST",
        f"/api/agent/workflows/tasks/{task['task_id']}/preview",
        json={"ephemeral": {"capability_id": "medication.plan.end", "fields": task["input_fields"]}},
    )
    response = h.client.post(
        f"/api/agent/workflows/tasks/{task['task_id']}/events",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "event_id": str(uuid4()),
            "expected_revision": task["revision"],
            "kind": "prepare_confirmation",
            "values": {},
            "ephemeral": {"capability_id": "medication.plan.end", "fields": values},
        },
    )
    assert response.status_code == 422 and h.snapshot()["regimens"][0]["state"] == "active"


def test_stop_action_rejects_a_different_target_and_stale_regimen_version(workflow):
    h = workflow
    saved = active_plan(h)
    stale = h.client.post(
        "/api/agent/workflows/tasks",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "capability_id": "medication.plan.end",
            "workspace_id": h.workspace_id,
            "save_mode": "allowed",
            "client_event_id": str(uuid4()),
            "values": {"regimen_id": saved["regimen_id"], "expected_version": 99},
        },
    )
    assert stale.status_code == 409
    task = h.start("medication.plan.end", {"regimen_id": saved["regimen_id"], "expected_version": 1})
    prepared = h.event(task["task_id"], "prepare_confirmation")
    other = active_plan(h, "DEMO other active medicine")
    response = h.client.post(
        f"/api/medications/{other['regimen_id']}/end",
        params={"client_id": "DEMO-workflow-A"},
        json={"confirmed": True},
        headers={"X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(prepared["revision"])},
    )
    assert response.status_code in {409, 422}
    assert h.snapshot()["regimens"][0]["state"] == "active"


@pytest.mark.parametrize("capability", ["medication.plan.view", "medication.setup.list"])
def test_reads_actual_owned_plan_details_without_clinical_writes(workflow, capability):
    h = workflow
    saved = h.seed_reviewed_medication()
    before = h.snapshot()
    values = {"medication_id": saved["medication_id"]} if capability == "medication.plan.view" else {}
    result = h.start(capability, values)
    assert result["visible_fields"]["records"][0]["display_name"] == "DEMO-workflow-medicine"
    plan = result["visible_fields"]["records"][0]["plans"][0]
    assert plan["regimen_id"] == saved["regimen_id"] and plan["dose_amount"] == 1
    assert plan["state"] == "draft" and plan["frequency_rule"]["local_times"] == ["20:00"]
    assert "confirmation_challenge_id" not in str(result) and "patient_id" not in str(result)
    assert h.snapshot()["regimens"] == before["regimens"]
    assert h.snapshot()["medications"] == before["medications"]


def test_plan_picker_offers_owned_records_and_checks_ownership_on_selection(workflow):
    h = workflow
    saved = h.seed_reviewed_medication()
    first = h.start("medication.plan.view")
    options = [option for action in first["actions"] if action["kind"] == "choice" for option in action["options"]]
    assert any(option["value"] == saved["medication_id"] for option in options)
    response = h.client.post(
        f"/api/agent/workflows/tasks/{first['task_id']}/events",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "event_id": str(uuid4()),
            "expected_revision": first["revision"],
            "kind": "provide_fields",
            "values": {"medication_id": str(uuid4())},
        },
    )
    assert response.status_code == 404
    selected = h.event(first["task_id"], "provide_fields", {"medication_id": saved["medication_id"]})
    assert selected["visible_fields"]["records"][0]["medication_id"] == saved["medication_id"]


def test_no_save_management_read_never_persists_its_selected_record_or_body(workflow):
    h = workflow
    saved = h.seed_reviewed_medication()
    result = h.start("medication.plan.view", {"medication_id": saved["medication_id"]}, save=False)
    assert result["visible_fields"]["records"][0]["display_name"] == "DEMO-workflow-medicine"
    assert result.get("input_fields") == {"medication_id": saved["medication_id"], "page": 0}
    refreshed = h._request(
        "POST",
        f"/api/agent/workflows/tasks/{result['task_id']}/preview",
        json={
            "ephemeral": {"capability_id": result["capability_id"], "fields": result["input_fields"]},
        },
    )
    assert refreshed["visible_fields"]["records"][0]["display_name"] == "DEMO-workflow-medicine"
    state = h.container.assistant_workflows.persistence_snapshot(h.owner_ids["A"])
    assert "DEMO-workflow-medicine" not in str(state) and saved["medication_id"] not in str(state)
    assert h.view(result["task_id"])["visible_fields"] == {}


def test_discovery_enables_only_composed_management_workflows(workflow):
    result = workflow._request("GET", "/api/agent/workflows/capabilities")
    availability = {row["id"]: row for row in result["capabilities"]}
    assert availability["medication.plan.view"]["available"] is True
    assert availability["medication.setup.list"]["available"] is True
    assert availability["medication.plan.end"]["available"] is True
    assert availability["medication.source.add"]["available"] is True
    assert availability["medication.source.review"]["available"] is True
    assert availability["medication.plan.change"]["available"] is True
    assert availability["inventory.count"]["available"] is True
    assert availability["gallery.photo.add"]["reason"] == "not_implemented"


@pytest.mark.parametrize("text", ["查看用药计划", "show medication plans"])
def test_chat_opens_the_real_plan_picker_instead_of_requesting_an_enrollment(workflow, text):
    h = workflow
    saved = h.seed_reviewed_medication()
    result = message(h, text)
    assert result["workflow"] is not None and result["workflow"]["capability_id"] == "medication.plan.view"
    choices = result["workflow"]["actions"]
    assert any(
        option["value"] == saved["medication_id"]
        for action in choices
        if action["kind"] == "choice"
        for option in action["options"]
    )
    assert len(h.snapshot()["regimens"]) == 1


@pytest.mark.parametrize("text", ["停止追踪用药计划", "stop tracking medication"])
def test_chat_stop_request_only_prepares_the_owned_plan_picker(workflow, text):
    h = workflow
    saved = active_plan(h)
    result = message(h, text)
    assert result["workflow"] is not None and result["workflow"]["capability_id"] == "medication.plan.end"
    assert any(
        option["value"] == f"{saved['regimen_id']}:1"
        for action in result["workflow"]["actions"]
        for option in action.get("options", [])
    )
    assert h.snapshot()["regimens"][0]["state"] == "active"


def test_empty_stop_picker_explains_that_no_active_plan_is_available(workflow):
    task = workflow.start("medication.plan.end")
    assert task["prompt_key"] == "assistant.medication.no_active"
    assert task["missing_fields"] == [] and task["actions"] == []


def test_saved_read_remains_accessible_when_deletions_remove_its_result_page(workflow):
    h = workflow
    drafts = [
        h._request("POST", "/api/medications/drafts", json={"medication_name": f"DEMO page medicine {index}"})
        for index in range(11)
    ]
    task = h.start("medication.plan.view", {"page": 1})
    assert len(task["visible_fields"]["records"]) == 1
    for draft in drafts[:10]:
        h._request("DELETE", f"/api/medications/unfinished/draft/{draft['regimen_id']}", json={"confirmed": True})
    current = h.view(task["task_id"])
    assert current["prompt_key"] == "assistant.medication.page_changed"
    assert current["input_fields"] == {"page": 0}
    assert current["visible_fields"]["records"][0]["display_name"] == "DEMO page medicine 10"
