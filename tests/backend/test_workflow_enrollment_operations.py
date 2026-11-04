"""Actual DEMO memory transactions; no workflow flags stand in for business rows."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4, uuid5

import pytest
from app.application.enrollment_operations import EnrollmentOperationService
from app.contracts.enrollment_operations import EnrollmentOperationInput
from app.contracts.enrollment_workflow import EnrollmentFields
from app.domain.errors import DuplicateEventError, StaleVersionError, ValidationError
from app.infrastructure.enrollment_operations import InMemoryEnrollmentWritePort


def services(h):
    writer = InMemoryEnrollmentWritePort(h.container.store)
    return EnrollmentOperationService(h.container.enrollment, writer), writer


def values(**changes):
    return EnrollmentOperationInput(
        action_key=uuid4(),
        fields=EnrollmentFields.model_validate(
            {
                "method": "manual",
                "medication_name": "DEMO transactional product",
                "dose_amount": 1,
                "dose_unit": "tablet",
                "frequency_rule": {"kind": "daily", "local_times": ["08:00"]},
                **changes,
            }
        ),
    )


def test_response_loss_replay_returns_the_same_real_unactivated_aggregate(workflow):
    h = workflow
    service, _ = services(h)
    request = values()
    owner = h.owner_ids["A"]
    first = service.prepare_once(owner, request)
    replay = service.prepare_once(owner, request)
    assert first.regimen.id == replay.regimen.id and replay.medication.id == first.medication.id
    assert replay.regimen.state.value == "draft"
    snap = h.snapshot()
    assert len(snap["medications"]) == len(snap["regimens"]) == 1
    assert len(h.container.store.sources) == 1 and not snap["dose_events"]
    assert service.lookup(h.owner_ids["B"], request.action_key) is None


def test_same_key_changed_inputs_cannot_create_or_replace_a_draft(workflow):
    h = workflow
    service, _ = services(h)
    request = values()
    owner = h.owner_ids["A"]
    first = service.prepare_once(owner, request)
    changed = request.model_copy(update={"fields": request.fields.model_copy(update={"dose_amount": 2})})
    with pytest.raises(DuplicateEventError):
        service.prepare_once(owner, changed)
    assert service.lookup(owner, request.action_key).regimen.id == first.regimen.id
    assert len(h.snapshot()["regimens"]) == 1


def test_simultaneous_requests_share_the_business_receipt_and_one_aggregate(workflow):
    h = workflow
    service, _ = services(h)
    request = values()
    owner = h.owner_ids["A"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: service.prepare_once(owner, request), range(2)))
    assert rows[0].regimen.id == rows[1].regimen.id
    assert len(h.snapshot()["regimens"]) == len(h.snapshot()["medications"]) == 1


def test_validation_failure_leaves_no_business_rows_or_receipt(workflow):
    h = workflow
    service, _ = services(h)
    request = values(frequency_rule={"kind": "daily", "local_times": ["24:00"]})
    with pytest.raises(ValidationError):
        service.prepare_once(h.owner_ids["A"], request)
    assert service.lookup(h.owner_ids["A"], request.action_key) is None
    assert not h.snapshot()["regimens"] and not h.container.store.sources


def test_current_owner_clinical_revision_is_checked_before_publishing(workflow):
    h = workflow
    _, writer = services(h)
    owner = h.owner_ids["A"]
    request = values()
    revision = writer.revision(owner)
    prepared = h.container.enrollment.prepare_draft(patient_id=owner, draft=request.fields.draft)
    h.seed_reviewed_medication()
    with pytest.raises(StaleVersionError):
        writer.create_once(owner, request.action_key, "0" * 64, prepared, expected_revision=revision)
    assert writer.lookup(owner, request.action_key) is None
    assert len(h.snapshot()["regimens"]) == 1


def ready(h, save=True):
    return h.start("medication.enroll", values().fields.model_dump(mode="json", exclude_none=True), save=save)


def test_explicit_workflow_preparation_binds_one_unactivated_draft_and_replays_after_response_loss(workflow):
    h = workflow
    first = ready(h)
    event = str(uuid4())
    prepared = h.event(first["task_id"], "prepare_confirmation", revision=first["revision"], event_id=event)
    assert prepared["state"] == "awaiting_confirmation" and prepared["result_ref"]["kind"] == "regimen"
    assert prepared["actions"][0]["component_key"] == "existing_activation"
    replay = h.event(first["task_id"], "prepare_confirmation", revision=first["revision"], event_id=event)
    assert replay["result_ref"] == prepared["result_ref"]
    assert len(h.snapshot()["regimens"]) == 1 and h.snapshot()["regimens"][0]["state"] == "draft"


def test_no_save_workflow_cannot_prepare_any_clinical_draft(workflow):
    h = workflow
    first = ready(h, False)
    result = h.client.post(
        f"/api/agent/workflows/tasks/{first['task_id']}/events",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "event_id": str(uuid4()),
            "expected_revision": first["revision"],
            "kind": "prepare_confirmation",
            "values": {},
            "ephemeral": {"capability_id": "medication.enroll", "fields": first["visible_fields"]},
        },
    )
    assert result.status_code == 422 and not h.snapshot()["regimens"]


def test_completion_observes_the_existing_independent_review_challenge_and_activation(workflow):
    h = workflow
    session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})
    first = ready(h)
    prepared = h.event(first["task_id"], "prepare_confirmation")
    regimen_id = prepared["result_ref"]["id"]
    pending = h.event(first["task_id"], "report_business_result")
    assert pending["state"] == "awaiting_confirmation"
    draft = h._request("GET", f"/api/medications/drafts/{regimen_id}")
    h._request("POST", f"/api/medications/drafts/{draft['source_id']}/review", json={"field_ids": None})
    challenge = h._request(
        "POST", f"/api/medications/drafts/{regimen_id}/challenge", params={"session_id": session["session_id"]}, json={}
    )
    h._request(
        "POST",
        "/api/medications/activate",
        json={
            "regimen_id": regimen_id,
            **{key: challenge[key] for key in ("challenge_id", "session_id", "session_state", "session_state_version")},
        },
    )
    observed = h.event(first["task_id"], "report_business_result")
    assert observed["state"] == "completed" and len(h.snapshot()["regimens"]) == 1


def test_client_report_cannot_supply_success_or_a_business_id(workflow):
    h = workflow
    first = ready(h)
    prepared = h.event(first["task_id"], "prepare_confirmation")
    result = h.client.post(
        f"/api/agent/workflows/tasks/{first['task_id']}/events",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "event_id": str(uuid4()),
            "expected_revision": prepared["revision"],
            "kind": "report_business_result",
            "values": {"state": "active", "regimen_id": str(uuid4())},
        },
    )
    assert result.status_code == 422 and h.snapshot()["regimens"][0]["state"] == "draft"


def test_correcting_prepared_inputs_invalidates_review_and_reuses_the_owned_medication(workflow):
    h = workflow
    first = ready(h)
    prepared = h.event(first["task_id"], "prepare_confirmation")
    old = prepared["result_ref"]["id"]
    changed = h.event(first["task_id"], "provide_fields", {"dose_amount": 2})
    assert changed["state"] == "ready_for_review" and changed["result_ref"] is None
    newer = h.event(first["task_id"], "prepare_confirmation")
    assert newer["result_ref"]["id"] != old
    assert len(h.snapshot()["medications"]) == 1 and len(h.snapshot()["regimens"]) == 2
    assert all(row["state"] == "draft" for row in h.snapshot()["regimens"])


def test_revoked_workflow_cannot_finish_a_previously_issued_activation(workflow):
    h = workflow
    session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})
    first = ready(h)
    prepared = h.event(first["task_id"], "prepare_confirmation")
    regimen_id = prepared["result_ref"]["id"]
    draft = h._request("GET", f"/api/medications/drafts/{regimen_id}")
    h._request("POST", f"/api/medications/drafts/{draft['source_id']}/review", json={"field_ids": None})
    challenge = h._request(
        "POST", f"/api/medications/drafts/{regimen_id}/challenge", params={"session_id": session["session_id"]}, json={}
    )
    h.event(first["task_id"], "cancel_save")
    response = h.client.post(
        "/api/medications/activate",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "regimen_id": regimen_id,
            **{key: challenge[key] for key in ("challenge_id", "session_id", "session_state", "session_state_version")},
        },
    )
    assert response.status_code in {409, 422}
    assert h.snapshot()["regimens"][0]["state"] == "draft"


def test_prior_preparation_cannot_be_reviewed_after_task_inputs_change(workflow):
    h = workflow
    first = ready(h)
    prepared = h.event(first["task_id"], "prepare_confirmation")
    draft = h._request("GET", f"/api/medications/drafts/{prepared['result_ref']['id']}")
    h.event(first["task_id"], "provide_fields", {"dose_amount": 2})
    response = h.client.post(
        f"/api/medications/drafts/{draft['source_id']}/review",
        params={"client_id": "DEMO-workflow-A"},
        json={"field_ids": None},
    )
    assert response.status_code in {409, 422}
    assert h.container.enrollment.get_source(h.owner_ids["A"], UUID(draft["source_id"])).reviewed_at is None


def test_business_success_followed_by_metadata_failure_recovers_the_same_business_receipt(workflow, monkeypatch):
    h = workflow
    first = ready(h)
    service = h.container.assistant_workflows
    repository = service._repository
    original = repository.cas

    def lost_metadata(*args, **kwargs):
        raise RuntimeError("DEMO metadata failure after business publication")

    monkeypatch.setattr(repository, "cas", lost_metadata)
    with pytest.raises(RuntimeError, match="DEMO metadata failure"):
        h.event(first["task_id"], "prepare_confirmation", revision=first["revision"])
    business = services(h)[0].lookup(
        h.owner_ids["A"], uuid5(UUID(first["task_id"]), f"medication.enroll:revision:{first['revision']}")
    )
    assert business is not None and len(h.snapshot()["regimens"]) == 1
    monkeypatch.setattr(repository, "cas", original)
    edit = h.client.post(
        f"/api/agent/workflows/tasks/{first['task_id']}/events",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "event_id": str(uuid4()),
            "expected_revision": first["revision"],
            "kind": "provide_fields",
            "values": {"dose_amount": 2},
        },
    )
    assert edit.status_code == 409 and h.view(first["task_id"])["state"] == "outcome_unknown"
    recovered = h.event(first["task_id"], "prepare_confirmation", revision=first["revision"])
    assert recovered["result_ref"]["id"] == str(business.regimen.id) and len(h.snapshot()["regimens"]) == 1


def test_expired_independent_confirmation_preserves_an_unactivated_workflow_draft(workflow):
    h = workflow
    session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})
    first = ready(h)
    prepared = h.event(first["task_id"], "prepare_confirmation")
    regimen_id = prepared["result_ref"]["id"]
    draft = h._request("GET", f"/api/medications/drafts/{regimen_id}")
    h._request("POST", f"/api/medications/drafts/{draft['source_id']}/review", json={"field_ids": None})
    challenge = h._request(
        "POST", f"/api/medications/drafts/{regimen_id}/challenge", params={"session_id": session["session_id"]}, json={}
    )
    h.clock.advance(hours=1)
    response = h.client.post(
        "/api/medications/activate",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "regimen_id": regimen_id,
            **{key: challenge[key] for key in ("challenge_id", "session_id", "session_state", "session_state_version")},
        },
    )
    assert response.status_code == 410 and h.view(first["task_id"])["state"] == "awaiting_confirmation"
    assert h.snapshot()["regimens"][0]["state"] == "draft"
