"""LOCAL / MOCK VERIFIED: real application policy, fake persistence/provider."""

import base64
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
import requests
from app.application.calendar_export import calendar_export
from app.application.dosing import DoseScheduleService
from app.application.notification_worker import NotificationWorker
from app.application.reminder_plan import ReminderPlanService
from app.contracts.dto import DoseRuleDTO, FrequencyRuleDTO, RegimenDraftInput
from app.contracts.enums import RegimenState
from app.contracts.notifications import Delivery, DeliveryResult
from app.contracts.preferences import PreferenceUpdate
from app.contracts.push import PushSubscriptionInput
from app.infrastructure.web_push import WebPushProvider
from icalendar import Calendar
from pydantic import ValidationError
from pywebpush import WebPushException

from tests.backend.test_patient_app_repairs import PATIENT, activate, services


def plan(wired):
    reminder, _ = services(wired)
    return ReminderPlanService(
        medications=wired.medications,
        regimens=wired.regimens,
        schedule=wired.schedule,
        events=wired.events,
        reminders=reminder,
        clock=wired.clock,
    )


def test_automatic_plan_is_owned_idempotent_and_updates_after_stop(wired):
    regimen = activate(wired, 60)
    service = plan(wired)
    before = wired.regimens.get(PATIENT, regimen)
    rows = service.upcoming(PATIENT, lead_minutes=15)
    assert rows and all(row.regimen_id == regimen and row.rule_id for row in rows)
    assert rows == service.upcoming(PATIENT, lead_minutes=15)
    assert not service.upcoming(UUID(int=200), lead_minutes=15)
    assert not wired.store.events and wired.regimens.get(PATIENT, regimen) == before
    later = service.upcoming(PATIENT, lead_minutes=0)
    assert later[0].remind_at - rows[0].remind_at == timedelta(minutes=15)
    stopped = wired.enrollment.end_regimen(patient_id=PATIENT, regimen_id=regimen)
    assert stopped.state == RegimenState.ENDED
    assert wired.enrollment.end_regimen(patient_id=PATIENT, regimen_id=regimen) == stopped
    assert not service.upcoming(PATIENT, lead_minutes=15)


def test_calendar_is_private_valid_bounded_and_stable(wired):
    activate(wired, 60)
    rows = plan(wired).upcoming(PATIENT, lead_minutes=15, days=7)
    result = calendar_export(rows, now=wired.clock.now(), lead_minutes=15)
    parsed = Calendar.from_ical(result)
    events = parsed.walk("VEVENT")
    assert len(events) == 7 and "DEMO Metformin" in result
    assert all(event["SUMMARY"] == "Medication reminder: DEMO Metformin" for event in events)
    assert all(event["CLASS"] == "PRIVATE" for event in events)
    assert events[0].decoded("DTSTART") == rows[0].due_at
    assert parsed.walk("VALARM")[0].decoded("TRIGGER") == timedelta(minutes=-15)
    assert all(len(line.encode()) <= 75 for line in result.split("\r\n"))
    assert calendar_export(rows, now=wired.clock.now(), lead_minutes=15) == result
    assert not wired.store.events


def test_calendar_escapes_and_folds_the_medication_name(wired):
    activate(wired, 60, "DEMO 药品; A, B\\C")
    rows = plan(wired).upcoming(PATIENT, lead_minutes=15, days=1)
    result = calendar_export(rows, now=wired.clock.now(), lead_minutes=15)
    parsed = Calendar.from_ical(result)
    event = parsed.walk("VEVENT")[0]

    assert str(event["SUMMARY"]) == "Medication reminder: DEMO 药品; A, B\\C"
    assert "\\;" in result and "\\," in result and "\\\\" in result
    assert all(len(line.encode("utf-8")) <= 75 for line in result.split("\r\n") if line)


@pytest.mark.parametrize("kind", ["pending", "prn", "completed"])
def test_pending_prn_and_completed_courses_do_not_generate_fixed_reminders(wired, kind):
    day = wired.clock.now().astimezone(ZoneInfo("Asia/Singapore")).date()
    draft = wired.enrollment.enroll_draft(
        patient_id=PATIENT,
        draft=RegimenDraftInput(
            medication_name="DEMO reminder exclusion",
            dose_amount=1,
            dose_unit="tablet",
            is_prn=kind == "prn",
            food_instruction="as needed" if kind == "prn" else None,
            frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["08:00"]) if kind == "completed" else None,
            course_start_date=day if kind == "completed" else None,
            course_end_date=day if kind == "completed" else None,
        ),
    )
    if kind != "pending":
        wired.enrollment.review_source_fields(patient_id=PATIENT, source_id=draft.regimen.source_id)
        challenge, _ = wired.enrollment.request_activation_challenge(
            patient_id=PATIENT, regimen_id=draft.regimen.id, session_id=uuid4(), session_state_version=1
        )
        wired.enrollment.confirm_challenge(patient_id=PATIENT, challenge_id=challenge.id)
        wired.enrollment.activate_regimen(
            patient_id=PATIENT,
            regimen_id=draft.regimen.id,
            challenge_id=challenge.id,
            session_state="awaiting_confirmation",
            session_state_version=1,
        )
    if kind == "completed":
        original = plan(wired).upcoming(PATIENT, lead_minutes=0)
        assert len(original) == 1
        wired.clock.advance(days=1)
        reminder, alerts = services(wired)
        assert alerts.current(PATIENT, lead_minutes=0, timezone="Asia/Singapore") == []
        from app.domain.errors import ValidationError as DomainValidationError

        with pytest.raises(DomainValidationError):
            reminder.snooze(patient_id=PATIENT, occurrence_id=original[0].occurrence_id, minutes=15)
    assert not plan(wired).upcoming(PATIENT, lead_minutes=0)
    assert not wired.store.events


@pytest.mark.parametrize("date,expected", [("2027-03-14", 0), ("2027-11-07", 1)])
def test_dst_nonexistent_time_skipped_repeated_time_once(wired, date, expected):
    from app.application.timezone import FixedTzProvider

    regimen = activate(wired, 60)

    class Clock:
        def now(self):
            return datetime.fromisoformat(date).replace(hour=12, tzinfo=UTC)

    schedule = DoseScheduleService(
        regimens=wired.regimens,
        rules=wired.dose_rules,
        occurrences=wired.occurrences,
        clock=Clock(),
        ids=wired.ids,
        tz_provider=FixedTzProvider("America/New_York"),
    )
    rule = DoseRuleDTO(
        id=uuid4(),
        patient_id=PATIENT,
        regimen_id=regimen,
        rule_kind="scheduled",
        local_times=["02:30" if expected == 0 else "01:30"],
        timezone="America/New_York",
    )
    schedule.add_rule(patient_id=PATIENT, regimen_id=regimen, rule=rule)
    rows = schedule.materialize(patient_id=PATIENT, regimen_id=regimen, days=1)
    assert len([row for row in rows if row.rule_id == rule.id]) == expected


def test_weekday_rule_and_disabled_rule_project_only_confirmed_times(wired):
    regimen = activate(wired, 60)
    rule = DoseRuleDTO(
        id=uuid4(),
        patient_id=PATIENT,
        regimen_id=regimen,
        rule_kind="scheduled",
        local_times=["19:00"],
        days_of_week=[1],
    )
    wired.schedule.add_rule(patient_id=PATIENT, regimen_id=regimen, rule=rule)
    rows = plan(wired).upcoming(PATIENT, lead_minutes=0)
    weekly = [row for row in rows if row.rule_id == rule.id]
    assert len(weekly) == 1 and weekly[0].due_at.astimezone(ZoneInfo("Asia/Singapore")).isoweekday() == 1
    disabled = rule.model_copy(update={"id": uuid4(), "enabled": False})
    wired.schedule.add_rule(patient_id=PATIENT, regimen_id=regimen, rule=disabled)
    assert not any(row.rule_id == disabled.id for row in plan(wired).upcoming(PATIENT, lead_minutes=0))


def test_vapid_generator_is_sdk_compatible_private_and_refuses_overwrite(tmp_path, monkeypatch, capsys):
    from app.config import parse_env_file
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid

    from scripts import create_vapid_keys

    monkeypatch.setattr(create_vapid_keys, "__file__", str(tmp_path / "scripts" / "create_vapid_keys.py"))
    create_vapid_keys.main()
    path = tmp_path / "outputs" / "local-vapid.env"
    values = parse_env_file(path)
    assert values["ENABLE_WEB_PUSH"] == "false"
    key = Vapid.from_string(values["VAPID_PRIVATE_KEY"])
    public = key.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    assert base64.urlsafe_b64encode(public).decode().rstrip("=") == values["VAPID_PUBLIC_KEY"]
    assert values["VAPID_PRIVATE_KEY"] not in capsys.readouterr().out
    with pytest.raises(FileExistsError):
        create_vapid_keys.main()


def test_disabled_worker_starts_without_touching_database_or_provider(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/run_reminders.py")],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env={**os.environ, "ENABLE_WEB_PUSH": "false", "PHARMASCAN_ENV_FILE": str(tmp_path / "no-runtime-secrets.env")},
    )
    assert result.returncode == 2 and "no jobs sent" in result.stdout
    assert not result.stderr


def subscription():
    return {
        "endpoint": "https://fcm.googleapis.com/fcm/send/DEMO-not-a-real-device",
        "keys": {
            "auth": base64.urlsafe_b64encode(b"x" * 16).decode().rstrip("="),
            "p256dh": base64.urlsafe_b64encode(b"\x04" + b"x" * 64).decode().rstrip("="),
        },
    }


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/a",
        "https://127.0.0.1/a",
        "https://fcm.googleapis.com.evil.test/a",
        "https://fcm.googleapis.com:444/a",
        "https://user@fcm.googleapis.com/a",
        "https://evil.test/a",
    ],
)
def test_push_endpoint_rejects_ssrf(endpoint):
    with pytest.raises(ValidationError):
        PushSubscriptionInput.model_validate({**subscription(), "endpoint": endpoint})


def test_push_keys_identity_and_timezone_validation():
    with pytest.raises(ValidationError):
        PushSubscriptionInput.model_validate({**subscription(), "patient_id": str(uuid4())})
    with pytest.raises(ValidationError):
        PushSubscriptionInput.model_validate({**subscription(), "keys": {"auth": "bad", "p256dh": "bad"}})
    assert PreferenceUpdate(timezone="America/New_York").timezone == "America/New_York"
    with pytest.raises(ValidationError):
        PreferenceUpdate(timezone="Invalid/Timezone")


@pytest.mark.parametrize(
    "code,status", [(410, "expired_subscription"), (429, "temporary"), (503, "temporary"), (403, "provider_rejected")]
)
def test_push_provider_failure_categories(code, status):
    response = requests.Response()
    response.status_code = code
    response.headers["Retry-After"] = "120"

    def fail(**kwargs):
        raise WebPushException("DEMO scrubbed", response=response)

    row = Delivery(
        id=uuid4(),
        subscription_id=uuid4(),
        subscription=PushSubscriptionInput.model_validate(subscription()),
        attempts=1,
    )
    result = WebPushProvider(private_key="DEMO-unused", subject="mailto:demo@example.invalid", send=fail).send(row)
    assert result.status == status
    if code == 429:
        assert result.retry_seconds == 120


def test_worker_is_bounded_and_notification_has_no_medication_or_patient_data():
    row = Delivery(
        id=uuid4(),
        subscription_id=uuid4(),
        subscription=PushSubscriptionInput.model_validate(subscription()),
        attempts=1,
    )
    calls = []

    def send(**kwargs):
        calls.append(kwargs)
        response = requests.Response()
        response.status_code = 201
        return response

    provider = WebPushProvider(private_key="DEMO-unused", subject="mailto:demo@example.invalid", send=send)

    class Repository:
        def claim(self, now):
            return row

        def finish(self, delivery, result, now):
            assert result == DeliveryResult(status="sent")

    class Clock:
        def now(self):
            return datetime(2026, 10, 15, tzinfo=UTC)

    assert NotificationWorker(Repository(), provider, Clock()).deliver(2) == 2
    assert len(calls) == 2 and "patient" not in calls[0]["data"] and "Metformin" not in calls[0]["data"]
    assert calls[0]["timeout"] == 10


def test_uncertain_network_send_is_not_declared_success():
    def fail(**kwargs):
        raise requests.Timeout("DEMO")

    row = Delivery(
        id=uuid4(),
        subscription_id=uuid4(),
        subscription=PushSubscriptionInput.model_validate(subscription()),
        attempts=1,
    )
    assert (
        WebPushProvider(private_key="DEMO-unused", subject="mailto:demo@example.invalid", send=fail).send(row).status
        == "uncertain_delivery"
    )


@pytest.mark.parametrize("code", [None, 302])
def test_missing_or_redirect_provider_response_cannot_claim_sent(code):
    def send(**kwargs):
        if code is None:
            return None
        response = requests.Response()
        response.status_code = code
        return response

    row = Delivery(
        id=uuid4(),
        subscription_id=uuid4(),
        subscription=PushSubscriptionInput.model_validate(subscription()),
        attempts=1,
    )
    assert (
        WebPushProvider(private_key="DEMO-unused", subject="mailto:demo@example.invalid", send=send).send(row).status
        == "provider_rejected"
    )


def test_new_reviewed_version_and_explicit_stop_cancel_future_reminders(clock):
    from app.transport.app_factory import create_app
    from app.transport.container import build_container
    from fastapi.testclient import TestClient

    container = build_container(clock=clock)
    app = TestClient(create_app(container))

    def call(method, path, **kwargs):
        response = app.request(
            method, path, params={"client_id": "DEMO-version-reminder", **kwargs.pop("params", {})}, **kwargs
        )
        assert response.status_code == 200
        return response.json()

    session = call("POST", "/api/demo/start", json={"client_id": "DEMO-version-reminder"})

    def draft(medication=None, time="08:00"):
        return call(
            "POST",
            "/api/medications/drafts",
            params={"medication_id": medication} if medication else {},
            json={
                "medication_name": "DEMO stable product",
                "dose_amount": 1,
                "dose_unit": "tablet",
                "frequency_kind": "daily",
                "frequency_local_times": [time],
            },
        )

    def activate_version(row):
        call("POST", f"/api/medications/drafts/{row['source_id']}/review", json={"field_ids": None})
        challenge = call(
            "POST",
            f"/api/medications/drafts/{row['regimen_id']}/challenge",
            params={"session_id": session["session_id"]},
        )
        return call(
            "POST",
            "/api/medications/activate",
            json={
                "regimen_id": row["regimen_id"],
                "challenge_id": challenge["challenge_id"],
                "session_id": session["session_id"],
                "session_state": challenge["session_state"],
                "session_state_version": challenge["session_state_version"],
            },
        )

    first = draft()
    activate_version(first)
    assert call("GET", "/api/me/medications")["medications"][0]["regimen_id"] == first["regimen_id"]
    blocked = app.post(
        "/api/medications/drafts",
        params={"client_id": "DEMO-version-reminder", "medication_id": first["medication_id"]},
        json={"medication_name": "DEMO stable product", "dose_amount": 1, "dose_unit": "tablet"},
    )
    assert blocked.status_code == 409 and blocked.json()["code"] == "REGIMEN_OVERLAP"
    call("POST", f"/api/medications/{first['regimen_id']}/end", json={"confirmed": True})
    assert call("GET", "/api/reminders/plan") == []
    second = draft(first["medication_id"], "20:00")
    activate_version(second)
    plan = call("GET", "/api/reminders/plan")
    assert plan and all(row["regimen_id"] == second["regimen_id"] for row in plan)
    versions = call("GET", "/api/me/regimens")
    assert {row["state"] for row in versions} == {"ended", "active"}
    assert len({row["medication_id"] for row in versions}) == 1
    assert (
        app.post(
            f"/api/medications/{second['regimen_id']}/end", params={"client_id": "DEMO-other"}, json={"confirmed": True}
        ).status_code
        == 404
    )
    assert (
        app.post(
            f"/api/medications/{second['regimen_id']}/end",
            params={"client_id": "DEMO-version-reminder"},
            json={"confirmed": False},
        ).status_code
        == 422
    )
    call("POST", f"/api/medications/{second['regimen_id']}/end", json={"confirmed": True})
    call("POST", f"/api/medications/{second['regimen_id']}/end", json={"confirmed": True})
    assert call("GET", "/api/reminders/plan") == []
    assert not container.store.events
