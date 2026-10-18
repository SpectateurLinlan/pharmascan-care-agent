"""Explicit DEMO_ONLY acceptance audit, not default CI discovery.

Run this file explicitly. Failures intentionally expose unmet patient requirements;
no xfail/skip, live model calls, production SQL or weakened assertions.
"""

import json
import re
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.agent.long_term_tools import execute_care_tool
from app.agent.memory import record_context
from app.agent.model_tools import ModelTools, model_tool_schemas
from app.agent.orchestrator import AgentTurn
from app.agent.tools import (
    EnrollMedicationRequest,
    GetDoseStatusRequest,
    ListActiveMedicationsRequest,
    MedicationHistoryRequest,
)
from app.contracts.agent_context import AgentContext
from app.contracts.dto import FrequencyRuleDTO, RegimenDraftInput
from app.contracts.enums import AgentIntent, ErrorCode, IntakeStatus, ToolName
from app.contracts.long_term import CareTaskInput
from app.contracts.observations import ObservationInput
from app.infrastructure.memory_repos import InMemoryToolTraceRepository

from . import test_dose_status_query as dose_fixtures
from . import test_long_term_care as care_fixtures
from .test_dose_status_query import PATIENT, _activate, _base, _report

dose_agent = dose_fixtures.agent
care = care_fixtures.care
stock = care_fixtures.stock


SQL = (Path(__file__).resolve().parents[2] / "supabase/migrations/202610180028_agent_overlap_audit.sql").read_text(
    encoding="utf-8"
)


def enum_values(key):
    block = SQL.split(f"WHEN '{key}' THEN", 1)[1].split("WHEN '", 1)[0]
    return set(re.findall(r"'([^']+)'", re.search(r"NOT IN\s*\((.*?)\)", block, re.S).group(1)))


@pytest.fixture(autouse=True)
def trace_contract(monkeypatch):
    """Apply current migration 028's redacted-summary clauses to actual memory trace writes."""
    original = InMemoryToolTraceRepository.add
    keys = set(re.findall(r"WHEN '([^']+)' THEN", SQL))

    def checked(repo, trace):
        for summary in (trace.request_summary, trace.response_summary):
            assert set(summary) <= keys, f"Audit CHECK: unexpected keys {set(summary) - keys}"
            assert len(json.dumps(summary, ensure_ascii=False).encode()) <= 1024
            for key, value in summary.items():
                if key in {"state", "error_code", "intake_status", "decision"}:
                    assert value in enum_values(key), f"Audit CHECK rejects {key}={value}"
                elif key in {"item_count", "missing_count"}:
                    assert type(value) is int and 0 <= value <= 9999999
                elif key == "demo_only":
                    assert value is True
                elif key == "already_recorded":
                    assert type(value) is bool
                elif key == "visual_status":
                    assert value == "not_checked"
        original(repo, trace)

    monkeypatch.setattr(InMemoryToolTraceRepository, "add", checked)


@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize(
    "status,words",
    [
        (IntakeStatus.REPORTED_TAKEN, ("reported taking", "已服")),
        (IntakeStatus.REPORTED_NOT_TAKEN, ("reported not taking", "未服")),
        (IntakeStatus.UNSURE, ("unsure", "不确定")),
        (None, ("cannot tell", "没有记录")),
    ],
)
def test_today_intake_answer_has_name_and_correct_patient_status(dose_agent, wired, language, status, words):
    agent, _ = dose_agent
    _, active = _activate(wired)
    wired.clock.advance(hours=2)
    if status:
        _report(wired, active.regimen.id, status, key="DEMO-audit-today")
    before = len(wired.store.events)
    question = "Have I taken Amlodipine today?" if language == "en" else "我今天吃过 Amlodipine 吗？"
    reply = agent.handle_turn(patient_id=PATIENT, session_id=uuid4(), turn=AgentTurn(text=question, language=language))
    print(question, "=>", reply.message)
    assert len(wired.store.events) == before and not reply.requires_confirmation
    assert "Amlodipine" in reply.message and words[language == "zh"] in reply.message


def opposing_days(wired):
    _, active = _activate(wired)
    wired.clock.advance(hours=2)
    _report(wired, active.regimen.id, IntakeStatus.REPORTED_TAKEN, key="DEMO-yesterday-taken")
    wired.clock.advance(days=1)
    _report(wired, active.regimen.id, IntakeStatus.REPORTED_NOT_TAKEN, key="DEMO-today-not-taken")
    return active


def test_yesterday_tool_must_not_return_todays_opposite_status(dose_agent, wired):
    _, registry = dose_agent
    opposing_days(wired)
    result = registry.execute(
        ToolName.GET_DOSE_STATUS,
        GetDoseStatusRequest(
            **_base(PATIENT, uuid4()),
            medication_name="Amlodipine",
            day_offset=-1,
        ),
    )
    assert result.payload["intake_status"] == "reported_taken", result.payload


@pytest.mark.parametrize("question", ["Did I take Amlodipine yesterday?", "我昨天吃过 Amlodipine 吗？", "查看昨天"])
def test_yesterday_natural_question_must_preserve_day_and_status(dose_agent, wired, question):
    agent, _ = dose_agent
    opposing_days(wired)
    reply = agent.handle_turn(
        patient_id=PATIENT,
        session_id=uuid4(),
        turn=AgentTurn(
            text=question,
            language="en" if question.isascii() else "zh",
            slots={"medication_name": "Amlodipine"},
        ),
    )
    print(question, "=>", reply.message)
    assert any(word in reply.message for word in ("yesterday", "昨天", "2026-10-13"))
    assert "Amlodipine" in reply.message and any(word in reply.message for word in ("reported taking", "已服"))


def test_model_status_schema_can_express_requested_yesterday():
    schema = next(row for row in model_tool_schemas() if row["name"] == "get_dose_status")
    assert "day_offset" in schema["parameters"]["properties"]


@pytest.mark.parametrize("language", ["en", "zh"])
def test_current_list_answer_names_actual_medicines(dose_agent, wired, language):
    agent, registry = dose_agent
    _activate(wired)
    result = registry.execute(ToolName.LIST_ACTIVE_MEDICATIONS, ListActiveMedicationsRequest(**_base(PATIENT, uuid4())))
    answer = agent.render_results(AgentIntent.CLARIFICATION, [result], language)
    print("Current medicines =>", answer)
    assert "Amlodipine 5mg" in answer


@pytest.mark.parametrize("language,question", [("en", "What medicine should I take today?"), ("zh", "今天吃什么药？")])
def test_today_schedule_answer_has_drug_quantity_time(dose_agent, wired, language, question):
    agent, _ = dose_agent
    _activate(wired)
    reply = agent.handle_turn(patient_id=PATIENT, session_id=uuid4(), turn=AgentTurn(text=question, language=language))
    print(question, "=>", reply.message)
    assert "Amlodipine" in reply.message and "08:00" in reply.message
    assert "1" in reply.message and ("tablet" in reply.message or "片" in reply.message)
    assert "missed" in reply.message or "不等于漏服" in reply.message


@pytest.mark.parametrize("language", ["en", "zh"])
def test_history_answer_describes_records_not_only_a_count_or_link(dose_agent, wired, language):
    agent, registry = dose_agent
    active = opposing_days(wired)
    result = registry.execute(
        ToolName.GET_MEDICATION_HISTORY,
        MedicationHistoryRequest(
            **_base(PATIENT, uuid4()),
            regimen_id=active.regimen.id,
            days=7,
        ),
    )
    assert {row["intake_status"] for row in result.payload["entries"]} >= {"reported_taken", "reported_not_taken"}
    answer = agent.render_results(AgentIntent.MEDICATION_HISTORY, [result], language)
    print("History =>", answer)
    assert "Amlodipine" in answer and any(word in answer for word in ("reported taking", "已服"))


def test_context_individual_string_bounds_also_fit_database_byte_budget():
    context = AgentContext()
    for _ in range(6):
        context = record_context(
            context, text="合成说明" * 125, message="合成回复" * 175, intent="clarification", language="zh", results=[]
        )
    context = AgentContext.model_validate(context.model_dump())
    size = len(json.dumps(context.model_dump(mode="json"), ensure_ascii=False).encode())
    assert size <= 20000, f"agent_context_bounds CHECK rejects {size} bytes despite individually valid strings"


def test_every_application_error_code_can_be_audited_under_existing_sql():
    missing = {code.value for code in ErrorCode} - enum_values("error_code")
    assert not missing, f"Trace CHECK rejects current application error codes: {sorted(missing)}"


def test_duplicate_enrollment_returns_clear_overlap_without_audit_check_failure(dose_agent, wired):
    _, registry = dose_agent
    _activate(wired)
    reply = registry.execute(
        ToolName.ENROLL_MEDICATION_DRAFT,
        EnrollMedicationRequest(
            **_base(PATIENT, uuid4()),
            medication_name="Amlodipine 5mg",
            dose_amount=1,
            dose_unit="tablet",
            frequency_kind="daily",
            frequency_local_times=["08:00"],
        ),
    )
    assert reply.blocked and reply.error_code == "REGIMEN_OVERLAP"


def care_read(care, name, language="zh", **arguments):
    service, _, _, patient, _ = care
    return execute_care_tool(
        service,
        name=name,
        arguments=arguments or {"days": 7},
        patient_id=patient,
        session_id=uuid4(),
        turn_id="DEMO-audit",
        text="DEMO read",
        language=language,
        timezone="Asia/Singapore",
    ).data["patient_safe_summary"]


def test_inventory_answer_distinguishes_unknown_and_estimate(care):
    service, _, _, patient, draft = care
    assert "未知" in care_read(care, "get_medication_inventory", medication_id=str(draft.medication.id))
    service.record_stock(patient, draft.medication.id, stock(3), "Asia/Singapore")
    answer = care_read(care, "get_medication_inventory", medication_id=str(draft.medication.id))
    assert "3" in answer and "估算" in answer and "盘点" in answer


@pytest.mark.parametrize("language", ["en", "zh"])
def test_followup_answer_uses_patient_local_due_date(care, wired, language):
    service, _, _, patient, draft = care
    due = wired.clock.now() + timedelta(hours=18)  # 2026-10-14 01:00 Singapore, 13th in UTC.
    service.create_task(
        patient,
        CareTaskInput(
            id=uuid4(),
            category="medication_review",
            title="DEMO pharmacist review",
            due_at=due,
            medication_id=draft.medication.id,
            regimen_id=draft.regimen.id,
            confirmed=True,
        ),
    )
    answer = care_read(care, "get_unresolved_follow_ups", language=language)
    print("Upcoming follow-up =>", answer)
    assert "DEMO pharmacist review" in answer and "2026-10-14" in answer


def test_health_records_answer_does_not_silently_omit_existing_notes(care, wired):
    _, _, observations, patient, _ = care
    descriptions = ["DEMO fatigue", "DEMO headache", "DEMO feeling well"]
    for description in descriptions:
        observations.save(
            patient,
            ObservationInput(id=uuid4(), description=description, occurred_at=wired.clock.now(), confirmed=True),
        )
        wired.clock.advance(seconds=1)
    answer = care_read(care, "get_health_observations")
    print("Health notes =>", answer)
    assert all(text in answer for text in descriptions) or any(
        word in answer for word in ("部分", "最近两", "查看全部")
    )


def test_past_intake_claim_never_prepares_todays_confirmation(dose_agent, wired):
    agent, registry = dose_agent
    _, active = _activate(wired)
    wired.clock.advance(hours=2)
    session = agent.start_session(patient_id=PATIENT)
    output = ModelTools(registry=registry, fallback=agent).execute(
        name="prepare_self_report",
        arguments={"regimen_id": str(active.regimen.id), "intake_status": "taken"},
        patient_id=PATIENT,
        session_id=session.id,
        correlation_id=uuid4(),
        client_turn_id="DEMO-past-claim",
        turn=AgentTurn(text="I took Amlodipine yesterday", language="en"),
    )
    assert not output.prepared_reply or not output.prepared_reply.requires_confirmation, (
        "Historical claim produced a current-day dose confirmation instead of explaining unsupported backfill"
    )


def test_historical_question_keeps_original_regimen_version(dose_agent, wired):
    _, registry = dose_agent
    draft, old = _activate(wired)
    wired.clock.advance(hours=2)
    _report(wired, old.regimen.id, IntakeStatus.REPORTED_TAKEN, key="DEMO-old-version")
    wired.clock.advance(days=1)
    wired.enrollment.end_regimen(patient_id=PATIENT, regimen_id=old.regimen.id)
    new = wired.enrollment.enroll_draft(
        patient_id=PATIENT,
        existing_medication_id=draft.medication.id,
        draft=RegimenDraftInput(
            medication_name="Amlodipine 5mg",
            dose_amount=2,
            dose_unit="tablet",
            frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["08:00"]),
        ),
    )
    wired.enrollment.review_source_fields(patient_id=PATIENT, source_id=new.regimen.source_id)
    challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=PATIENT, regimen_id=new.regimen.id, session_id=uuid4(), session_state_version=1
    )
    wired.enrollment.confirm_challenge(patient_id=PATIENT, challenge_id=challenge.id)
    wired.enrollment.activate_regimen(
        patient_id=PATIENT,
        regimen_id=new.regimen.id,
        challenge_id=challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=1,
    )
    original = registry.execute(
        ToolName.GET_MEDICATION_HISTORY,
        MedicationHistoryRequest(**_base(PATIENT, uuid4()), regimen_id=old.regimen.id, days=7),
    )
    assert any(row["intake_status"] == "reported_taken" for row in original.payload["entries"])
    queried = registry.execute(
        ToolName.GET_DOSE_STATUS,
        GetDoseStatusRequest(**_base(PATIENT, uuid4()), medication_id=draft.medication.id, day_offset=-1),
    )
    assert queried.payload["regimen_id"] == str(old.regimen.id), (
        "Yesterday's question resolved the replacement version instead of the version owning yesterday's report"
    )


def test_foreign_patient_medication_id_cannot_be_read(dose_agent, wired):
    _, registry = dose_agent
    foreign = uuid4()
    draft, _ = _activate(wired, patient_id=foreign, name="DEMO private medicine")
    result = registry.execute(
        ToolName.GET_DOSE_STATUS, GetDoseStatusRequest(**_base(PATIENT, uuid4()), medication_id=draft.medication.id)
    )
    assert result.blocked and result.error_code == "NOT_FOUND"
    assert "DEMO private medicine" not in json.dumps(result.model_dump(mode="json"))


def test_as_needed_medicine_is_not_fabricated_as_a_fixed_today_dose(dose_agent, wired):
    agent, _ = dose_agent
    draft = wired.enrollment.enroll_draft(
        patient_id=PATIENT,
        draft=RegimenDraftInput(
            medication_name="DEMO as-needed medicine",
            dose_amount=1,
            dose_unit="tablet",
            is_prn=True,
            food_instruction="DEMO recorded as-needed instruction",
        ),
    )
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
    reply = agent.handle_turn(
        patient_id=PATIENT, session_id=uuid4(), turn=AgentTurn(text="今天吃什么药？", language="zh")
    )
    assert "按需" in reply.message and "不列入固定安排" in reply.message
    assert not wired.store.events
