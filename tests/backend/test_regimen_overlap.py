"""LOCAL/SIMULATED: duplicate-course guards, not a hosted database proof."""

from datetime import date, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import pytest
from app.contracts.dto import FrequencyRuleDTO, RegimenDraftInput
from app.contracts.enums import RegimenState
from app.domain.errors import RegimenOverlapError
from app.domain.regimen_overlap import courses_overlap
from app.infrastructure.supabase_data import SupabaseDataClient
from app.transport.app_factory import create_app
from app.transport.container import build_container
from fastapi.testclient import TestClient

PATIENT = UUID(int=100)


def draft(**changes):
    return RegimenDraftInput(
        **{
            "medication_name": "DEMO Amlodipine",
            "dose_amount": 5,
            "dose_unit": "mg",
            "frequency_rule": FrequencyRuleDTO(kind="daily", local_times=["12:16"]),
            **changes,
        }
    )


def prepare(wired, data=None, patient=PATIENT):
    row = wired.enrollment.enroll_draft(patient_id=patient, draft=data or draft())
    wired.enrollment.review_source_fields(patient_id=patient, source_id=row.regimen.source_id)
    challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=patient,
        regimen_id=row.regimen.id,
        session_id=UUID(int=400),
        session_state_version=1,
    )
    wired.enrollment.confirm_challenge(patient_id=patient, challenge_id=challenge.id)
    return row, challenge


def activate(wired, row, challenge, patient=PATIENT):
    return wired.enrollment.activate_regimen(
        patient_id=patient,
        regimen_id=row.regimen.id,
        challenge_id=challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=1,
    )


@pytest.mark.parametrize("prn", [False, True])
def test_same_name_different_dose_or_prn_cannot_create_overlapping_course(wired, prn):
    first, challenge = prepare(wired)
    activate(wired, first, challenge)
    before = tuple(len(getattr(wired.store, name)) for name in ("sources", "source_fields", "medications", "regimens"))
    with pytest.raises(RegimenOverlapError):
        wired.enrollment.enroll_draft(
            patient_id=PATIENT,
            draft=draft(
                medication_name="  demo   AMLODIPINE  ",
                dose_amount=10,
                is_prn=prn,
                frequency_rule=None if prn else FrequencyRuleDTO(kind="daily", local_times=["20:00"]),
                food_instruction="as needed" if prn else None,
            ),
        )
    assert before == tuple(
        len(getattr(wired.store, name)) for name in ("sources", "source_fields", "medications", "regimens")
    )


def test_activation_rechecks_preexisting_drafts_and_does_not_consume_on_conflict(wired):
    first, first_challenge = prepare(wired)
    second, second_challenge = prepare(wired, draft(dose_amount=10))
    activate(wired, first, first_challenge)
    with pytest.raises(RegimenOverlapError):
        activate(wired, second, second_challenge)
    assert wired.challenges.get(PATIENT, second_challenge.id).consumed_at is None
    assert wired.regimens.get(PATIENT, second.regimen.id).state == RegimenState.DRAFT
    assert wired.regimens.get(PATIENT, first.regimen.id).state == RegimenState.ACTIVE
    assert not wired.store.events

    wired.enrollment.end_regimen(patient_id=PATIENT, regimen_id=first.regimen.id)
    assert activate(wired, second, second_challenge).regimen.state == RegimenState.ACTIVE
    assert wired.regimens.get(PATIENT, first.regimen.id).state == RegimenState.ENDED


def test_another_patients_plan_does_not_block_or_leak(wired):
    first, challenge = prepare(wired)
    activate(wired, first, challenge)
    other, other_challenge = prepare(wired, patient=UUID(int=200))
    assert activate(wired, other, other_challenge, UUID(int=200)).regimen.state == RegimenState.ACTIVE


def test_known_same_product_with_different_names_is_also_blocked(wired):
    first, first_challenge = prepare(wired)
    second, second_challenge = prepare(wired, draft(medication_name="DEMO alternative brand"))
    for medication in (first.medication, second.medication):
        reviewed = wired.medications.get(PATIENT, medication.id)
        wired.medications.update(reviewed.model_copy(update={"product_id": UUID(int=900)}))
    activate(wired, first, first_challenge)
    with pytest.raises(RegimenOverlapError):
        activate(wired, second, second_challenge)


def test_inclusive_last_day_blocks_overlap_but_later_course_is_allowed(wired):
    today = wired.clock.now().astimezone(ZoneInfo("Asia/Singapore")).date()
    first, challenge = prepare(wired, draft(course_start_date=today, course_end_date=today + timedelta(days=2)))
    activate(wired, first, challenge)
    with pytest.raises(RegimenOverlapError):
        wired.enrollment.enroll_draft(patient_id=PATIENT, draft=draft(course_start_date=today + timedelta(days=2)))
    later, later_challenge = prepare(wired, draft(course_start_date=today + timedelta(days=3)))
    assert activate(wired, later, later_challenge).regimen.state == RegimenState.ACTIVE


def test_unknown_end_is_open_and_windows_are_inclusive():
    assert courses_overlap(first_start=date(2026, 1, 1), first_end=None, second_start=date(2027, 1, 1), second_end=None)
    assert courses_overlap(
        first_start=date(2026, 1, 1), first_end=date(2026, 1, 2), second_start=date(2026, 1, 2), second_end=None
    )


def test_database_overlap_code_maps_to_safe_conflict_without_echoing_provider_text():
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(400, json={"code": "P7501", "message": "PRIVATE"}))
    ) as http:
        db = SupabaseDataClient(
            base_url="https://example.invalid",
            publishable_key="SIMULATED-publishable",
            access_token="SIMULATED-user",
            patient_id=PATIENT,
            client=http,
        )
        with pytest.raises(RegimenOverlapError) as caught:
            db.request("PATCH", "/rest/v1/regimen_versions", body={"state": "active"})
        assert "PRIVATE" not in str(caught.value)


def test_http_rejects_duplicate_with_conflict_and_keeps_original_plan():
    root = build_container()
    with TestClient(create_app(root)) as client:
        query = "?client_id=DEMO-overlap-contract"
        start = client.post("/api/demo/start", json={"client_id": "DEMO-overlap-contract"}).json()
        patient = UUID(start["patient_id"])
        original, challenge = prepare(root, patient=patient)
        activate(root, original, challenge, patient=patient)
        rejected = client.post(
            "/api/medications/drafts" + query,
            json={"medication_name": "DEMO Amlodipine", "dose_amount": 10, "dose_unit": "mg"},
        )
        assert rejected.status_code == 409 and rejected.json()["code"] == "REGIMEN_OVERLAP"
        assert root.enrollment.get_regimen(patient, original.regimen.id).state == RegimenState.ACTIVE
