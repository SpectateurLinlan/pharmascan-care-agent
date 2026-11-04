"""Duplicate records require an owned selection; whole product names stay distinct."""

from uuid import UUID, uuid4

from .test_workflow_enrollment import message


def test_duplicate_record_is_a_fresh_owned_choice_and_cannot_be_set_as_an_ordinary_field(workflow):
    h = workflow
    existing = h.seed_reviewed_medication()
    first = h.start(
        "medication.enroll",
        {
            "method": "manual",
            "medication_name": "DEMO-workflow-medicine",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_rule": {"kind": "daily", "local_times": ["08:00"]},
        },
    )
    assert first["state"] == "collecting" and "existing_medication_choice" in first["missing_fields"]
    choice = next(action for action in first["actions"] if action.get("action_id") == "enrollment.duplicate")
    assert any(
        option["value"] == existing["medication_id"] and option["label_text"] == "DEMO-workflow-medicine"
        for option in choice["options"]
    )
    blocked = h.client.post(
        f"/api/agent/workflows/tasks/{first['task_id']}/events",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "event_id": str(uuid4()),
            "expected_revision": first["revision"],
            "kind": "provide_fields",
            "values": {"existing_medication_id": existing["medication_id"]},
        },
    )
    assert blocked.status_code == 422
    chosen = h.event(first["task_id"], "select_candidate", {"existing_medication_id": existing["medication_id"]})
    assert (
        chosen["state"] == "ready_for_review"
        and chosen["visible_fields"]["existing_medication_id"] == existing["medication_id"]
    )


def test_duplicate_choice_can_restart_product_name_without_merging_a_different_strength(workflow):
    h = workflow
    h.seed_reviewed_medication()
    first = h.start("medication.enroll", {"method": "manual", "medication_name": "DEMO-workflow-medicine"})
    different = h.event(first["task_id"], "select_candidate", {"choice": "different_product"})
    assert "medication_name" not in different["visible_fields"] and "medication_name" in different["missing_fields"]
    changed = message(h, "药名：DEMO-workflow-medicine 200mg；规格：200mg", different)["workflow"]
    assert (
        changed["visible_fields"]["medication_name"].endswith("200mg")
        and "existing_medication_id" not in changed["visible_fields"]
    )


def test_a_changed_selected_record_keeps_the_saved_task_readable_and_requests_a_new_choice(workflow):
    h = workflow
    existing = h.seed_reviewed_medication()
    first = h.start("medication.enroll", {"method": "manual", "medication_name": "DEMO-workflow-medicine"})
    chosen = h.event(first["task_id"], "select_candidate", {"existing_medication_id": existing["medication_id"]})
    key = (h.owner_ids["A"], UUID(existing["medication_id"]))
    row = h.container.store.medications[key]
    h.container.store.medications[key] = row.model_copy(update={"display_name": "DEMO renamed product"})
    current = h.view(chosen["task_id"])
    assert "existing_medication_choice" in current["missing_fields"]
    recovered = h.event(first["task_id"], "select_candidate", {"choice": "different_product"})
    assert "medication_name" in recovered["missing_fields"]


def test_foreign_or_unoffered_record_selection_is_rejected_without_changing_task(workflow):
    h = workflow
    first = h.start("medication.enroll", {"method": "manual", "medication_name": "DEMO new"})
    result = h.client.post(
        f"/api/agent/workflows/tasks/{first['task_id']}/events",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "event_id": str(uuid4()),
            "expected_revision": first["revision"],
            "kind": "select_candidate",
            "values": {"existing_medication_id": str(uuid4())},
        },
    )
    assert result.status_code == 422
    assert h.view(first["task_id"])["revision"] == first["revision"]


def test_initial_request_cannot_skip_the_explicit_record_choice(workflow):
    h = workflow
    existing = h.seed_reviewed_medication()
    result = h.client.post(
        "/api/agent/workflows/tasks",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "capability_id": "medication.enroll",
            "workspace_id": h.workspace_id,
            "client_event_id": str(uuid4()),
            "values": {
                "method": "manual",
                "medication_name": "DEMO-workflow-medicine",
                "existing_medication_id": existing["medication_id"],
            },
        },
    )
    assert result.status_code == 422


def test_every_matching_record_is_offered_with_a_distinguishable_label(workflow):
    h = workflow
    for _ in range(11):
        h.seed_reviewed_medication()
    first = h.start("medication.enroll", {"method": "manual", "medication_name": "DEMO-workflow-medicine"})
    options = [
        option
        for action in first["actions"]
        if action.get("action_id") == "enrollment.duplicate"
        for option in action["options"]
        if option["value"] != "different_product"
    ]
    assert len(options) == 11 and len({option["label_text"] for option in options}) == 11


def test_explicitly_different_recorded_strength_can_create_a_separate_owned_product(workflow):
    h = workflow
    old = h._request(
        "POST",
        "/api/medications/drafts",
        json={
            "medication_name": "DEMO same generic",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_kind": "daily",
            "frequency_local_times": ["08:00"],
            "dose_basis": {"strength_text": "400 mg"},
        },
    )
    first = h.start(
        "medication.enroll",
        {
            "method": "manual",
            "medication_name": "DEMO same generic",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "dose_basis": {"strength_text": "200mg"},
            "frequency_rule": {"kind": "daily", "local_times": ["08:00"]},
        },
    )
    assert any(
        option["value"] == "distinct_product"
        for action in first["actions"]
        if action.get("action_id") == "enrollment.duplicate"
        for option in action["options"]
    )
    chosen = h.event(first["task_id"], "select_candidate", {"choice": "distinct_product"})
    assert chosen["state"] == "ready_for_review"
    prepared = h.event(first["task_id"], "prepare_confirmation")
    new = h.container.enrollment.get_regimen(h.owner_ids["A"], UUID(prepared["result_ref"]["id"]))
    assert str(new.patient_medication_id) != old["medication_id"] and len(h.snapshot()["medications"]) == 2


def test_equivalent_or_unknown_strengths_cannot_be_declared_distinct_by_a_client_flag(workflow):
    h = workflow
    h._request(
        "POST",
        "/api/medications/drafts",
        json={"medication_name": "DEMO equivalent", "dose_basis": {"strength_text": "200.0 mg"}},
    )
    first = h.start(
        "medication.enroll",
        {"method": "manual", "medication_name": "DEMO equivalent", "dose_basis": {"strength_text": "200mg"}},
    )
    response = h.client.post(
        f"/api/agent/workflows/tasks/{first['task_id']}/events",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "event_id": str(uuid4()),
            "expected_revision": first["revision"],
            "kind": "select_candidate",
            "values": {"choice": "distinct_product"},
        },
    )
    assert response.status_code == 422 and len(h.snapshot()["medications"]) == 1


def test_selected_record_accepts_case_and_fullwidth_typing_without_changing_its_owned_name(workflow):
    h = workflow
    existing = h.seed_reviewed_medication()
    typed = "".join(chr(ord(char) + 65248) if 33 <= ord(char) <= 126 else char for char in "DEMO-WORKFLOW-MEDICINE")
    first = h.start(
        "medication.enroll",
        {
            "method": "manual",
            "medication_name": typed,
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_rule": {"kind": "daily", "local_times": ["08:00"]},
        },
    )
    chosen = h.event(first["task_id"], "select_candidate", {"existing_medication_id": existing["medication_id"]})
    prepared = h.event(first["task_id"], "prepare_confirmation")
    assert (
        chosen["state"] == "ready_for_review"
        and prepared["visible_fields"]["medication_name"] == "DEMO-workflow-medicine"
    )
    assert len(h.snapshot()["medications"]) == 1
