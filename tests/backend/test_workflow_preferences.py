"""DEMO_ONLY typed preference drafts and actual independent native saves."""

from uuid import uuid4

import pytest

from .test_workflow_records import clinical

CASES = {
    "preference.language": {"preferred_language": "zh"},
    "preference.text": {"text_scale_percent": 125},
    "preference.voice": {"voice_enabled": False, "tts_autoplay": False},
    "preference.reminder": {"reminders_enabled": False, "reminder_lead_minutes": 30},
    "preference.privacy": {"conversation_history_enabled": True},
    "preference.timezone": {"timezone": "America/New_York"},
    "profile.edit": {"display_name": "DEMO preference owner"},
}


def previous(h):
    return h.container.preferences.get(h.owner_ids["A"]).model_dump(mode="json", exclude={
        "patient_id", "created_at", "updated_at"})


def prepared(h, capability="preference.text", values=None):
    task = h.start(capability, {**(values or CASES[capability]), "previous": previous(h)})
    return h.event(task["task_id"], "prepare_confirmation")


def save(h, task, *, values=None, owner="A", confirmed=True):
    payload = values if values is not None else task["visible_fields"]["settings_review"]["payload"]
    return h.client.put("/api/me/preferences", params={"client_id": "DEMO-workflow-" + owner}, json=payload,
        headers={"X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(task["revision"]),
                 "X-Patient-Confirmed": str(confirmed).lower()})


@pytest.mark.parametrize("capability", CASES)
def test_each_preference_uses_its_native_scope_and_actual_readback(workflow, capability):
    h = workflow
    before, old = clinical(h), previous(h)
    task = prepared(h, capability)
    assert previous(h) == old and clinical(h) == before
    result = save(h, task)
    assert result.status_code == 200, result.text
    for key, value in CASES[capability].items():
        assert result.json()[key] == value
    assert clinical(h) == before
    done = h.event(task["task_id"], "report_business_result")
    assert done["state"] == "completed" and done["result_ref"]["kind"] == "settings_action"
    for key, value in CASES[capability].items():
        assert done["visible_fields"]["current_preferences"][key] == value


def test_profile_query_is_owned_metadata_without_a_patient_write(workflow):
    h = workflow
    before, old = clinical(h), previous(h)
    task = h.start("profile.view")
    assert task["visible_fields"]["current_preferences"] == old
    assert task["result_ref"] is None and clinical(h) == before
    assert "patient_id" not in str(task["visible_fields"])


@pytest.mark.parametrize("change", ["owner", "payload", "confirm", "paused", "revoked", "native", "revision"])
def test_preference_binding_rejects_wrong_or_stale_patient_authority(workflow, change):
    h = workflow
    task = prepared(h)
    options = {}
    if change == "owner":
        options["owner"] = "B"
    if change == "payload":
        options["values"] = {"timezone": "UTC"}
    if change == "confirm":
        options["confirmed"] = False
    if change == "paused":
        h.event(task["task_id"], "pause")
    if change == "revoked":
        h.event(task["task_id"], "cancel_save")
    if change == "native":
        h._request("PUT", "/api/me/preferences", json={"text_scale_percent": 140})
    if change == "revision":
        task = {**task, "revision": task["revision"] + 1}
    old = previous(h)
    result = save(h, task, **options)
    assert result.status_code in {404, 409, 422}, result.text
    assert previous(h) == old


@pytest.mark.parametrize("capability,values", [("preference.language", {"timezone": "UTC"}),
    ("preference.text", {"text_scale_percent": 99}), ("preference.voice", {"voice_enabled": "true"}),
    ("preference.timezone", {"timezone": "not-a-zone"}), ("profile.edit", {"password": "DEMO-secret"})])
def test_preference_inputs_are_strict_and_cannot_expand_scope(workflow, capability, values):
    h = workflow
    response = h.client.post("/api/agent/workflows/tasks", params={"client_id": "DEMO-workflow-A"}, json={
        "capability_id": capability, "workspace_id": h.workspace_id, "client_event_id": str(uuid4()),
        "save_mode": "allowed", "values": values})
    assert response.status_code == 422


def test_no_save_preference_draft_never_saves_native_state_or_task_fields(workflow):
    h = workflow
    old = previous(h)
    task = h.start("preference.text", {"text_scale_percent": 125, "previous": old}, save=False)
    assert previous(h) == old and h.view(task["task_id"])["input_fields"] is None
    with pytest.raises(AssertionError, match="404|409|422"):
        h.event(task["task_id"], "prepare_confirmation")


def test_preference_lost_response_replay_does_not_override_later_native_changes(workflow):
    h = workflow
    task = prepared(h)
    assert save(h, task).status_code == 200
    h._request("PUT", "/api/me/preferences", json={"text_scale_percent": 140})
    assert save(h, task).status_code == 200
    assert previous(h)["text_scale_percent"] == 140
    done = h.event(task["task_id"], "report_business_result")
    assert done["state"] == "completed"
    assert done["visible_fields"]["current_preferences"]["text_scale_percent"] == 140


def test_failed_preference_save_preserves_draft_until_checked_edit_and_new_review(workflow, monkeypatch):
    from app.domain.errors import ProviderUnavailableError

    h = workflow
    task = prepared(h)
    original = h.container.preferences.save
    monkeypatch.setattr(h.container.preferences, "save", lambda *args: (_ for _ in ()).throw(
        ProviderUnavailableError("DEMO preference unavailable")))
    assert save(h, task).status_code == 503
    assert h.view(task["task_id"])["input_fields"]["text_scale_percent"] == 125
    h.event(task["task_id"], "report_business_result")
    h.event(task["task_id"], "provide_fields", {"text_scale_percent": 130})
    task = h.event(task["task_id"], "prepare_confirmation")
    monkeypatch.setattr(h.container.preferences, "save", original)
    assert save(h, task).json()["text_scale_percent"] == 130
