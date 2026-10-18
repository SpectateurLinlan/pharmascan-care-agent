"""DEMO_ONLY actual HTTP/application reads with an injected clock; no inferred writes."""

from datetime import timedelta

import pytest
from app.contracts.enums import IntakeStatus
from app.contracts.preferences import PreferenceUpdate
from app.domain.dose_attention import attention_deadline

from .correctness02_support import OWNER, TOKEN, build_harness


@pytest.mark.parametrize("elapsed,state", [(7199, "pending"), (7200, "unrecorded"), (7201, "unrecorded")])
def test_two_hour_boundary_is_unrecorded_and_never_writes_intake(elapsed, state):
    h = build_harness()
    try:
        h.root.clock.advance(seconds=elapsed - 4 * 3600)
        before = (dict(h.root.store.events), dict(h.root.store.occurrences), dict(h.root.store.challenges))
        response = h.client.get("/api/me/today-attention", headers={"Authorization": "Bearer " + TOKEN})
        assert response.status_code == 200, response.text
        row = next(row for row in response.json()["plans"] if row["regimen_id"] == str(h.plans[2].regimen.id))
        assert row["state"] == state
        assert len(row["unrecorded_times"]) == (state == "unrecorded")
        assert before == (h.root.store.events, h.root.store.occurrences, h.root.store.challenges)
    finally:
        h.close()


def test_next_dose_supersedes_previous_attention_before_two_hours_and_due_flow_agrees():
    h = build_harness()
    try:
        plan = h.plans[2].regimen
        h.root.store.regimens[(OWNER, plan.id)] = plan.model_copy(
            update={"frequency_rule": {**plan.frequency_rule, "local_times": ["08:00", "09:00"]}}
        )
        for key, rule in list(h.root.store.dose_rules.items()):
            if rule.regimen_id == plan.id:
                h.root.store.dose_rules[key] = rule.model_copy(update={"local_times": ["08:00", "09:00"]})
        h.root.clock.advance(hours=-3)  # 09:00 patient local
        result = h.client.get("/api/me/today-attention", headers={"Authorization": "Bearer " + TOKEN}).json()
        row = next(row for row in result["plans"] if row["regimen_id"] == str(plan.id))
        assert row["state"] == "pending" and row["unrecorded_times"] == ["2026-10-18T00:00:00Z"]
        h.root.schedule.materialize(patient_id=OWNER, regimen_id=plan.id, days=2)
        due = h.root.schedule.find_due(patient_id=OWNER, regimen_id=plan.id, attention_only=True)
        assert due.occurrence.due_at.isoformat() == "2026-10-18T01:00:00+00:00"
        # Ordinary/Agent reads keep their existing contract; no event was created.
        assert len(h.root.store.events) == 3
    finally:
        h.close()


def test_prn_has_no_inferred_daily_dose_and_other_patient_has_no_private_plan():
    h = build_harness()
    try:
        plan = h.plans[2].regimen
        h.root.store.regimens[(OWNER, plan.id)] = plan.model_copy(update={"is_prn": True, "frequency_rule": None})
        response = h.client.get("/api/me/today-attention", headers={"Authorization": "Bearer " + TOKEN}).json()
        row = next(row for row in response["plans"] if row["regimen_id"] == str(plan.id))
        assert row["state"] == "as_needed" and row["unrecorded_times"] == []
        foreign = h.client.get("/api/me/today-attention", headers={"Authorization": "Bearer DEMO.foreign"})
        assert foreign.status_code == 200 and foreign.json()["plans"] == []
        assert h.client.get("/api/me/today-attention").status_code == 401
        assert len(h.root.store.events) == 3
    finally:
        h.close()


def test_deadline_is_display_only_and_never_crosses_local_midnight():
    h = build_harness()
    try:
        end = h.root.clock.now().replace(hour=16, minute=0, second=0, microsecond=0)
        due = end - timedelta(minutes=30)
        assert attention_deadline(due, None, end) == end
        assert attention_deadline(due, due + timedelta(minutes=10), end) == due + timedelta(minutes=10)
    finally:
        h.close()


@pytest.mark.parametrize("status", ["reported_taken", "reported_not_taken", "unsure"])
def test_existing_report_states_are_not_replaced_by_automatic_unrecorded(status):
    h = build_harness()
    try:
        plan = h.plans[2].regimen
        key, event = next((key, event) for key, event in h.root.store.events.items() if event.regimen_id == plan.id)
        occurrence_key = (OWNER, event.occurrence_id)
        occurrence = h.root.store.occurrences[occurrence_key]
        due = h.root.clock.now().replace(hour=0, minute=0, second=0, microsecond=0)
        h.root.store.occurrences[occurrence_key] = occurrence.model_copy(update={"due_at": due})
        h.root.store.events[key] = event.model_copy(
            update={
                "event_time": due + timedelta(minutes=5),
                "created_at": h.root.clock.now() - timedelta(minutes=1),
                "intake_status": IntakeStatus(status),
            }
        )
        result = h.client.get("/api/me/today-attention", headers={"Authorization": "Bearer " + TOKEN}).json()
        row = next(row for row in result["plans"] if row["regimen_id"] == str(plan.id))
        assert row["state"] == "recorded" and row["unrecorded_times"] == []
        assert h.root.store.events[key].intake_status == IntakeStatus(status)
    finally:
        h.close()


def test_today_uses_patient_calendar_day_not_utc_server_day():
    h = build_harness()
    try:
        h.root.preferences.save(OWNER, PreferenceUpdate(timezone="America/Los_Angeles"))
        result = h.client.get("/api/me/today-attention", headers={"Authorization": "Bearer " + TOKEN}).json()
        assert result["local_date"] == "2026-10-17" and result["timezone"] == "America/Los_Angeles"
    finally:
        h.close()


def test_interval_without_a_trusted_anchor_is_not_guessed_or_auto_marked_unrecorded():
    h = build_harness()
    try:
        plan = h.plans[2].regimen
        h.root.store.regimens[(OWNER, plan.id)] = plan.model_copy(
            update={"frequency_rule": {"kind": "interval", "every_hours": 12, "local_times": []}}
        )
        response = h.client.get("/api/me/today-attention", headers={"Authorization": "Bearer " + TOKEN}).json()
        row = next(row for row in response["plans"] if row["regimen_id"] == str(plan.id))
        assert row["state"] == "unavailable" and row["unrecorded_times"] == []
        assert len(h.root.store.events) == 3
    finally:
        h.close()
