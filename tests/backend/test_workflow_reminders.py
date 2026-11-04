"""DEMO_ONLY read-only reminder projection and task-bound native calendar bytes."""

from uuid import uuid4

import pytest

from .test_workflow_medication_management import active_plan
from .test_workflow_records import clinical


def calendar(h, task, *, owner="A", params=None):
    return h.client.get("/api/reminders/calendar", params={
        "client_id": "DEMO-workflow-" + owner, "range": "30", **(params or {}),
    }, headers={"X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(task["revision"])})


def test_reminder_query_is_a_real_read_projection_without_materializing_doses(workflow):
    h = workflow
    active_plan(h, "DEMO reminder medicine")
    before = clinical(h)
    task = h.start("reminder.list", {"days": 7})
    rows = task["visible_fields"]["medications"]
    assert rows and rows[0]["medication_name"] == "DEMO reminder medicine"
    assert all(row["projected_only"] for row in rows)
    assert task["result_ref"] is None
    h.view(task["task_id"])
    h.container.assistant_workflows.list_views(h.owner_ids["A"])
    assert clinical(h) == before
    assert "patient_id" not in str(task["visible_fields"])


def test_explicit_task_bound_calendar_exports_native_ics_without_occurrence_or_dose_writes(workflow):
    h = workflow
    active_plan(h, "DEMO calendar medicine")
    before = clinical(h)
    task = h.start("reminder.calendar.export", {"range": "30"})
    assert task["result_ref"] is None and clinical(h) == before
    result = calendar(h, task)
    assert result.status_code == 200, result.text
    assert result.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in result.text and "DEMO calendar medicine" in result.text
    assert "Cache-Control" in result.headers
    assert clinical(h) == before and h.view(task["task_id"])["result_ref"] is None


@pytest.mark.parametrize("change", ["owner", "options", "revision", "paused"])
def test_calendar_rejects_cross_owner_or_changed_review_options(workflow, change):
    h = workflow
    active_plan(h)
    task = h.start("reminder.calendar.export", {"range": "30"})
    if change == "paused":
        task = h.event(task["task_id"], "pause")
    options = {"owner": {"owner": "B"}, "options": {"params": {"range": "90"}},
               "revision": {}, "paused": {}}[change]
    if change == "revision":
        h.event(task["task_id"], "provide_fields", {"range": "90"})
    response = calendar(h, task, **options)
    assert response.status_code in {404, 409, 422}, response.text
    assert not h.container.store.events


def test_no_save_calendar_accepts_current_page_options_but_keeps_no_task_fields(workflow):
    h = workflow
    active_plan(h)
    task = h.start("reminder.calendar.export", {"range": "30"}, save=False)
    before = clinical(h)
    response = calendar(h, task, params={"range": "90"})
    assert response.status_code == 200 and "BEGIN:VCALENDAR" in response.text
    assert clinical(h) == before
    assert h.view(task["task_id"])["input_fields"] is None


def test_empty_calendar_is_a_failure_not_a_download_success(workflow):
    h = workflow
    task = h.start("reminder.calendar.export", {"range": "30"})
    response = calendar(h, task)
    assert response.status_code == 422
    assert h.view(task["task_id"])["result_ref"] is None


def test_care_reminders_are_owned_read_metadata_without_materializing_doses(workflow):
    from datetime import timedelta

    from app.contracts.long_term import CareTaskInput

    h = workflow
    h.container.long_term.create_task(h.owner_ids["A"], CareTaskInput(
        id=uuid4(), category="medication_review", title="DEMO future care reminder",
        due_at=h.clock.now() + timedelta(hours=1), reminder_minutes=15, confirmed=True,
    ))
    before = clinical(h)
    task = h.start("reminder.list")
    assert task["visible_fields"]["care_tasks"][0]["title"] == "DEMO future care reminder"
    assert clinical(h) == before
    other = h._request("POST", "/api/agent/workflows/tasks", owner="B", json={
        "capability_id": "reminder.list", "workspace_id": str(uuid4()), "save_mode": "allowed",
        "client_event_id": str(uuid4()), "values": {},
    })
    assert not other["visible_fields"]["care_tasks"]


def test_calendar_discards_a_result_when_its_task_changes_during_export(workflow, monkeypatch):
    h = workflow
    active_plan(h)
    task = h.start("reminder.calendar.export")
    original = h.container.reminder_plan.calendar_export_rows

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        h.event(task["task_id"], "pause")
        return result

    monkeypatch.setattr(h.container.reminder_plan, "calendar_export_rows", changed)
    assert calendar(h, task).status_code == 409


def test_notification_status_read_has_no_subscription_or_sender_authority(workflow):
    h = workflow
    task = h.start("notification.status")
    assert task["result_ref"] is None and "endpoint" not in str(task)
    catalog = h._request("GET", "/api/agent/workflows/capabilities")["capabilities"]
    by_id = {row["id"]: row for row in catalog}
    for capability in ("reminder.list", "reminder.calendar.export", "notification.status",
                       "reminder.snooze", "reminder.settings", "notification.subscribe", "notification.unsubscribe"):
        assert by_id[capability]["available"] is True
    assert by_id["notification.test"]["available"] is False
    assert by_id["notification.test"]["reason"] == "notification_send_not_authorized"
    assert h.container.push_test is None


@pytest.mark.parametrize("text,capability", [
    ("show my reminders", "reminder.list"), ("查看我的提醒", "reminder.list"),
    ("export reminder calendar", "reminder.calendar.export"), ("导出提醒日历", "reminder.calendar.export"),
    ("check notification status", "notification.status"), ("查看通知状态", "notification.status"),
])
def test_bilingual_reminder_read_entries(workflow, text, capability):
    result = workflow._request("POST", "/api/agent/workflows/messages", json={
        "text": text, "workspace_id": workflow.workspace_id, "client_turn_id": str(uuid4()),
    })
    assert result["workflow"]["capability_id"] == capability
