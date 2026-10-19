"""Synthetic HTTP/application acceptance, no production or provider calls."""

from datetime import timedelta
from uuid import uuid4

import pytest
from app.contracts.care_calendar import CareCalendarEvent
from app.contracts.long_term import StockInput
from pydantic import ValidationError as SchemaError

from .correctness02_support import OWNER, TOKEN, build_harness


def call(h, method, path, data=None, token=TOKEN):
    return h.client.request(method, path, headers={"Authorization": f"Bearer {token}"}, json=data)


@pytest.mark.parametrize("status", ["reported_taken", "reported_not_taken", "unsure"])
def test_late_report_confirmation_correction_and_retry(status):
    h = build_harness()
    before = dict(h.root.store.events)
    item = call(h, "GET", "/api/me/dose-follow-ups").json()["items"][0]
    endpoint = f"/api/me/doses/{item['occurrence_id']}/late-report"
    values = dict(
        id=str(uuid4()),
        intake_status=status,
        reason="forgot_to_record",
        notes="DEMO 本人补记",
        expected_report_id=None,
        actual_administration_at=None,
    )
    if status == "reported_taken":
        values["actual_administration_at"] = item["due_at"]
    assert call(h, "POST", endpoint, {"report": values, "challenge_id": str(uuid4())}).status_code != 200
    challenge = call(h, "POST", endpoint + "/challenge", values)
    assert challenge.status_code == 200, challenge.text
    assert h.root.store.events == before and not h.root.store.late_reports
    body = {"report": values, "challenge_id": challenge.json()["challenge_id"]}
    tampered = {**body, "report": {**values, "notes": "DEMO changed"}}
    assert call(h, "POST", endpoint, tampered).status_code != 200
    response = call(h, "POST", endpoint, body)
    assert response.status_code == 200, response.text
    assert response.json()["intake_status"] == status and not response.json()["ingestion_proven"]
    assert response.json()["recorded_at"] != item["due_at"]
    assert call(h, "POST", endpoint, body).json() == response.json()
    assert h.root.store.events == before and len(h.root.store.late_reports) == 1
    assert all(
        row["occurrence_id"] != item["occurrence_id"]
        for row in call(h, "GET", "/api/me/dose-follow-ups").json()["items"]
    )
    correction = {
        **values,
        "id": str(uuid4()),
        "expected_report_id": values["id"],
        "reason": "correcting_record",
        "intake_status": "unsure",
        "actual_administration_at": None,
    }
    challenge2 = call(h, "POST", endpoint + "/challenge", correction).json()
    changed = call(h, "POST", endpoint, {"report": correction, "challenge_id": challenge2["challenge_id"]})
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == 2 and h.root.store.events == before
    history = call(h, "GET", endpoint.replace("/late-report", "/late-reports")).json()
    assert [entry["intake_status"] for entry in history["corrections"]] == [status, "unsure"]
    effective = h.root.self_report.history(
        patient_id=OWNER,
        regimen_id=__import__("uuid").UUID(item["regimen_id"]),
        window_start=h.root.clock.now() - timedelta(days=7),
        window_end=h.root.clock.now(),
    )
    assert any(entry.event and str(entry.event.id) == correction["id"] for entry in effective)


def test_late_scope_stale_challenge_invalid_times_and_cancellation():
    h = build_harness()
    item = call(h, "GET", "/api/me/dose-follow-ups").json()["items"][0]
    path = f"/api/me/doses/{item['occurrence_id']}/late-report"
    values = dict(
        id=str(uuid4()), intake_status="reported_taken", reason="other", notes="DEMO", expected_report_id=None
    )
    assert call(h, "POST", path + "/challenge", values, "DEMO.foreign").status_code != 200
    assert call(h, "POST", path + "/challenge", {**values, "reason": "arbitrary"}).status_code == 422
    assert (
        call(
            h,
            "POST",
            path + "/challenge",
            {**values, "actual_administration_at": (h.root.clock.now() + timedelta(hours=1)).isoformat()},
        ).status_code
        != 200
    )
    assert call(h, "POST", path + "/challenge", {**values, "expected_report_id": str(uuid4())}).status_code != 200
    challenge = call(h, "POST", path + "/challenge", values).json()
    assert not h.root.store.late_reports  # cancelling the sheet performs no write
    h.root.clock.advance(minutes=11)
    assert call(h, "POST", path, {"report": values, "challenge_id": challenge["challenge_id"]}).status_code != 200
    assert not h.root.store.late_reports


def test_correct_original_ended_version_keeps_original_and_records_actual_time():
    h = build_harness()
    original_plan = h.plans[0].regimen
    items = call(h, "GET", "/api/me/dose-follow-ups?include_reported=true").json()["items"]
    item = next(row for row in items if row["regimen_id"] == str(original_plan.id))
    original = dict(h.root.store.events)
    values = dict(
        id=str(uuid4()),
        intake_status="reported_taken",
        reason="correcting_record",
        actual_administration_at=item["due_at"],
        expected_report_id=item["report_id"],
        notes="DEMO corrected time",
    )
    path = f"/api/me/doses/{item['occurrence_id']}/late-report"
    proposal = call(h, "POST", path + "/challenge", values)
    assert proposal.status_code == 200, proposal.text
    wrong_time = {**values, "id": str(uuid4()), "actual_administration_at": h.root.clock.now().isoformat()}
    assert call(h, "POST", path + "/challenge", wrong_time).status_code != 200
    saved = call(h, "POST", path, dict(report=values, challenge_id=proposal.json()["challenge_id"]))
    assert saved.status_code == 200, saved.text
    assert saved.json()["regimen_id"] == str(original_plan.id)
    audit = call(h, "GET", path.replace("/late-report", "/late-reports")).json()
    assert audit["original"]["id"] == item["report_id"] and len(audit["corrections"]) == 1
    assert h.root.store.events == original
    assert saved.json()["actual_administration_at"] == item["due_at"]


def test_unknown_actual_time_does_not_deduct_a_late_report_from_a_new_stock_count():
    h = build_harness()
    item = call(h, "GET", "/api/me/dose-follow-ups").json()["items"][0]
    from uuid import UUID

    medication = UUID(item["medication_id"])
    h.root.long_term.record_stock(
        OWNER,
        medication,
        StockInput(id=uuid4(), kind="count", quantity=2, unit="tablet", confirmed=True),
        "Asia/Singapore",
    )
    values = dict(id=str(uuid4()), intake_status="reported_taken", reason="unsure_time", expected_report_id=None)
    path = f"/api/me/doses/{item['occurrence_id']}/late-report"
    proposal = call(h, "POST", path + "/challenge", values).json()
    assert call(h, "POST", path, dict(report=values, challenge_id=proposal["challenge_id"])).status_code == 200
    inventory = h.root.long_term.inventory(OWNER, medication)
    assert inventory.estimated_remaining is None and inventory.last_confirmed_stock == 2
    assert "Count your stock again" in inventory.estimate_note

    tasks = h.root.long_term.refresh_refill_tasks(OWNER, "Asia/Singapore")
    assert any(
        row.medication_id == medication and row.source == "stock_estimate" and row.status == "open" for row in tasks
    )


def test_calendar_contract_retains_source_ids_and_date_only_bounds():
    from datetime import date

    identifier = uuid4()
    event = CareCalendarEvent(
        source_type="regimen_version",
        source_id=identifier,
        kind="course_end",
        title="DEMO course",
        timezone="Asia/Singapore",
        on_date=date(2026, 10, 19),
    )
    assert event.model_dump(mode="json")["event_id"] == f"regimen_version:{identifier}:course_end"
    assert event.at is None and event.model_dump(mode="json")["on_date"] == "2026-10-19"
    with pytest.raises(SchemaError):
        CareCalendarEvent(
            source_type="care_task",
            source_id=identifier,
            kind="planned_dose",
            title="DEMO invalid",
            timezone="Asia/Singapore",
            on_date=date(2026, 10, 19),
        )


def test_task_time_reminders_edit_reopen_history_and_scope():
    h = build_harness()
    now = h.root.clock.now()
    values = dict(
        id=str(uuid4()),
        title="DEMO pharmacist visit",
        category="medication_review",
        due_at=(now + timedelta(hours=3)).isoformat(),
        reminder_minutes=60,
        confirmed=True,
    )
    assert call(h, "POST", "/api/me/care-tasks", {**values, "title": " "}).status_code == 422
    assert call(h, "POST", "/api/me/care-tasks", {**values, "reminder_minutes": 1440}).status_code != 200
    row = call(h, "POST", "/api/me/care-tasks", values)
    assert row.status_code == 200, row.text
    row = row.json()
    path = "/api/me/care-tasks/" + row["id"]
    assert (
        call(
            h,
            "POST",
            path,
            dict(id=str(uuid4()), expected_version=1, status="completed", confirmed=True),
            "DEMO.foreign",
        ).status_code
        != 200
    )
    edit = dict(
        id=str(uuid4()),
        expected_version=1,
        status="deferred",
        title="DEMO rescheduled",
        due_at=(now + timedelta(days=2)).isoformat(),
        reminder_minutes=30,
        notes="DEMO bring records",
        confirmed=True,
    )
    updated = call(h, "POST", path, edit)
    assert updated.status_code == 200, updated.text
    assert call(h, "POST", path, edit).json()["version"] == 2
    assert call(h, "POST", path, {**edit, "reminder_minutes": 15}).status_code != 200
    completed = call(
        h, "POST", path, dict(id=str(uuid4()), expected_version=2, status="completed", confirmed=True)
    ).json()
    reopened = call(
        h,
        "POST",
        path,
        dict(
            id=str(uuid4()),
            expected_version=3,
            status="open",
            due_at=(now + timedelta(days=3)).isoformat(),
            reminder_minutes=None,
            confirmed=True,
        ),
    ).json()
    assert completed["version"] == 3 and reopened["version"] == 4
    assert len(reopened["history"]) == 4 and reopened["history"][1]["title"] == "DEMO rescheduled"
    assert reopened["history"][1]["reminder_minutes"] == 30 and reopened["reminder_minutes"] is None
    past = {**values, "id": str(uuid4()), "due_at": (now - timedelta(days=1)).isoformat(), "reminder_minutes": None}
    assert call(h, "POST", "/api/me/care-tasks", past).status_code != 200
    historical = call(h, "POST", "/api/me/care-tasks", {**past, "historical_confirmed": True})
    assert historical.status_code == 200, historical.text
    assert historical.json()["historical_entry"]


def test_unreviewed_identity_keeps_unreported_visible_but_refuses_write():
    from uuid import UUID

    from app.contracts.enums import IdentityStatus

    h = build_harness()
    item = call(h, "GET", "/api/me/dose-follow-ups").json()["items"][0]
    key = (OWNER, UUID(item["medication_id"]))
    h.root.store.medications[key] = h.root.store.medications[key].model_copy(
        update={"identity_status": IdentityStatus.UNVERIFIED}
    )
    visible = call(h, "GET", "/api/me/dose-follow-ups").json()["items"]
    row = next(row for row in visible if row["occurrence_id"] == item["occurrence_id"])
    assert not row["can_report"] and row["intake_status"] is None
    response = call(
        h,
        "POST",
        f"/api/me/doses/{item['occurrence_id']}/late-report/challenge",
        dict(id=str(uuid4()), intake_status="reported_taken", reason="forgot_to_record"),
    )
    assert response.status_code != 200 and not h.root.store.late_reports


def test_late_report_is_counted_in_its_occurrence_period_not_the_reporting_week():
    h = build_harness()
    h.root.clock.advance(days=4)
    item = next(
        row
        for row in call(h, "GET", "/api/me/dose-follow-ups").json()["items"]
        if row["due_at"].startswith("2026-10-17")
    )
    values = dict(id=str(uuid4()), intake_status="reported_taken", reason="unsure_time", expected_report_id=None)
    path = f"/api/me/doses/{item['occurrence_id']}/late-report"
    proposal = call(h, "POST", path + "/challenge", values).json()
    assert call(h, "POST", path, dict(report=values, challenge_id=proposal["challenge_id"])).status_code == 200
    weekly = h.root.review_summary.generate(OWNER, "week", timezone="Asia/Singapore")
    monthly = h.root.review_summary.generate(OWNER, "month", timezone="Asia/Singapore")
    assert weekly.reported_taken == 0  # This occurrence was last week, though reported today.
    assert monthly.reported_taken == 2  # The fixture's original taken report plus this occurrence.


def test_ended_plans_keep_existing_unreported_occurrences_without_creating_history():
    h = build_harness()
    for draft in h.plans[1:]:
        h.root.enrollment.end_regimen(patient_id=OWNER, regimen_id=draft.regimen.id)
    before = dict(h.root.store.occurrences)
    assert call(h, "GET", "/api/me/medications").json()["medications"] == []
    rows = call(h, "GET", "/api/me/dose-follow-ups").json()["items"]
    assert rows and all(row["can_report"] for row in rows)
    assert dict(h.root.store.occurrences) == before


def test_032_capability_blocks_silent_legacy_rpc_loss_before_io():
    from app.contracts.long_term import CareTask, TaskUpdate
    from app.domain.errors import ValidationError
    from app.infrastructure.care_repos import SupabaseCareRepository

    h = build_harness()

    class NoIO:
        def check_patient(self, patient):
            raise AssertionError("Unreleased fields must be rejected before RPC")

    repository = SupabaseCareRepository(NoIO())
    now = h.root.clock.now()
    row = CareTask(
        id=uuid4(),
        patient_id=OWNER,
        title="DEMO",
        category="medication_review",
        due_at=now + timedelta(days=1),
        reminder_minutes=30,
        created_at=now,
        updated_at=now,
    )
    with pytest.raises(ValidationError, match="not enabled"):
        repository.create_task(row)
    with pytest.raises(ValidationError, match="not enabled"):
        repository.update_task(
            OWNER,
            row.id,
            TaskUpdate(id=uuid4(), expected_version=1, status="open", reminder_minutes=None, confirmed=True),
            now,
        )
