"""DEMO_ONLY temporal outcomes through actual local services, no live provider."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from app.agent.model_tools import ModelTools
from app.agent.orchestrator import AgentTurn
from app.agent.tools import CheckDueDoseRequest, GetDoseStatusRequest, RecordSelfReportRequest
from app.application.dosing import DoseScheduleService
from app.application.timezone import FixedTzProvider
from app.contracts.enums import IntakeStatus, ToolName
from app.contracts.temporal import calendar_selection, local_day_window

from .test_dose_status_query import PATIENT, _activate, _base, _report
from .test_dose_status_query import agent as agent


@pytest.mark.parametrize(
    "zone,instant,expected",
    [
        ("Asia/Singapore", "2026-10-12T23:00:00+00:00", "2026-10-12"),
        ("America/Los_Angeles", "2026-10-13T01:00:00+00:00", "2026-10-11"),
        ("Pacific/Kiritimati", "2026-10-12T12:00:00+00:00", "2026-10-12"),
    ],
)
@pytest.mark.parametrize("text", ["查看昨天", "Yesterday", "我昨天吃过药吗？"])
def test_calendar_uses_patient_day(zone, instant, expected, text):
    assert calendar_selection(text, datetime.fromisoformat(instant), zone).day == date.fromisoformat(expected)


@pytest.mark.parametrize("day,hours", [(date(2026, 3, 8), 23), (date(2026, 11, 1), 25)])
def test_dst_window_is_calendar_day(day, hours):
    start, end = local_day_window(day, "America/New_York")
    assert (end - start).total_seconds() == hours * 3600
    assert start.astimezone(ZoneInfo("America/New_York")).date() == day


@pytest.mark.parametrize(
    "text", ["2026-02-30", "2026-10-14", "昨天和今天", "明天", "last week", "3 days ago", "10月12日", "Oct 12"]
)
def test_unknown_or_conflicting_dates_do_not_mean_today(text):
    assert not calendar_selection(text, datetime(2026, 10, 13, tzinfo=UTC), "Asia/Singapore").supported


@pytest.mark.parametrize(
    "text", ["I took Amlodipine yesterday", "我昨天吃了 Amlodipine", "I took it 2026-10-12", "I took it last week"]
)
def test_model_past_claim_refuses_without_challenge_or_event(agent, wired, text):
    orchestrator, registry = agent
    _, active = _activate(wired)
    session = orchestrator.start_session(patient_id=PATIENT)
    before = (len(wired.store.events), len(wired.store.challenges))
    result = ModelTools(registry=registry, fallback=orchestrator).execute(
        name="prepare_self_report",
        arguments={"regimen_id": str(active.regimen.id), "intake_status": "taken"},
        patient_id=PATIENT,
        session_id=session.id,
        correlation_id=uuid4(),
        client_turn_id="DEMO-past",
        turn=AgentTurn(text=text, language="zh" if "我" in text else "en"),
    )
    assert result.prepared_reply and not result.prepared_reply.requires_confirmation
    assert before == (len(wired.store.events), len(wired.store.challenges))
    assert "今天" in result.prepared_reply.message or "today" in result.prepared_reply.message


@pytest.mark.parametrize(
    "text",
    [
        "Have I taken Amlodipine yesterday?",
        "我昨天吃过 Amlodipine 吗？",
        "Have I taken Amlodipine 2026-10-13?",
        "我 2026年10月13日吃过 Amlodipine 吗？",
    ],
)
def test_model_cannot_substitute_today(agent, wired, text):
    orchestrator, registry = agent
    _, active = _activate(wired)
    wired.clock.advance(hours=2)
    _report(wired, active.regimen.id, IntakeStatus.REPORTED_TAKEN, key="DEMO-original")
    wired.clock.advance(days=1)
    _report(wired, active.regimen.id, IntakeStatus.REPORTED_NOT_TAKEN, key="DEMO-opposite")
    output = ModelTools(registry=registry, fallback=orchestrator).execute(
        name="get_dose_status",
        arguments={"medication_name": "Amlodipine", "day_offset": 0},
        patient_id=PATIENT,
        session_id=uuid4(),
        correlation_id=uuid4(),
        client_turn_id="DEMO-date",
        turn=AgentTurn(text=text),
    )
    result = output.results[0]
    assert result.payload["local_date"] == "2026-10-13"
    assert result.payload["intake_status"] == "reported_taken"
    answer = orchestrator.render_results(output.intent, output.results)
    assert "yesterday" in answer and "reported taking" in answer and "Amlodipine" in answer


def test_later_submitted_event_stays_with_original_occurrence(agent, wired):
    _, registry = agent
    _, active = _activate(wired)
    wired.clock.advance(hours=2)
    _report(wired, active.regimen.id, IntakeStatus.REPORTED_TAKEN, key="DEMO-later")
    event = next(iter(wired.store.events.values()))
    # Synthetic pre-existing late record only; this does not enable a write API.
    wired.store.events[PATIENT, event.id] = event.model_copy(
        update={
            "event_time": event.event_time + timedelta(days=1),
            "created_at": event.created_at + timedelta(days=1),
        }
    )
    wired.clock.advance(days=1)
    result = registry.execute(
        ToolName.GET_DOSE_STATUS,
        GetDoseStatusRequest(
            **_base(PATIENT, uuid4()), medication_id=active.regimen.patient_medication_id, day_offset=-1
        ),
    )
    row = result.payload["records"][0]
    assert row["intake_status"] == "reported_taken"
    assert row["due_at"] != row["event_time"]
    assert row["created_at"].startswith("2026-10-14")


def test_historical_occurrence_cannot_prepare_or_write_today(agent, wired):
    orchestrator, registry = agent
    _, active = _activate(wired)
    occurrences = wired.schedule.materialize(patient_id=PATIENT, regimen_id=active.regimen.id, days=1)
    wired.clock.advance(days=1)
    request = RecordSelfReportRequest(
        **_base(PATIENT, uuid4()),
        regimen_id=active.regimen.id,
        occurrence_id=occurrences[0].id,
        intake_status="taken",
        idempotency_key="DEMO-wrong-date",
    )
    before = len(wired.store.events), len(wired.store.challenges)
    result = registry.execute(ToolName.RECORD_SELF_REPORT, request)
    assert result.blocked and not result.requires_confirmation
    assert before == (len(wired.store.events), len(wired.store.challenges))
    from app.domain.errors import ValidationError

    with pytest.raises(ValidationError):
        registry.prepare_self_report_confirmation(request, session_state_version=1)


def test_historical_schedule_is_read_only_and_uses_old_rule(agent, wired):
    _, registry = agent
    _, active = _activate(wired)
    wired.clock.advance(days=1)
    wired.enrollment.end_regimen(patient_id=PATIENT, regimen_id=active.regimen.id)
    before = len(wired.store.occurrences), len(wired.store.events)
    result = registry.execute(
        ToolName.CHECK_DUE_DOSE, CheckDueDoseRequest(**_base(PATIENT, uuid4()), window="today", day_offset=-1)
    )
    row = result.payload["schedule"][0]
    assert row["regimen_id"] == str(active.regimen.id)
    assert row["local_time"] == "08:00" and row["intake_status"] == "not_reported"
    assert row["occurrence_id"] is None  # no fabricated historical ID
    assert before == (len(wired.store.occurrences), len(wired.store.events))


def test_injected_patient_timezone_reaches_tool_window(wired):
    schedule = DoseScheduleService(
        regimens=wired.regimens,
        rules=wired.dose_rules,
        occurrences=wired.occurrences,
        clock=wired.clock,
        ids=wired.ids,
        tz_provider=FixedTzProvider("America/New_York"),
    )
    from app.agent.registry import ToolRegistry

    registry = ToolRegistry(
        enrollment=wired.enrollment,
        schedule=schedule,
        self_report=wired.self_report,
        traces=wired.traces,
        clock=wired.clock,
        ids=wired.ids,
    )
    draft, _ = _activate(wired)
    result = registry.execute(
        ToolName.GET_DOSE_STATUS, GetDoseStatusRequest(**_base(PATIENT, uuid4()), medication_id=draft.medication.id)
    )
    assert result.payload["local_timezone"] == "America/New_York"
    assert result.payload["local_date"] == "2026-10-12"
    assert result.payload["resolution"] == "resolved"


def test_one_day_query_lists_distinct_report_states(agent, wired):
    orchestrator, registry = agent
    _, active = _activate(wired, times=("08:00", "12:00", "18:00"))
    wired.clock.advance(hours=2)
    _report(wired, active.regimen.id, IntakeStatus.REPORTED_TAKEN, key="DEMO-first")
    wired.clock.advance(hours=4)
    _report(wired, active.regimen.id, IntakeStatus.UNSURE, key="DEMO-second")
    result = registry.execute(
        ToolName.GET_DOSE_STATUS,
        GetDoseStatusRequest(**_base(PATIENT, uuid4()), medication_id=active.regimen.patient_medication_id),
    )
    answer = orchestrator.render_results(result.tool_name, [result])
    assert "reported taking" in answer and "unsure" in answer
    assert result.payload["records"][0]["future"]  # upcoming dose is explicitly separate
    assert "18:00" not in answer  # no future plan masquerading as past history


@pytest.mark.parametrize("language,text", [("en", "I took Amlodipine today"), ("zh", "我今天吃了 Amlodipine")])
def test_current_report_still_prepares_only_confirmation(agent, wired, language, text):
    orchestrator, _ = agent
    _, active = _activate(wired)
    wired.clock.advance(hours=2)
    session = orchestrator.start_session(patient_id=PATIENT)
    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=session.id,
        turn=AgentTurn(text=text, language=language, slots={"regimen_id": active.regimen.id, "intake_status": "taken"}),
    )
    assert reply.requires_confirmation and reply.pending_report
    summary = reply.pending_report.summary
    assert summary.occurrence_due_at.astimezone(ZoneInfo(summary.local_timezone)).date() == (
        wired.clock.now().astimezone(ZoneInfo(summary.local_timezone)).date()
    )
    assert not wired.store.events


def test_no_current_version_fallback_outside_effective_interval(agent, wired):
    _, registry = agent
    draft, active = _activate(wired)
    wired.enrollment.end_regimen(patient_id=PATIENT, regimen_id=active.regimen.id)
    wired.clock.advance(days=1)
    result = registry.execute(
        ToolName.GET_DOSE_STATUS, GetDoseStatusRequest(**_base(PATIENT, uuid4()), medication_id=draft.medication.id)
    )
    assert result.payload["regimen_id"] is None
    assert not result.payload["reported"] and not result.requires_confirmation


def test_history_tool_honors_explicit_date_and_excludes_future(agent, wired):
    from app.agent.tools import MedicationHistoryRequest

    _, registry = agent
    _, active = _activate(wired)
    wired.clock.advance(hours=2)
    _report(wired, active.regimen.id, IntakeStatus.REPORTED_TAKEN, key="DEMO-historical")
    wired.clock.advance(days=1)
    result = registry.execute(
        ToolName.GET_MEDICATION_HISTORY,
        MedicationHistoryRequest(
            **_base(PATIENT, uuid4()), regimen_id=active.regimen.id, target_date=date(2026, 10, 13)
        ),
    )
    assert result.payload["window_start"] == "2026-10-12T16:00:00+00:00"
    assert result.payload["window_end"] == "2026-10-13T16:00:00+00:00"
    assert len(result.payload["entries"]) == 1 and result.payload["entries"][0]["reported"]


def test_stale_occurrence_in_context_does_not_override_requested_day(agent, wired):
    orchestrator, registry = agent
    _, active = _activate(wired)
    wired.clock.advance(hours=2)
    _report(wired, active.regimen.id, IntakeStatus.REPORTED_TAKEN, key="DEMO-ref-old")
    session = orchestrator.start_session(patient_id=PATIENT)
    orchestrator.handle_turn(
        patient_id=PATIENT, session_id=session.id, turn=AgentTurn(text="Have I taken Amlodipine today?")
    )
    wired.clock.advance(hours=1)
    # A fresh request resolves its relative date from current time, not stored results.
    reply = orchestrator.handle_turn(
        patient_id=PATIENT, session_id=session.id, turn=AgentTurn(text="Have I taken it yesterday?")
    )
    assert reply.tool_results[0].payload["local_date"] == "2026-10-12"
    assert not reply.requires_confirmation and not reply.tool_results[0].payload["reported"]


def test_thread_resume_reinterprets_yesterday_without_replaying_writes(monkeypatch):
    from .test_conversation_threads import consent, send
    from .test_conversation_threads import wired as http_wired

    container, client = http_wired()
    consent(client, True)
    headers = {"Authorization": "Bearer DEMO-A"}
    original_day = container.clock.now().astimezone(ZoneInfo("Asia/Singapore")).date()
    first = send(client, "查看今天").json()
    container.clock.moment += timedelta(days=1)
    resumed = client.post(f"/api/agent/conversations/{first['conversation_id']}/resume", headers=headers)
    assert resumed.status_code == 200
    requests = []
    execute = container.registry.execute

    def capture(name, request):
        requests.append(request)
        return execute(name, request)

    monkeypatch.setattr(container.registry, "execute", capture)
    changed = client.put("/api/me/preferences", headers=headers, json={"preferred_language": "zh"})
    assert changed.status_code == 200
    response = client.post(
        "/api/agent/messages",
        headers=headers,
        json={
            "text": "查看昨天",
            "language": "zh",
            "conversation_id": first["conversation_id"],
            "session_id": resumed.json()["session_id"],
            "client_turn_id": "DEMO-next-day",
        },
    )
    assert response.status_code == 200
    assert response.json()["conversation_id"] == first["conversation_id"]
    assert "昨天" in response.json()["message"]
    assert requests and requests[-1].target_date == original_day
    assert not container.store.events
    # The full stored conversation remains distinct from the model's bounded context.
    history = client.get(f"/api/agent/conversations/{first['conversation_id']}", headers=headers).json()
    assert [row["user_text"] for row in history["entries"]] == ["查看今天", "查看昨天"]


def test_same_day_version_switch_keeps_each_occurrence_and_status(agent, wired):
    from app.contracts.dto import FrequencyRuleDTO, RegimenDraftInput

    _, registry = agent
    original, old = _activate(wired)
    wired.clock.advance(hours=2)
    _report(wired, old.regimen.id, IntakeStatus.REPORTED_TAKEN, key="DEMO-before-switch")
    wired.clock.advance(hours=1)
    wired.enrollment.end_regimen(patient_id=PATIENT, regimen_id=old.regimen.id)
    replacement = wired.enrollment.enroll_draft(
        patient_id=PATIENT,
        existing_medication_id=original.medication.id,
        draft=RegimenDraftInput(
            medication_name="Amlodipine 5mg",
            dose_amount=2,
            dose_unit="tablet",
            frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["12:00"]),
        ),
    )
    wired.enrollment.review_source_fields(patient_id=PATIENT, source_id=replacement.regimen.source_id)
    challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=PATIENT, regimen_id=replacement.regimen.id, session_id=uuid4(), session_state_version=1
    )
    wired.enrollment.confirm_challenge(patient_id=PATIENT, challenge_id=challenge.id)
    wired.enrollment.activate_regimen(
        patient_id=PATIENT,
        regimen_id=replacement.regimen.id,
        challenge_id=challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=1,
    )
    wired.clock.advance(hours=3)
    _report(wired, replacement.regimen.id, IntakeStatus.REPORTED_NOT_TAKEN, key="DEMO-after-switch")
    result = registry.execute(
        ToolName.GET_DOSE_STATUS, GetDoseStatusRequest(**_base(PATIENT, uuid4()), medication_id=original.medication.id)
    )
    records = result.payload["records"]
    assert [row["regimen_id"] for row in records] == [str(replacement.regimen.id), str(old.regimen.id)]
    assert [row["intake_status"] for row in records] == ["reported_not_taken", "reported_taken"]
    schedule = registry.execute(ToolName.CHECK_DUE_DOSE, CheckDueDoseRequest(**_base(PATIENT, uuid4()), window="today"))
    assert [(row["local_time"], row["dose_amount"]) for row in schedule.payload["schedule"]] == [
        ("08:00", 1),
        ("12:00", 2),
    ]


def test_same_name_different_medication_ids_require_clarification(agent, wired):
    _, registry = agent
    _activate(wired, name="Amlodipine 5mg")
    _activate(wired, name="Amlodipine 10mg")
    result = registry.execute(
        ToolName.GET_DOSE_STATUS, GetDoseStatusRequest(**_base(PATIENT, uuid4()), medication_name="Amlodipine")
    )
    assert result.blocked and result.payload["resolution"] == "unknown_medication"
    assert not wired.store.events
