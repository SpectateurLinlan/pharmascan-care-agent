"""Synthetic independent patient report actions, real application/HTTP policy."""

from uuid import UUID, uuid4

import pytest

from .test_workflow_records import clinical


def prn_plan(h):
    from .test_workflow_draft_recovery import activate, challenge

    session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})
    draft = h._request(
        "POST",
        "/api/medications/drafts",
        json={
            "medication_name": "DEMO workflow PRN",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "is_prn": True,
            "food_instruction": "DEMO original as-needed instructions",
        },
    )
    ref = {"id": draft["regimen_id"]}
    summary = challenge(h, ref, session["session_id"])
    assert activate(h, ref, summary).status_code == 200
    return draft


def report_engine(h):
    from app.application.assistant_capabilities.reports import PatientReportAdapter
    from app.application.assistant_workflows import WorkflowService
    from app.application.workflow_reports import WorkflowDoseReportService
    from app.infrastructure.clinical_memory import MemoryClinicalMutationGuard
    from app.infrastructure.memory_workflows import MemoryActionRepository

    old = h.container.assistant_workflows
    actions = MemoryActionRepository(h.clock, state=old._repository._state)
    adapter = PatientReportAdapter(
        enrollment=h.container.enrollment,
        reports=h.container.self_report,
        schedule=h.container.schedule,
        actions=actions,
        clinical=MemoryClinicalMutationGuard(h.container.store.clinical),
        clock=h.clock,
    )
    service = WorkflowService(
        repository=old._repository,
        registry=old._registry,
        adapters={**old._adapters, **dict.fromkeys(adapter.capability_ids, adapter)},
        writers={**old._writers, **dict.fromkeys(adapter.capability_ids, adapter)},
        patient_guards={**old._patient_guards, **dict.fromkeys(adapter.capability_ids, adapter)},
        patient_results={**old._patient_results, **dict.fromkeys(adapter.capability_ids, adapter)},
        clock=h.clock,
        ids=h.container.ids,
        conversations=h.container.conversation_threads,
        preferences=h.container.preferences,
        controls=old._controls,
    )
    h.container.assistant_workflows = service
    h.container.assistant_reports = WorkflowDoseReportService(workflows=service, adapter=adapter)
    return service


def prepared(h, old, capability="dose.prn.report"):
    report_engine(h)
    started = h.start(capability, {"regimen_id": old["regimen_id"], "expected_version": 1})
    return h.event(started["task_id"], "prepare_confirmation")


def headers(view):
    return {"X-Assistant-Task": view["task_id"], "X-Assistant-Revision": str(view["revision"])}


def choice(old):
    return {"regimen_id": old["regimen_id"], "intake_status": "taken", "idempotency_key": "report-" + str(uuid4())}


def test_preparing_a_report_binds_only_the_owned_plan_without_a_challenge_or_event(workflow):
    h = workflow
    old = prn_plan(h)
    before = clinical(h)
    saved = prepared(h, old)
    assert saved["state"] == "awaiting_confirmation" and saved["actions"][0]["component_key"] == "existing_self_report"
    assert clinical(h) == before


def test_prn_report_requires_independent_patient_confirmation_then_reads_actual_event(workflow):
    h = workflow
    old = prn_plan(h)
    saved = prepared(h, old)
    values = choice(old)
    challenge = h._request("POST", "/api/prn/report/challenge", json=values, headers=headers(saved))
    assert h.snapshot()["dose_events"] == []
    result = h._request(
        "POST", "/api/prn/report", json={**values, "challenge_id": challenge["challenge_id"]}, headers=headers(saved)
    )
    assert result["event_id"] and result["ingestion_proven"] is False
    complete = h.event(saved["task_id"], "report_business_result")
    assert complete["state"] == "completed" and complete["result_ref"]["kind"] == "dose_event"
    assert complete["result_ref"]["id"] == result["event_id"] and len(h.snapshot()["dose_events"]) == 1


def test_revoked_saving_blocks_an_old_patient_challenge_request(workflow):
    h = workflow
    old = prn_plan(h)
    saved = prepared(h, old)
    h.event(saved["task_id"], "cancel_save")
    before = clinical(h)
    response = h.client.post(
        "/api/prn/report/challenge", params={"client_id": "DEMO-workflow-A"}, json=choice(old), headers=headers(saved)
    )
    assert response.status_code == 409 and clinical(h) == before


def test_revised_task_rejects_the_previously_issued_report_challenge(workflow):
    h = workflow
    old = prn_plan(h)
    saved = prepared(h, old)
    values = choice(old)
    challenge = h._request("POST", "/api/prn/report/challenge", json=values, headers=headers(saved))
    h.event(saved["task_id"], "pause")
    current = h.event(saved["task_id"], "resume")
    before = clinical(h)
    response = h.client.post(
        "/api/prn/report",
        params={"client_id": "DEMO-workflow-A"},
        json={**values, "challenge_id": challenge["challenge_id"]},
        headers=headers(current),
    )
    assert response.status_code == 409 and clinical(h) == before


def test_a_legacy_or_other_task_challenge_cannot_be_adopted_by_a_prepared_report(workflow):
    h = workflow
    old = prn_plan(h)
    values = choice(old)
    h._request("POST", "/api/prn/report/challenge", json=values)
    saved = prepared(h, old)
    before = clinical(h)
    response = h.client.post(
        "/api/prn/report/challenge", params={"client_id": "DEMO-workflow-A"}, json=values, headers=headers(saved)
    )
    assert response.status_code == 409 and clinical(h) == before


def test_lost_report_response_replays_one_actual_event_without_another_confirmation(workflow):
    h = workflow
    old = prn_plan(h)
    saved = prepared(h, old)
    values = choice(old)
    challenge = h._request("POST", "/api/prn/report/challenge", json=values, headers=headers(saved))
    payload = {**values, "challenge_id": challenge["challenge_id"]}
    first = h._request("POST", "/api/prn/report", json=payload, headers=headers(saved))
    second = h._request("POST", "/api/prn/report", json=payload, headers=headers(saved))
    assert first["event_id"] == second["event_id"] and second["already_recorded"]
    assert len(h.snapshot()["dose_events"]) == 1


def test_client_success_and_event_ids_cannot_establish_a_patient_report(workflow):
    h = workflow
    old = prn_plan(h)
    saved = prepared(h, old)
    response = h.client.post(
        f"/api/agent/workflows/tasks/{saved['task_id']}/events",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "event_id": str(uuid4()),
            "expected_revision": saved["revision"],
            "kind": "report_business_result",
            "values": {"success": True, "event_id": str(uuid4())},
        },
    )
    assert response.status_code == 422 and not h.snapshot()["dose_events"]


def test_scheduled_report_uses_the_actual_owned_occurrence_without_reconstructing_history(workflow):
    from .test_workflow_medication_management import active_plan

    h = workflow
    old = active_plan(h)
    h.container.schedule.materialize(patient_id=h.owner_ids["A"], regimen_id=UUID(old["regimen_id"]), days=1)
    h.clock.advance(hours=13)
    due = h._request("GET", "/api/doses/due", params={"regimen_id": old["regimen_id"]})
    occurrence = due["occurrence_id"]
    assert occurrence
    before = clinical(h)
    saved = prepared(h, old, "dose.report")
    assert clinical(h) == before
    values = choice(old)
    path = f"/api/doses/{occurrence}/report"
    challenge = h._request("POST", path + "/challenge", json=values, headers=headers(saved))
    result = h._request(
        "POST", path, json={**values, "challenge_id": challenge["challenge_id"]}, headers=headers(saved)
    )
    complete = h.event(saved["task_id"], "report_business_result")
    assert complete["result_ref"]["id"] == result["event_id"] and complete["state"] == "completed"
    assert len(h.snapshot()["dose_events"]) == 1


@pytest.mark.parametrize(
    "failure", ["foreign_owner", "half_binding", "wrong_route", "stopped", "revoked_after_summary"]
)
def test_wrong_or_changed_patient_report_authority_never_records_an_event(workflow, failure):
    h = workflow
    old = prn_plan(h)
    saved = prepared(h, old)
    values = choice(old)
    challenge = h._request("POST", "/api/prn/report/challenge", json=values, headers=headers(saved))
    if failure == "stopped":
        h.container.enrollment.end_regimen(patient_id=h.owner_ids["A"], regimen_id=UUID(old["regimen_id"]))
    if failure == "revoked_after_summary":
        h.event(saved["task_id"], "cancel_save")
    binding = headers(saved)
    if failure == "half_binding":
        binding.pop("X-Assistant-Revision")
    path = f"/api/doses/{uuid4()}/report" if failure == "wrong_route" else "/api/prn/report"
    before = clinical(h)
    response = h.client.post(
        path,
        params={"client_id": "DEMO-workflow-B" if failure == "foreign_owner" else "DEMO-workflow-A"},
        json={**values, "challenge_id": challenge["challenge_id"]},
        headers=binding,
    )
    assert response.status_code in {404, 409, 422} and clinical(h) == before


def test_model_fields_cannot_supply_the_patient_status_key_or_confirmation():
    from app.contracts.assistant_workflows import validate_workflow_values
    from pydantic import ValidationError

    for name in ("patient_id", "intake_status", "confirmed", "challenge_id", "idempotency_key"):
        with pytest.raises(ValidationError):
            validate_workflow_values("dose.prn.report", {name: "DEMO"})


def test_workflow_and_action_metadata_never_expose_an_executable_confirmation(workflow):
    import json

    h = workflow
    old = prn_plan(h)
    saved = prepared(h, old)
    values = choice(old)
    challenge = h._request("POST", "/api/prn/report/challenge", json=values, headers=headers(saved))
    assert challenge["challenge_id"]
    actual = h.view(saved["task_id"])
    serialized = json.dumps(actual)
    for forbidden in ("challenge_id", "token_hash", "session_state_version", "intended_intake_status"):
        assert forbidden not in serialized
    assert not h.snapshot()["dose_events"]


def test_failed_challenge_binding_cannot_be_treated_as_a_report_or_adopted_on_retry(workflow, monkeypatch):
    h = workflow
    old = prn_plan(h)
    saved = prepared(h, old)
    values = choice(old)
    adapter = h.container.assistant_workflows._adapters["dose.prn.report"]
    original = adapter.actions.complete

    def unavailable(context, receipt):
        if receipt.safe_reason is None and receipt.binding_revision == saved["revision"]:
            raise OSError("DEMO challenge binding unavailable")
        return original(context, receipt)

    monkeypatch.setattr(adapter.actions, "complete", unavailable)
    with pytest.raises(OSError):
        h._request("POST", "/api/prn/report/challenge", json=values, headers=headers(saved))
    monkeypatch.setattr(adapter.actions, "complete", original)
    response = h.client.post(
        "/api/prn/report/challenge", params={"client_id": "DEMO-workflow-A"}, json=values, headers=headers(saved)
    )
    assert response.status_code == 409 and not h.snapshot()["dose_events"]
    assert h.event(saved["task_id"], "report_business_result")["state"] == "awaiting_confirmation"


@pytest.mark.parametrize(
    "phrase,capability",
    [
        ("record a dose", "dose.report"),
        ("记录服药自述", "dose.report"),
        ("record an as-needed dose", "dose.prn.report"),
        ("记录按需服药自述", "dose.prn.report"),
    ],
)
def test_chat_starts_only_patient_report_preparation_without_creating_a_report(workflow, phrase, capability):
    from .test_workflow_enrollment import message

    h = workflow
    prn_plan(h)
    before = clinical(h)
    response = message(h, phrase)
    assert response["reply"]["mode"] == "workflow" and response["workflow"]["capability_id"] == capability
    assert clinical(h) == before


def test_status_read_fences_old_unsubmitted_confirmation_before_a_fresh_patient_review(workflow):
    h = workflow
    old = prn_plan(h)
    saved = prepared(h, old)
    values = choice(old)
    summary = h._request("POST", "/api/prn/report/challenge", json=values, headers=headers(saved))
    checked = h.event(saved["task_id"], "report_business_result")
    assert checked["state"] == "awaiting_confirmation" and checked["revision"] > saved["revision"]
    for binding in (saved, checked):
        response = h.client.post(
            "/api/prn/report",
            params={"client_id": "DEMO-workflow-A"},
            json={**values, "challenge_id": summary["challenge_id"]},
            headers=headers(binding),
        )
        assert response.status_code == 409 and not h.snapshot()["dose_events"]
    fresh = choice(old)
    new = h._request("POST", "/api/prn/report/challenge", json=fresh, headers=headers(checked))
    h._request("POST", "/api/prn/report", json={**fresh, "challenge_id": new["challenge_id"]}, headers=headers(checked))
    assert h.event(saved["task_id"], "report_business_result")["state"] == "completed"
    assert len(h.snapshot()["dose_events"]) == 1


def test_noncanonical_patient_key_is_rejected_before_creating_an_unreconcilable_challenge(workflow):
    h = workflow
    old = prn_plan(h)
    saved = prepared(h, old)
    values = choice(old)
    values["idempotency_key"] = "report-AAAAAAAA-0000-4000-8000-000000000099"
    before = clinical(h)
    response = h.client.post(
        "/api/prn/report/challenge", params={"client_id": "DEMO-workflow-A"}, json=values, headers=headers(saved)
    )
    assert response.status_code == 422 and clinical(h) == before
