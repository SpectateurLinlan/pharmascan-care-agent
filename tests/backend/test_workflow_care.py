"""DEMO_ONLY actual care APIs, independently confirmed workflow writes."""

from datetime import timedelta
from uuid import uuid4

import pytest

CAPABILITIES = (
    "observation.list",
    "observation.add",
    "observation.edit",
    "observation.delete",
    "inventory.view",
    "inventory.count",
    "barrier.list",
    "barrier.add",
    "followup.list",
    "followup.add",
    "followup.edit",
    "followup.contacted",
    "followup.complete",
    "followup.defer",
    "followup.cancel",
)


def test_followup_edit_can_explicitly_clear_link_and_reminder_after_patient_review(workflow):
    from .test_workflow_medication_management import active_plan

    h = workflow
    med = active_plan(h)
    old = h._request(
        "POST",
        "/api/me/care-tasks",
        json={
            "id": str(uuid4()),
            "category": "medication_review",
            "title": "DEMO linked followup",
            "medication_id": med["medication_id"],
            "regimen_id": med["regimen_id"],
            "due_at": (h.clock.now() + timedelta(days=2)).isoformat(),
            "reminder_minutes": 60,
            "confirmed": True,
        },
    )
    task = prepared(
        h, "followup.edit", {"task_id": old["id"], "expected_version": 1, "clear_plan": True, "disable_reminder": True}
    )
    result = save(h, task)
    assert result["regimen_id"] is None and result["medication_id"] is None and result["reminder_minutes"] is None
    assert result["history"][0] == old["history"][0]
    assert save(h, task) == result


@pytest.mark.parametrize(
    "kind,unit,value,secondary",
    [
        ("blood_pressure", "mmHg", 120, 80),
        ("blood_glucose", "mmol/L", 5.6, None),
        ("blood_glucose", "mg/dL", 100, None),
        ("weight", "kg", 65, None),
        ("sleep", "hours", 7, None),
        ("mood", "score", 4, None),
    ],
)
def test_actual_observation_measurement_and_unit_survive_the_patient_workflow(workflow, kind, unit, value, secondary):
    h = workflow
    task = prepared(
        h,
        "observation.add",
        {**fields(h, "observation.add"), "kind": kind, "unit": unit, "value": value, "secondary_value": secondary},
    )
    saved = save(h, task)
    assert (saved["kind"], saved["unit"], saved["value"], saved["secondary_value"]) == (kind, unit, value, secondary)
    assert h.event(task["task_id"], "report_business_result")["state"] == "completed"


def test_no_save_care_draft_retains_no_text_fingerprint_or_action_receipt(workflow):
    h = workflow
    task = h.start(
        "observation.add",
        {**fields(h, "observation.add"), "description": "DEMO private page-only description"},
        save=False,
    )
    snapshot = h.snapshot()
    assert snapshot["tasks"] == [] and not snapshot["history"]
    assert "DEMO private page-only description" not in str(snapshot["workflow_controls"])
    state = h.container.assistant_workflows._repository._state
    assert not state.actions and not state.events
    assert task["save_mode"] == "ephemeral"


def test_failed_deletion_receipt_does_not_claim_success_from_a_missing_record(workflow, monkeypatch):
    h = workflow
    note = h._request(
        "PUT",
        "/api/me/health-observations",
        json={
            "id": str(uuid4()),
            "description": "DEMO deletion result uncertainty",
            "occurred_at": h.clock.now().isoformat(),
            "confirmed": True,
        },
    )
    task = prepared(h, "observation.delete", fields(h, "observation.delete", observation=note))
    adapter = h.container.assistant_workflows._adapters["observation.delete"]
    original = adapter.actions.complete

    def broken(context, receipt):
        if receipt.safe_reason == "care_deleted":
            raise OSError("DEMO receipt unavailable after business deletion")
        return original(context, receipt)

    monkeypatch.setattr(adapter.actions, "complete", broken)
    with pytest.raises(OSError):
        save(h, task)
    monkeypatch.setattr(adapter.actions, "complete", original)
    checked = h.event(task["task_id"], "report_business_result")
    assert checked["state"] != "completed"
    assert not h._request("GET", "/api/me/health-observations")


def test_unsure_patient_dose_report_never_creates_a_medication_barrier(workflow):
    from .test_workflow_report_bindings import prn_plan

    h = workflow
    med = prn_plan(h)
    values = {"regimen_id": med["regimen_id"], "intake_status": "unsure", "idempotency_key": "report-" + str(uuid4())}
    summary = h._request("POST", "/api/prn/report/challenge", json=values)
    h._request("POST", "/api/prn/report", json={**values, "challenge_id": summary["challenge_id"]})
    h.start("barrier.list", {})
    assert h.container.long_term.barriers(h.owner_ids["A"]) == []


def test_model_care_fields_reject_confirmation_ids_and_client_success():
    from app.contracts.assistant_workflows import validate_workflow_values
    from pydantic import ValidationError

    for capability in CAPABILITIES:
        for key in ("patient_id", "confirmed", "historical_confirmed", "id", "success"):
            with pytest.raises(ValidationError):
                validate_workflow_values(capability, {key: True})


def fields(h, capability, medicine=None, task=None, observation=None):
    now = h.clock.now()
    values = {
        "observation.add": {"description": "DEMO patient description", "occurred_at": now.isoformat()},
        "observation.delete": {"observation_id": observation["id"]} if observation else {},
        "inventory.count": {"medication_id": medicine["medication_id"], "quantity": 12, "unit": "tablet"}
        if medicine
        else {},
        "inventory.view": {"medication_id": medicine["medication_id"]} if medicine else {},
        "barrier.add": {
            "category": "scheduling",
            "occurred_at": now.isoformat(),
            "description": "DEMO difficult timing",
        },
        "followup.add": {"title": "DEMO pharmacy review", "due_at": (now + timedelta(days=2)).isoformat()},
    }.get(capability, {})
    if task and capability.startswith("followup.") and capability not in {"followup.add", "followup.list"}:
        values = {"task_id": task["id"], "expected_version": task["version"]}
        if capability in {"followup.defer", "followup.edit"}:
            values["due_at"] = (now + timedelta(days=3)).isoformat()
        if capability == "followup.edit":
            values["title"] = "DEMO updated pharmacy review"
    return values


@pytest.mark.parametrize("capability", CAPABILITIES)
def test_every_care_capability_has_a_real_nonmutating_preparation(workflow, capability):
    h = workflow
    before = h.snapshot()
    task = h.start(capability, {})
    assert task["capability_id"] == capability
    h.view(task["task_id"])
    assert h.snapshot()["dose_events"] == before["dose_events"]
    assert not h.container.long_term.tasks(h.owner_ids["A"])
    assert not h.container.long_term.barriers(h.owner_ids["A"])


def prepared(h, capability, values):
    task = h.start(capability, values)
    return h.event(task["task_id"], "prepare_confirmation")


def binding(view):
    return {"X-Assistant-Task": view["task_id"], "X-Assistant-Revision": str(view["revision"])}


def patient_request(h, view):
    review = view["visible_fields"]["care_review"]
    capability = view["capability_id"]
    values = {**review["payload"], "confirmed": True}
    routes = {
        "observation.add": ("PUT", "/api/me/health-observations"),
        "observation.edit": ("PUT", "/api/me/health-observations"),
        "observation.delete": ("DELETE", "/api/me/health-observations/" + str(review.get("target_id"))),
        "inventory.count": ("POST", "/api/me/inventory/" + str(review.get("target_id"))),
        "barrier.add": ("POST", "/api/me/adherence-barriers"),
        "followup.add": ("POST", "/api/me/care-tasks"),
    }
    return (*routes.get(capability, ("POST", "/api/me/care-tasks/" + str(review.get("target_id")))), values)


def save(h, view):
    method, path, values = patient_request(h, view)
    return h._request(method, path, headers=binding(view), **({"json": values} if method != "DELETE" else {}))


@pytest.mark.parametrize("capability", ["observation.add", "inventory.count", "barrier.add", "followup.add"])
def test_patient_confirmation_writes_once_and_completion_reads_the_actual_owned_record(workflow, capability):
    from .test_workflow_medication_management import active_plan

    h = workflow
    medicine = active_plan(h)
    task = prepared(h, capability, fields(h, capability, medicine))
    assert task["state"] == "awaiting_confirmation" and task["result_ref"]["kind"] == "care_review"
    result = save(h, task)
    assert save(h, task) == result
    complete = h.event(task["task_id"], "report_business_result")
    assert complete["state"] == "completed" and complete["visible_fields"]["saved_record"]
    assert complete["result_ref"]["kind"] != "care_review"
    if capability == "inventory.count":
        actual = h._request("GET", "/api/me/inventory/" + medicine["medication_id"])
        assert actual["last_confirmed_stock"] == 12 and len(actual["transactions"]) == 1


@pytest.mark.parametrize(
    "capability", ["followup.edit", "followup.contacted", "followup.complete", "followup.defer", "followup.cancel"]
)
def test_each_followup_operation_has_one_actual_history_change(workflow, capability):
    h = workflow
    original = h._request(
        "POST",
        "/api/me/care-tasks",
        json={
            "id": str(uuid4()),
            "category": "medication_review",
            "title": "DEMO followup",
            "due_at": (h.clock.now() + timedelta(days=2)).isoformat(),
            "reminder_minutes": None,
            "confirmed": True,
        },
    )
    task = prepared(h, capability, fields(h, capability, task=original))
    actual = save(h, task)
    assert save(h, task) == actual
    assert actual["version"] == 2 and len(actual["history"]) == 2
    assert actual["history"][0] == original["history"][0]
    assert h.event(task["task_id"], "report_business_result")["state"] == "completed"


def test_observation_deletion_requires_an_actual_patient_success_receipt(workflow):
    h = workflow
    original = h._request(
        "PUT",
        "/api/me/health-observations",
        json={
            "id": str(uuid4()),
            "description": "DEMO note to delete",
            "occurred_at": h.clock.now().isoformat(),
            "confirmed": True,
        },
    )
    task = prepared(h, "observation.delete", fields(h, "observation.delete", observation=original))
    assert save(h, task) == {"deleted": True}
    assert h.event(task["task_id"], "report_business_result")["state"] == "completed"


@pytest.mark.parametrize(
    "failure", ["no_save", "pause", "foreign", "half_binding", "changed_fields", "wrong_id", "not_confirmed"]
)
def test_invalid_patient_care_authority_never_saves(workflow, failure):
    h = workflow
    task = prepared(h, "observation.add", fields(h, "observation.add"))
    method, path, values = patient_request(h, task)
    if failure == "no_save":
        h.event(task["task_id"], "cancel_save")
    if failure == "pause":
        h.event(task["task_id"], "pause")
    if failure == "changed_fields":
        values["description"] = "DEMO changed after review"
    if failure == "wrong_id":
        values["id"] = str(uuid4())
    if failure == "not_confirmed":
        values["confirmed"] = False
    headers = binding(task)
    if failure == "half_binding":
        headers.pop("X-Assistant-Revision")
    response = h.client.request(
        method,
        path,
        params={"client_id": "DEMO-workflow-B" if failure == "foreign" else "DEMO-workflow-A"},
        json=values,
        headers=headers,
    )
    assert response.status_code in {404, 409, 422}
    assert not h._request("GET", "/api/me/health-observations")


def test_a_changed_observation_cannot_be_deleted_using_an_old_displayed_review(workflow):
    h = workflow
    note = h._request(
        "PUT",
        "/api/me/health-observations",
        json={
            "id": str(uuid4()),
            "description": "DEMO before",
            "occurred_at": h.clock.now().isoformat(),
            "confirmed": True,
        },
    )
    task = prepared(h, "observation.delete", fields(h, "observation.delete", observation=note))
    h.clock.advance(seconds=1)
    h._request(
        "PUT",
        "/api/me/health-observations",
        json={
            "id": note["id"],
            "description": "DEMO changed after review",
            "occurred_at": note["occurred_at"],
            "confirmed": True,
        },
    )
    method, path, _ = patient_request(h, task)
    response = h.client.request(method, path, params={"client_id": "DEMO-workflow-A"}, headers=binding(task))
    assert response.status_code == 409
    assert h._request("GET", "/api/me/health-observations")[0]["description"] == "DEMO changed after review"


def test_a_changed_inventory_requires_a_new_independent_review(workflow):
    from .test_workflow_medication_management import active_plan

    h = workflow
    med = active_plan(h)
    task = prepared(h, "inventory.count", fields(h, "inventory.count", med))
    h._request(
        "POST",
        "/api/me/inventory/" + med["medication_id"],
        json={"id": str(uuid4()), "kind": "count", "quantity": 20, "unit": "tablet", "confirmed": True},
    )
    method, path, body = patient_request(h, task)
    response = h.client.request(method, path, params={"client_id": "DEMO-workflow-A"}, json=body, headers=binding(task))
    assert response.status_code == 409
    assert h._request("GET", path)["last_confirmed_stock"] == 20


def test_failed_stock_save_can_be_corrected_after_actual_result_check(workflow):
    from .test_workflow_medication_management import active_plan

    h = workflow
    med = active_plan(h)
    draft = {**fields(h, "inventory.count", med), "kind": "refill"}
    task = prepared(h, "inventory.count", draft)
    method, path, body = patient_request(h, task)
    response = h.client.request(method, path, params={"client_id": "DEMO-workflow-A"}, json=body, headers=binding(task))
    assert response.status_code == 422
    checked = h.event(task["task_id"], "report_business_result")
    assert checked["state"] == "awaiting_confirmation"
    corrected = h.event(task["task_id"], "provide_fields", {"kind": "count", "quantity": 12})
    current = h.event(corrected["task_id"], "prepare_confirmation")
    save(h, current)
    assert h._request("GET", path)["last_confirmed_stock"] == 12


def test_existing_observation_edit_reuses_patient_api_and_retains_original_creation_time(workflow):
    h = workflow
    old = h._request(
        "PUT",
        "/api/me/health-observations",
        json={
            "id": str(uuid4()),
            "description": "DEMO prior note",
            "occurred_at": h.clock.now().isoformat(),
            "confirmed": True,
        },
    )
    h.clock.advance(seconds=1)
    task = prepared(
        h,
        "observation.edit",
        {"observation_id": old["id"], "description": "DEMO explicit correction", "occurred_at": old["occurred_at"]},
    )
    result = save(h, task)
    assert result["id"] == old["id"] and result["created_at"] == old["created_at"]
    assert result["description"] == "DEMO explicit correction"
    done = h.event(task["task_id"], "report_business_result")
    assert done["result_ref"]["kind"] == "observation" and done["state"] == "completed"


@pytest.mark.parametrize(
    "kind,quantity", [("count", 12), ("refill", 3), ("adjustment", -2), ("lost", 1), ("discarded", 1), ("damaged", 1)]
)
def test_each_existing_stock_change_kind_is_confirmed_and_changes_one_actual_ledger(workflow, kind, quantity):
    from .test_workflow_medication_management import active_plan

    h = workflow
    med = active_plan(h)
    if kind != "count":
        h._request(
            "POST",
            "/api/me/inventory/" + med["medication_id"],
            json={"id": str(uuid4()), "kind": "count", "quantity": 20, "unit": "tablet", "confirmed": True},
        )
    task = prepared(h, "inventory.count", {**fields(h, "inventory.count", med), "kind": kind, "quantity": quantity})
    result = save(h, task)
    expected = quantity if kind == "count" else 20 + quantity if kind in {"refill", "adjustment"} else 20 - quantity
    assert result["transactions"][-1]["stock_after"] == expected
    assert len(result["transactions"]) == (1 if kind == "count" else 2)
    assert h.event(task["task_id"], "report_business_result")["state"] == "completed"
