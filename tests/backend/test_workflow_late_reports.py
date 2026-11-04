"""DEMO_ONLY historical patient UI; real policies and append-only reports."""

from uuid import UUID, uuid4

import pytest

from .test_workflow_medication_management import active_plan
from .test_workflow_records import clinical as clinical_records
from .test_workflow_report_bindings import headers


def clinical(h):
    return {**clinical_records(h), "late_reports": dict(h.container.store.late_reports)}


def existing_occurrence(h):
    old = active_plan(h)
    h.container.schedule.materialize(patient_id=h.owner_ids["A"], regimen_id=UUID(old["regimen_id"]), days=1)
    h.clock.advance(hours=24)
    rows = h.container.schedule.existing_occurrences(
        h.owner_ids["A"], UUID(old["regimen_id"]), h.clock.now().replace(hour=0), h.clock.now()
    )
    if not rows:
        from datetime import timedelta

        rows = h.container.schedule.existing_occurrences(
            h.owner_ids["A"], UUID(old["regimen_id"]), h.clock.now() - timedelta(days=2), h.clock.now()
        )
    assert rows
    return rows[0]


def prepared(h, occurrence, capability="dose.late.review"):
    current = h.container.late_reports.occurrence(h.owner_ids["A"], occurrence.id)
    audit = h.container.late_reports.audit(h.owner_ids["A"], occurrence.id)
    start = h.start(
        capability,
        {
            "occurrence_id": str(occurrence.id),
            "expected_version": len(audit.corrections) + 1,
            "expected_report_id": str(current.report_id) if current.report_id else None,
        },
    )
    return h.event(start["task_id"], "prepare_confirmation")


def body(expected=None):
    return {
        "id": str(uuid4()),
        "intake_status": "reported_taken",
        "reason": "forgot_to_record",
        "notes": "DEMO synthetic patient report",
        "expected_report_id": expected,
    }


def path(occurrence):
    return f"/api/me/doses/{occurrence.id}/late-report"


def test_pure_historical_picker_never_materializes_or_issues_confirmation(workflow):
    h = workflow
    existing_occurrence(h)
    before = clinical(h)
    task = h.start("dose.late.review", {})
    assert task["actions"][0]["action_id"] == "late.target"
    h.view(task["task_id"])
    assert clinical(h) == before


def test_late_and_correction_independent_confirm_preserves_original_and_reads_actual_result(workflow):
    h = workflow
    occurrence = existing_occurrence(h)
    original = dict(h.container.store.events)
    first = prepared(h, occurrence)
    before = clinical(h)
    assert first["actions"][0]["component_key"] == "existing_late_report"
    values = body()
    summary = h._request("POST", path(occurrence) + "/challenge", json=values, headers=headers(first))
    assert clinical(h)["late_reports"] == before["late_reports"]
    payload = {"report": values, "challenge_id": summary["challenge_id"]}
    report = h._request("POST", path(occurrence), json=payload, headers=headers(first))
    assert not report["ingestion_proven"]
    assert h._request("POST", path(occurrence), json=payload, headers=headers(first)) == report
    complete = h.event(first["task_id"], "report_business_result")
    assert complete["state"] == "completed" and complete["result_ref"]["id"] == report["id"]
    correction = prepared(h, occurrence, "dose.correction.review")
    values2 = {**body(report["id"]), "intake_status": "unsure", "reason": "correcting_record"}
    summary2 = h._request("POST", path(occurrence) + "/challenge", json=values2, headers=headers(correction))
    saved2 = h._request(
        "POST",
        path(occurrence),
        json={"report": values2, "challenge_id": summary2["challenge_id"]},
        headers=headers(correction),
    )
    assert saved2["version"] == 2 and h.container.store.events == original
    audit = h._request("GET", path(occurrence) + "s")
    assert [row["intake_status"] for row in audit["corrections"]] == ["reported_taken", "unsure"]
    assert h.event(correction["task_id"], "report_business_result")["state"] == "completed"


@pytest.mark.parametrize("failure", ["no_save", "pause", "foreign_owner", "half_binding", "changed_body"])
def test_changed_or_unowned_patient_review_cannot_append(workflow, failure):
    h = workflow
    occurrence = existing_occurrence(h)
    task = prepared(h, occurrence)
    values = body()
    summary = h._request("POST", path(occurrence) + "/challenge", json=values, headers=headers(task))
    if failure == "no_save":
        h.event(task["task_id"], "cancel_save")
    if failure == "pause":
        h.event(task["task_id"], "pause")
    if failure == "changed_body":
        values["notes"] = "DEMO changed after review"
    binding = headers(task)
    if failure == "half_binding":
        binding.pop("X-Assistant-Revision")
    before = clinical(h)
    response = h.client.post(
        path(occurrence),
        params={"client_id": "DEMO-workflow-B" if failure == "foreign_owner" else "DEMO-workflow-A"},
        headers=binding,
        json={"report": values, "challenge_id": summary["challenge_id"]},
    )
    assert response.status_code in {404, 409, 422} and clinical(h) == before


def test_legacy_confirmation_cannot_be_adopted(workflow):
    h = workflow
    occurrence = existing_occurrence(h)
    values = body()
    h._request("POST", path(occurrence) + "/challenge", json=values)
    task = prepared(h, occurrence)
    before = clinical(h)
    response = h.client.post(
        path(occurrence) + "/challenge", params={"client_id": "DEMO-workflow-A"}, json=values, headers=headers(task)
    )
    assert response.status_code == 409 and clinical(h) == before


def test_competing_correction_summaries_cannot_overwrite_the_current_generation(workflow):
    h = workflow
    occurrence = existing_occurrence(h)
    first = prepared(h, occurrence)
    values = body()
    summary = h._request("POST", path(occurrence) + "/challenge", json=values, headers=headers(first))
    h._request(
        "POST",
        path(occurrence),
        json={"report": values, "challenge_id": summary["challenge_id"]},
        headers=headers(first),
    )
    a = prepared(h, occurrence, "dose.correction.review")
    h.workspace_id = str(uuid4())  # Independent patient page; starting in the same page suspends its predecessor.
    b = prepared(h, occurrence, "dose.correction.review")
    changes = [{**body(values["id"]), "intake_status": "unsure", "reason": "correcting_record"} for _ in range(2)]
    summaries = [
        h._request("POST", path(occurrence) + "/challenge", json=row, headers=headers(task))
        for row, task in zip(changes, (a, b), strict=True)
    ]
    h._request(
        "POST",
        path(occurrence),
        json={"report": changes[0], "challenge_id": summaries[0]["challenge_id"]},
        headers=headers(a),
    )
    before = clinical(h)
    response = h.client.post(
        path(occurrence),
        params={"client_id": "DEMO-workflow-A"},
        json={"report": changes[1], "challenge_id": summaries[1]["challenge_id"]},
        headers=headers(b),
    )
    assert response.status_code == 409 and clinical(h) == before
    assert len(h.container.late_reports.audit(h.owner_ids["A"], occurrence.id).corrections) == 2


def test_response_check_without_a_report_fences_the_old_summary(workflow):
    h = workflow
    occurrence = existing_occurrence(h)
    task = prepared(h, occurrence)
    values = body()
    summary = h._request("POST", path(occurrence) + "/challenge", json=values, headers=headers(task))
    latest = h.event(task["task_id"], "report_business_result")
    assert latest["state"] == "awaiting_confirmation"
    response = h.client.post(
        path(occurrence),
        params={"client_id": "DEMO-workflow-A"},
        json={"report": values, "challenge_id": summary["challenge_id"]},
        headers=headers(latest),
    )
    assert response.status_code == 409 and not h.container.store.late_reports


def test_patient_only_inputs_and_false_completion_are_not_model_authority(workflow):
    from app.contracts.assistant_workflows import validate_workflow_values
    from pydantic import ValidationError

    for capability in ("dose.late.review", "dose.correction.review"):
        for field in (
            "patient_id",
            "intake_status",
            "actual_administration_at",
            "notes",
            "reason",
            "challenge_id",
            "confirmed",
        ):
            with pytest.raises(ValidationError):
                validate_workflow_values(capability, {field: "DEMO"})
    h = workflow
    occurrence = existing_occurrence(h)
    task = prepared(h, occurrence)
    response = h.client.post(
        f"/api/agent/workflows/tasks/{task['task_id']}/events",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "event_id": str(uuid4()),
            "expected_revision": task["revision"],
            "kind": "report_business_result",
            "values": {"success": True},
        },
    )
    assert response.status_code == 422 and not h.container.store.late_reports


def test_correcting_an_original_current_report_retains_its_exact_original_event(workflow):
    h = workflow
    old = active_plan(h)
    h.clock.advance(hours=13)
    due = h._request("GET", "/api/doses/due", params={"regimen_id": old["regimen_id"]})
    occurrence = h.container.schedule.get_occurrence(h.owner_ids["A"], UUID(due["occurrence_id"]))
    values = {"regimen_id": old["regimen_id"], "intake_status": "taken", "idempotency_key": "report-" + str(uuid4())}
    summary = h._request("POST", f"/api/doses/{occurrence.id}/report/challenge", json=values)
    event = h._request(
        "POST", f"/api/doses/{occurrence.id}/report", json={**values, "challenge_id": summary["challenge_id"]}
    )
    original = dict(h.container.store.events)
    h.clock.advance(hours=24)
    task = prepared(h, occurrence, "dose.correction.review")
    correction = {**body(event["event_id"]), "intake_status": "unsure", "reason": "correcting_record"}
    review = h._request("POST", path(occurrence) + "/challenge", json=correction, headers=headers(task))
    h._request(
        "POST",
        path(occurrence),
        json={"report": correction, "challenge_id": review["challenge_id"]},
        headers=headers(task),
    )
    assert h.container.store.events == original
    audit = h.container.late_reports.audit(h.owner_ids["A"], occurrence.id)
    assert str(audit.original.id) == event["event_id"] and len(audit.corrections) == 1


@pytest.mark.parametrize(
    "text,capability",
    [
        ("record a late dose", "dose.late.review"),
        ("\u8865\u8bb0\u670d\u836f", "dose.late.review"),
        ("correct a dose report", "dose.correction.review"),
        ("\u66f4\u6b63\u670d\u836f\u8bb0\u5f55", "dose.correction.review"),
    ],
)
def test_chat_entry_is_available_as_patient_ui_only(workflow, text, capability):
    from .test_workflow_enrollment import message

    h = workflow
    reply = message(h, text)
    assert reply["workflow"]["capability_id"] == capability
    manifest = h._request("GET", "/api/agent/workflows/capabilities")
    entry = next(row for row in manifest["capabilities"] if row["id"] == capability)
    assert entry["available"] and entry["mode"] == "patient_ui"
