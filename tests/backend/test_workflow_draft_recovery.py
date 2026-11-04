"""Saved draft recovery over actual public DEMO services and patient APIs."""

from uuid import UUID, uuid4

import pytest

from .test_workflow_enrollment import message


def enrollment(h):
    task = h.start(
        "medication.enroll",
        {
            "method": "manual",
            "medication_name": "DEMO recovery",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_rule": {"kind": "daily", "local_times": ["08:00"]},
        },
    )
    return h.event(task["task_id"], "prepare_confirmation")


def challenge(h, ref, session):
    source = h.container.enrollment.get_regimen(h.owner_ids["A"], UUID(ref["id"])).source_id
    current = h.container.enrollment.get_source(h.owner_ids["A"], source)
    if current.reviewed_at is None:
        h._request("POST", f"/api/medications/drafts/{source}/review", json={"field_ids": None})
    return h._request("POST", f"/api/medications/drafts/{ref['id']}/challenge", params={"session_id": session}, json={})


def activate(h, ref, confirmation):
    return h.client.post(
        "/api/medications/activate",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "regimen_id": ref["id"],
            **{
                key: confirmation[key]
                for key in ("challenge_id", "session_id", "session_state", "session_state_version")
            },
        },
    )


def test_legacy_draft_recovery_prepares_the_same_aggregate_then_uses_independent_activation(workflow):
    h = workflow
    old = h.seed_reviewed_medication()
    before = h.snapshot()
    task = h.start("medication.draft.resume", {"regimen_id": old["regimen_id"], "expected_version": 1})
    assert task["state"] == "ready_for_review"
    prepared = h.event(task["task_id"], "prepare_confirmation")
    assert prepared["result_ref"]["id"] == old["regimen_id"]
    assert prepared["actions"][0]["component_key"] == "existing_activation"
    assert h.snapshot()["regimens"] == before["regimens"]
    assert h.snapshot()["sources"] == before["sources"]
    confirmed = challenge(h, prepared["result_ref"], old["session_id"])
    assert activate(h, prepared["result_ref"], confirmed).status_code == 200
    assert h.event(task["task_id"], "report_business_result")["state"] == "completed"


def test_suspended_recovery_stays_readable_after_the_original_task_activates(workflow):
    h = workflow
    session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})
    original = enrollment(h)
    recovery = h.start("medication.draft.resume", {"regimen_id": original["result_ref"]["id"], "expected_version": 1})
    resumed = h._request(
        "POST",
        f"/api/agent/workflows/tasks/{recovery['task_id']}/resume-draft",
        json={"expected_revision": recovery["revision"]},
    )
    confirm = challenge(h, resumed["result_ref"], session["session_id"])
    assert activate(h, resumed["result_ref"], confirm).status_code == 200
    h.event(resumed["task_id"], "report_business_result")
    rows = h._request("GET", "/api/agent/workflows/tasks")
    saved = next(row for row in rows if row["task_id"] == recovery["task_id"])
    assert saved["state"] == "suspended" and not saved["actions"]


def test_bound_draft_handoff_returns_to_original_saved_task_without_moving_its_authority(workflow):
    h = workflow
    original = enrollment(h)
    before = h.snapshot()
    task = h.start("medication.draft.resume", {"regimen_id": original["result_ref"]["id"], "expected_version": 1})
    assert any(action["kind"] == "resume_task" for action in task["actions"])
    assert h.view(original["task_id"])["state"] == "suspended"
    resumed = h._request(
        "POST",
        f"/api/agent/workflows/tasks/{task['task_id']}/resume-draft",
        json={"expected_revision": task["revision"]},
    )
    assert resumed["task_id"] == original["task_id"] and resumed["state"] == "awaiting_confirmation"
    assert h.view(task["task_id"])["state"] == "suspended"
    assert h.snapshot()["regimens"] == before["regimens"]
    assert h.snapshot()["sources"] == before["sources"]


def test_revoking_legacy_recovery_invalidates_independent_review_and_does_not_delete_clinical_draft(workflow):
    h = workflow
    old = h.seed_reviewed_medication()
    task = h.start("medication.draft.resume", {"regimen_id": old["regimen_id"], "expected_version": 1})
    h.event(task["task_id"], "prepare_confirmation")
    h.event(task["task_id"], "cancel_save")
    denied = h.client.post(
        f"/api/medications/drafts/{old['regimen_id']}/challenge",
        params={"client_id": "DEMO-workflow-A", "session_id": old["session_id"]},
        json={},
    )
    assert denied.status_code in {409, 422}
    assert h.snapshot()["regimens"][0]["state"] == "draft"


def test_an_activation_challenge_from_before_recovery_cannot_be_replayed(workflow):
    h = workflow
    session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})
    original = enrollment(h)
    old_challenge = challenge(h, original["result_ref"], session["session_id"])
    h.event(original["task_id"], "pause")
    h.event(original["task_id"], "resume")
    assert activate(h, original["result_ref"], old_challenge).status_code in {409, 422}
    fresh = challenge(h, original["result_ref"], session["session_id"])
    assert activate(h, original["result_ref"], fresh).status_code == 200


def test_missing_details_create_a_new_unactivated_version_and_keep_original_sources(workflow):
    h = workflow
    old = h._request("POST", "/api/medications/drafts", json={"medication_name": "DEMO incomplete recovery"})
    before = h.snapshot()
    task = h.start("medication.draft.resume", {"regimen_id": old["regimen_id"], "expected_version": 1})
    assert task["state"] == "collecting" and "dose_amount" in task["missing_fields"]
    ready = h.event(
        task["task_id"],
        "provide_fields",
        {
            "details": {
                "method": "manual",
                "medication_name": "DEMO incomplete recovery",
                "dose_amount": 1,
                "dose_unit": "tablet",
                "frequency_rule": {"kind": "daily", "local_times": ["20:00"]},
            }
        },
    )
    assert ready["state"] == "ready_for_review"
    prepared = h.event(task["task_id"], "prepare_confirmation")
    assert prepared["result_ref"]["id"] != old["regimen_id"] and prepared["result_ref"]["version"] == 2
    assert h.snapshot()["regimens"][0] == before["regimens"][0]
    assert h.snapshot()["sources"][0] == before["sources"][0]
    assert len(h.snapshot()["medications"]) == 1 and not h.snapshot()["dose_events"]
    session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})
    loaded = h._request("GET", f"/api/medications/drafts/{prepared['result_ref']['id']}")
    assert loaded["identity_review"] == {"source_id": old["source_id"], "medication_name": "DEMO incomplete recovery"}
    h._request(
        "POST",
        f"/api/medications/drafts/{prepared['result_ref']['id']}/identity-review",
        headers={"X-Assistant-Task": prepared["task_id"], "X-Assistant-Revision": str(prepared["revision"])},
        json={"confirmed": True},
    )
    reviewed = h.snapshot()
    assert reviewed["sources"][:1] == before["sources"][:1]
    original_fields = [row for row in reviewed["source_fields"] if row["source_id"] == old["source_id"]]
    assert all(
        row["review_status"] == ("user_reviewed" if row["field_name"] == "medication_name" else "extracted")
        for row in original_fields
    )
    current = challenge(h, prepared["result_ref"], session["session_id"])
    assert activate(h, prepared["result_ref"], current).status_code == 200


@pytest.mark.parametrize("mode", ["ephemeral", "revoked", "foreign", "wrong_target"])
def test_original_task_handoff_cannot_bypass_ownership_no_save_or_choose_a_destination(workflow, mode):
    h = workflow
    original = enrollment(h)
    task = h.start(
        "medication.draft.resume",
        {"regimen_id": original["result_ref"]["id"], "expected_version": 1},
        save=mode != "ephemeral",
    )
    if mode == "revoked":
        h.event(task["task_id"], "cancel_save")
    payload = {"expected_revision": task["revision"]}
    if mode == "wrong_target":
        payload["target_task_id"] = str(uuid4())
    response = h.client.post(
        f"/api/agent/workflows/tasks/{task['task_id']}/resume-draft",
        params={"client_id": "DEMO-workflow-" + ("B" if mode == "foreign" else "A")},
        json=payload,
    )
    assert response.status_code in {404, 409, 422}
    assert h.view(original["task_id"])["state"] == "suspended"
    assert h.snapshot()["regimens"][0]["state"] == "draft"


def test_revoked_original_is_not_adopted_by_another_saved_task(workflow):
    h = workflow
    original = enrollment(h)
    h.event(original["task_id"], "cancel_save")
    task = h.start("medication.draft.resume", {"regimen_id": original["result_ref"]["id"], "expected_version": 1})
    assert task["state"] == "failed_recoverable" and not task["actions"]
    response = h.client.post(
        f"/api/agent/workflows/tasks/{task['task_id']}/resume-draft",
        params={"client_id": "DEMO-workflow-A"},
        json={"expected_revision": task["revision"]},
    )
    assert response.status_code in {404, 409, 422}
    assert h.snapshot()["regimens"][0]["state"] == "draft"


def test_recovery_picker_is_owned_paged_and_does_not_silently_drop_an_eleventh_draft(workflow):
    h = workflow
    for number in range(11):
        h._request("POST", "/api/medications/drafts", json={"medication_name": f"DEMO recovery {number}"})
    first = h.start("medication.draft.resume")
    assert len(first["actions"][0]["options"]) == 10 and first["visible_fields"]["page_count"] == 2
    next_page = h.event(first["task_id"], "provide_fields", {"page": 1})
    assert len(next_page["actions"][0]["options"]) == 1
    foreign = h.client.post(
        "/api/agent/workflows/tasks",
        params={"client_id": "DEMO-workflow-B"},
        json={
            "capability_id": "medication.draft.resume",
            "workspace_id": str(uuid4()),
            "client_event_id": str(uuid4()),
            "values": {"regimen_id": str(h.snapshot()["regimens"][0]["id"])},
        },
    )
    assert foreign.status_code == 404


@pytest.mark.parametrize("text", ["继续药物草稿", "resume a medication draft"])
def test_plain_chat_enters_actual_recovery_and_explains_the_remaining_steps(workflow, text):
    h = workflow
    h.seed_reviewed_medication()
    result = message(h, text)
    assert result["workflow"] is not None and result["workflow"]["capability_id"] == "medication.draft.resume"
    assert result["workflow"]["actions"][0]["action_id"] == "medication.resume_target"
    assert "medication.draft.resume" not in result["reply"]["message"]


def test_chat_missing_slot_is_nested_into_recovery_details_without_losing_the_original_target(workflow):
    h = workflow
    old = h._request(
        "POST",
        "/api/medications/drafts",
        json={
            "medication_name": "DEMO incomplete recovery",
            "dose_unit": "tablet",
            "frequency_kind": "daily",
            "frequency_local_times": ["20:00"],
        },
    )
    task = h.start("medication.draft.resume", {"regimen_id": old["regimen_id"], "expected_version": 1})
    assert task["missing_fields"] == ["dose_amount"]
    reply = message(h, "2", task)
    assert reply["reply"]["mode"] == "workflow"
    updated = reply["workflow"]
    assert updated["visible_fields"]["dose_amount"] == 2 and updated["state"] == "ready_for_review"
    assert updated["input_fields"]["regimen_id"] == old["regimen_id"]
    assert h.snapshot()["regimens"][0]["dose_amount"] is None


def test_no_save_legacy_recovery_never_creates_a_binding_or_activation_challenge(workflow):
    h = workflow
    old = h.seed_reviewed_medication()
    before = h.snapshot()
    task = h.start("medication.draft.resume", {"regimen_id": old["regimen_id"], "expected_version": 1}, save=False)
    assert task["input_fields"] == {"regimen_id": old["regimen_id"], "expected_version": 1, "page": 0}
    response = h.client.post(
        f"/api/agent/workflows/tasks/{task['task_id']}/events",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "event_id": str(uuid4()),
            "expected_revision": task["revision"],
            "kind": "prepare_confirmation",
            "values": {},
            "ephemeral": {"capability_id": task["capability_id"], "fields": task["input_fields"]},
        },
    )
    assert response.status_code == 422
    assert not h.container.store.enrollment_operations
    assert h.snapshot()["regimens"] == before["regimens"]


def test_an_active_or_stale_version_cannot_be_recovered_as_a_draft(workflow):
    from .test_workflow_medication_management import active_plan

    h = workflow
    old = h.seed_reviewed_medication()
    stale = h.client.post(
        "/api/agent/workflows/tasks",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "workspace_id": h.workspace_id,
            "client_event_id": str(uuid4()),
            "capability_id": "medication.draft.resume",
            "values": {"regimen_id": old["regimen_id"], "expected_version": 2},
        },
    )
    assert stale.status_code == 409
    active = active_plan(h, "DEMO recovery active protected")
    denied = h.client.post(
        "/api/agent/workflows/tasks",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "workspace_id": h.workspace_id,
            "client_event_id": str(uuid4()),
            "capability_id": "medication.draft.resume",
            "values": {"regimen_id": active["regimen_id"], "expected_version": 1},
        },
    )
    assert denied.status_code == 422


def test_concurrent_legacy_recovery_cannot_steal_the_first_saved_task_binding(workflow):
    from concurrent.futures import ThreadPoolExecutor

    from app.domain.errors import StaleVersionError

    from .test_workflow_enrollment_operations import services

    h = workflow
    old = h.seed_reviewed_medication()
    service, writer = services(h)

    def bind():
        task_id = uuid4()
        try:
            return service.bind_existing_once(
                h.owner_ids["A"],
                UUID(old["regimen_id"]),
                1,
                action_key=uuid4(),
                workflow_task_id=task_id,
                workflow_revision=1,
            )
        except StaleVersionError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = list(pool.map(lambda _: bind(), range(2)))
    assert sum(row is not None for row in attempts) == 1
    winner = next(row for row in attempts if row is not None)
    assert writer.for_regimen(h.owner_ids["A"], UUID(old["regimen_id"])) == winner
    assert len(h.snapshot()["regimens"]) == 1


def test_handoff_across_workspaces_pauses_the_recovery_task_before_resuming_original(workflow):
    h = workflow
    original = enrollment(h)
    h.workspace_id = str(uuid4())
    task = h.start("medication.draft.resume", {"regimen_id": original["result_ref"]["id"], "expected_version": 1})
    resumed = h._request(
        "POST",
        f"/api/agent/workflows/tasks/{task['task_id']}/resume-draft",
        json={"expected_revision": task["revision"]},
    )
    assert resumed["task_id"] == original["task_id"]
    assert h.view(task["task_id"])["state"] == "suspended"


def test_a_legacy_confirmation_issued_before_the_saved_recovery_is_rejected_with_a_new_review_prompt(workflow):
    h = workflow
    old = h.seed_reviewed_medication()
    ref = {"id": old["regimen_id"]}
    stale = challenge(h, ref, old["session_id"])
    task = h.start("medication.draft.resume", {"regimen_id": old["regimen_id"], "expected_version": 1})
    prepared = h.event(task["task_id"], "prepare_confirmation")
    denied = activate(h, prepared["result_ref"], stale)
    assert denied.status_code == 409 and "new summary" in denied.json()["message"]
    current = challenge(h, prepared["result_ref"], old["session_id"])
    assert activate(h, prepared["result_ref"], current).status_code == 200


def test_original_name_review_requires_the_current_independent_saved_draft(workflow):
    h = workflow
    old = h._request("POST", "/api/medications/drafts", json={"medication_name": "DEMO original-name fence"})
    task = h.start(
        "medication.draft.resume",
        {
            "regimen_id": old["regimen_id"],
            "details": {
                "method": "manual",
                "medication_name": "DEMO original-name fence",
                "dose_amount": 1,
                "dose_unit": "tablet",
                "frequency_rule": {"kind": "daily", "local_times": ["20:00"]},
            },
        },
    )
    prepared = h.event(task["task_id"], "prepare_confirmation")
    original_fields = h.snapshot()["source_fields"]
    h.event(task["task_id"], "cancel_save")
    denied = h.client.post(
        f"/api/medications/drafts/{prepared['result_ref']['id']}/identity-review",
        params={"client_id": "DEMO-workflow-A"},
        json={"confirmed": True},
        headers={"X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(prepared["revision"])},
    )
    assert denied.status_code in {409, 422}
    assert h.snapshot()["source_fields"] == original_fields


def test_source_registration_drafts_require_source_reconciliation_instead_of_manual_identity_adoption(
    workflow, monkeypatch
):
    from .test_workflow_draft_deletion import source_task

    h = workflow
    source = source_task(h, monkeypatch)
    saved = h._request(
        "POST",
        f"/api/evidence/tasks/{source['id']}/review",
        json={
            "patient_reviewed": True,
            "draft": {
                "medication_name": source["product"]["name"],
                "dose_amount": 1,
                "dose_unit": "tablet",
                "frequency_rule": {"kind": "daily", "local_times": ["08:00"]},
            },
        },
    )
    task = h.start("medication.draft.resume", {"regimen_id": saved["draft_regimen_id"], "expected_version": 1})
    assert task["state"] == "failed_recoverable" and task["prompt_key"] == "assistant.medication.resume_source"
    assert not task["actions"] and not h.container.store.enrollment_operations


def test_recovering_a_photo_backed_task_keeps_the_exact_original_and_does_not_repeat_recognition():
    from .test_workflow_originals import original_png
    from .test_workflow_photo_enrollment import label
    from .workflow_support import WorkflowHarness

    with WorkflowHarness(source_results=[label()]) as h:
        original = h.start("medication.enroll", {"method": "photo"})
        uploaded = h.upload(original["task_id"], original_png())
        message(h, "08:00, 20:00", uploaded["workflow"])
        prepared = h.event(original["task_id"], "prepare_confirmation")
        recovery = h.start("medication.draft.resume", {"regimen_id": prepared["result_ref"]["id"]})
        resumed = h._request(
            "POST",
            f"/api/agent/workflows/tasks/{recovery['task_id']}/resume-draft",
            json={"expected_revision": recovery["revision"]},
        )
        assert resumed["task_id"] == original["task_id"]
        assert h.read_original(uploaded["attachment"]["id"]) == original_png()
        assert len(h.source_calls) == 1 and len(h.snapshot()["regimens"]) == 1
