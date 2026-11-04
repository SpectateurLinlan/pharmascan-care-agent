"""DEMO_ONLY actual native snooze/preferences, independent patient confirmation."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from .test_workflow_medication_management import active_plan
from .test_workflow_records import clinical


def fields(h, capability):
    prefs = h.container.preferences.get(h.owner_ids["A"])
    if capability == "reminder.settings":
        return {"reminders_enabled": False, "reminder_lead_minutes": 30,
                "previous_enabled": prefs.reminders_enabled, "previous_lead_minutes": prefs.reminder_lead_minutes,
                "previous_timezone": prefs.timezone}
    med = active_plan(h)
    rows = h.container.schedule.materialize(patient_id=h.owner_ids["A"], regimen_id=UUID(med["regimen_id"]))
    row = next(row for row in rows if row.due_at > h.clock.now())
    return {"occurrence_id": str(row.id), "minutes": 15, "previous_timezone": prefs.timezone}


def prepared(h, capability):
    task = h.start(capability, fields(h, capability))
    return h.event(task["task_id"], "prepare_confirmation")


def save(h, task, *, values=None, owner="A", confirmed=True):
    payload = values if values is not None else task["visible_fields"]["reminder_review"]["payload"]
    return h.client.request("POST" if task["capability_id"] == "reminder.snooze" else "PUT",
        "/api/reminders" if task["capability_id"] == "reminder.snooze" else "/api/me/preferences",
        params={"client_id": "DEMO-workflow-" + owner}, json=payload,
        headers={"X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(task["revision"]),
                 "X-Patient-Confirmed": str(confirmed).lower()})


@pytest.mark.parametrize("capability", ["reminder.settings", "reminder.snooze"])
def test_patient_confirmation_saves_the_native_result_without_changing_clinical_records(workflow, capability):
    h = workflow
    data = fields(h, capability)
    before = clinical(h)
    old_prefs = h.container.preferences.get(h.owner_ids["A"])
    task = h.start(capability, data)
    assert task["state"] == "ready_for_review"
    task = h.event(task["task_id"], "prepare_confirmation")
    assert not h.container.store.reminders and h.container.preferences.get(h.owner_ids["A"]) == old_prefs
    result = save(h, task)
    assert result.status_code == 200, result.text
    assert clinical(h) == before
    if capability == "reminder.snooze":
        assert result.json()["remind_at"] == (h.clock.now() + timedelta(minutes=15)).isoformat().replace("+00:00", "Z")
    else:
        assert result.json()["reminders_enabled"] is False and result.json()["reminder_lead_minutes"] == 30
    done = h.event(task["task_id"], "report_business_result")
    assert done["state"] == "completed" and done["result_ref"]["kind"] == "reminder_action"


@pytest.mark.parametrize("change", ["owner", "payload", "confirmation", "revision", "paused", "revoked", "native"])
def test_bound_reminder_settings_rejects_changed_authority_without_native_write(workflow, change):
    h = workflow
    task = prepared(h, "reminder.settings")
    options = {}
    if change == "owner":
        options["owner"] = "B"
    if change == "payload":
        options["values"] = {"reminders_enabled": True, "reminder_lead_minutes": 30}
    if change == "confirmation":
        options["confirmed"] = False
    if change == "revision":
        h.event(task["task_id"], "report_business_result")
    if change == "paused":
        h.event(task["task_id"], "pause")
    if change == "revoked":
        h.event(task["task_id"], "cancel_save")
    if change == "native":
        h._request("PUT", "/api/me/preferences", json={"reminder_lead_minutes": 60})
    before = h.container.preferences.get(h.owner_ids["A"])
    result = save(h, task, **options)
    assert result.status_code in {404, 409, 422}, result.text
    assert h.container.preferences.get(h.owner_ids["A"]) == before


def test_snooze_lost_response_replay_does_not_extend_the_saved_time(workflow):
    h = workflow
    task = prepared(h, "reminder.snooze")
    first = save(h, task)
    assert first.status_code == 200
    h.clock.advance(minutes=5)
    second = save(h, task)
    assert second.status_code == 200 and second.json() == first.json()
    assert len(h.container.store.reminders) == 1
    assert h.event(task["task_id"], "report_business_result")["state"] == "completed"


def test_projected_snooze_ids_do_not_materialize_an_occurrence(workflow):
    h = workflow
    active_plan(h)
    projection = h.start("reminder.list")["visible_fields"]["medications"][0]
    before = clinical(h)
    with pytest.raises(AssertionError, match="404|422"):
        h.start("reminder.snooze", {"occurrence_id": projection["occurrence_id"], "minutes": 15,
                                  "previous_timezone": "Asia/Singapore"})
    assert clinical(h) == before and not h.container.store.reminders


def test_no_save_settings_never_has_confirmation_authority_or_saved_values(workflow):
    h = workflow
    task = h.start("reminder.settings", fields(h, "reminder.settings"), save=False)
    assert h.view(task["task_id"])["input_fields"] is None and task["result_ref"] is None
    assert not h.snapshot()["tasks"]
    result = h.client.post(f"/api/agent/workflows/tasks/{task['task_id']}/events",
        params={"client_id": "DEMO-workflow-A"}, json={"event_id": str(uuid4()),
        "expected_revision": task["revision"], "kind": "prepare_confirmation", "values": {}})
    assert result.status_code in {404, 409, 422}


def test_failed_snooze_keeps_draft_and_requires_checked_edit_before_a_new_review(workflow, monkeypatch):
    from app.domain.errors import ProviderUnavailableError

    h = workflow
    task = prepared(h, "reminder.snooze")
    original = h.container.reminders.snooze
    monkeypatch.setattr(h.container.reminders, "snooze", lambda **kw: (_ for _ in ()).throw(
        ProviderUnavailableError("DEMO native failure")))
    assert save(h, task).status_code == 503
    assert h.view(task["task_id"])["input_fields"]["minutes"] == 15
    checked = h.event(task["task_id"], "report_business_result")
    assert checked["state"] != "completed"
    edited = h.event(task["task_id"], "provide_fields", {"minutes": 30})
    task = h.event(edited["task_id"], "prepare_confirmation")
    monkeypatch.setattr(h.container.reminders, "snooze", original)
    assert save(h, task).status_code == 200


def test_settings_success_is_historical_when_current_native_settings_change(workflow):
    h = workflow
    task = prepared(h, "reminder.settings")
    assert save(h, task).status_code == 200
    done = h.event(task["task_id"], "report_business_result")
    h._request("PUT", "/api/me/preferences", json={"reminders_enabled": True})
    current = h.view(task["task_id"])
    assert current["state"] == "completed" and current["result_ref"] == done["result_ref"]
    assert current["visible_fields"]["current_settings"]["reminders_enabled"] is True


@pytest.mark.parametrize("change", ["owner", "payload", "clinical", "deadline"])
def test_snooze_rejects_wrong_target_or_stale_clinical_context(workflow, change):
    h = workflow
    task = prepared(h, "reminder.snooze")
    options = {}
    if change == "owner":
        options["owner"] = "B"
    if change == "payload":
        options["values"] = {"occurrence_id": str(uuid4()), "minutes": 15}
    if change == "clinical":
        occurrence = h.container.schedule.get_occurrence(h.owner_ids["A"], UUID(task["input_fields"]["occurrence_id"]))
        h.container.enrollment.end_regimen(patient_id=h.owner_ids["A"], regimen_id=occurrence.regimen_id)
    if change == "deadline":
        h.clock.advance(days=1)
    before = clinical(h)
    assert save(h, task, **options).status_code in {404, 409, 422}
    assert clinical(h) == before and not h.container.store.reminders


def test_snooze_applied_without_success_receipt_blocks_replay_and_draft_replacement(workflow, monkeypatch):
    from app.domain.errors import ProviderUnavailableError

    h = workflow
    task = prepared(h, "reminder.snooze")
    adapter = h.container.assistant_workflows._adapters["reminder.snooze"]
    complete = adapter.actions.complete

    def fail_receipt(context, receipt):
        if receipt.safe_reason == "reminder_saved":
            raise ProviderUnavailableError("DEMO lost success receipt")
        return complete(context, receipt)

    monkeypatch.setattr(adapter.actions, "complete", fail_receipt)
    assert save(h, task).status_code == 503
    before = dict(h.container.store.reminders)
    h.clock.advance(minutes=5)
    assert save(h, task).status_code == 409
    checked = h.event(task["task_id"], "report_business_result")
    assert checked["state"] != "completed"
    with pytest.raises(AssertionError, match="409"):
        h.event(task["task_id"], "provide_fields", {"minutes": 30})
    assert dict(h.container.store.reminders) == before


@pytest.mark.parametrize("values", [{"minutes": 0}, {"minutes": "15"}, {"minutes": 1441},
    {"reminders_enabled": "false"}, {"reminder_lead_minutes": 121}, {"timezone": "UTC"},
    {"voice_enabled": False}])
def test_reminder_drafts_use_closed_strict_fields(workflow, values):
    h = workflow
    capability = "reminder.snooze" if "minutes" in values else "reminder.settings"
    response = h.client.post("/api/agent/workflows/tasks", params={"client_id": "DEMO-workflow-A"}, json={
        "capability_id": capability, "workspace_id": h.workspace_id, "client_event_id": str(uuid4()),
        "save_mode": "allowed", "values": values})
    assert response.status_code == 422
    assert not h.container.store.reminders


@pytest.mark.parametrize("path,method,payload", [
    ("/api/reminders", "POST", {"occurrence_id": str(uuid4()), "minutes": 15}),
    ("/api/me/preferences", "PUT", {"reminders_enabled": False})])
def test_incomplete_native_reminder_binding_never_falls_back_to_unbound(workflow, path, method, payload):
    h = workflow
    response = h.client.request(method, path, params={"client_id": "DEMO-workflow-A"}, json=payload,
        headers={"X-Assistant-Task": str(uuid4()), "X-Patient-Confirmed": "true"})
    assert response.status_code == 422


@pytest.mark.parametrize("text,capability", [
    ("snooze a reminder", "reminder.snooze"), ("稍后提醒我", "reminder.snooze"),
    ("change reminder settings", "reminder.settings"), ("修改提醒设置", "reminder.settings"),
])
def test_bilingual_reminder_change_entries(workflow, text, capability):
    response = workflow._request("POST", "/api/agent/workflows/messages", json={"text": text,
        "workspace_id": workflow.workspace_id, "client_turn_id": str(uuid4())})
    assert response["workflow"]["capability_id"] == capability
