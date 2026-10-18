"""DEMO_ONLY first-time/default collection, real application schedules, no provider claims."""

from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from app.agent.orchestrator import AgentTurn
from app.contracts.dto import FrequencyRuleDTO, RegimenDraftInput
from app.domain.errors import ValidationError
from app.domain.interval_schedule import interval_moments

from .test_agent import agent as agent
from .test_medication_evidence import attach
from .test_medication_evidence import evidence as evidence

PATIENT = UUID(int=100)


@pytest.mark.parametrize("times,source,first", [([], "default_0800", "08:00"), (["07:00"], "patient_entered", "07:00")])
def test_draft_default_is_marked_and_activation_schedules_every_eight_hours(wired, times, source, first):
    saved = wired.enrollment.enroll_draft(
        patient_id=PATIENT,
        draft=RegimenDraftInput(
            medication_name="DEMO interval",
            dose_amount=1,
            dose_unit="tablet",
            course_start_date=date(2026, 10, 14),
            frequency_rule=FrequencyRuleDTO(kind="interval", every_hours=8, local_times=times),
        ),
    )
    anchor = saved.regimen.frequency_rule["interval_anchor"]
    assert anchor == {"local_date": "2026-10-14", "local_time": first, "time_source": source}
    assert saved.regimen.state != "active" and not wired.store.events
    wired.enrollment.review_source_fields(patient_id=PATIENT, source_id=saved.regimen.source_id)
    challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=PATIENT, regimen_id=saved.regimen.id, session_id=UUID(int=999), session_state_version=1
    )
    assert challenge.regimen_id == saved.regimen.id
    wired.enrollment.confirm_challenge(patient_id=PATIENT, challenge_id=challenge.id)
    wired.enrollment.activate_regimen(
        patient_id=PATIENT,
        regimen_id=saved.regimen.id,
        challenge_id=challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=1,
    )
    rows = wired.schedule.materialize(patient_id=PATIENT, regimen_id=saved.regimen.id, days=3)
    # Window is Oct13..16 local; the reviewed first dose is Oct14, not Oct13.
    assert len(rows) == (5 if first == "08:00" else 6)
    assert all((b.due_at - a.due_at).total_seconds() == 8 * 3600 for a, b in zip(rows, rows[1:], strict=False))
    assert len({row.generation_key for row in rows}) == len(rows)
    again = wired.schedule.materialize(patient_id=PATIENT, regimen_id=saved.regimen.id, days=3)
    assert [row.id for row in again] == [row.id for row in rows]
    assert not wired.store.events


def test_missing_date_is_not_guessed_and_rejection_has_no_writes(wired):
    with pytest.raises(ValidationError, match="first-dose date"):
        wired.enrollment.enroll_draft(
            patient_id=PATIENT,
            draft=RegimenDraftInput(
                medication_name="DEMO missing anchor", frequency_rule=FrequencyRuleDTO(kind="interval", every_hours=8)
            ),
        )
    assert not wired.store.regimens and not wired.store.sources


def test_non_divisor_interval_keeps_cross_day_anchor_and_elapsed_hours_through_dst():
    frequency = {"every_hours": 7, "interval_anchor": {"local_date": "2026-10-31", "local_time": "08:00"}}
    rows = interval_moments(
        frequency, datetime(2026, 10, 31, tzinfo=UTC), datetime(2026, 11, 3, tzinfo=UTC), "America/New_York"
    )
    assert len(rows) == 9
    assert all((b - a).total_seconds() == 25200 for a, b in zip(rows, rows[1:], strict=False))
    assert rows[0] == datetime(2026, 10, 31, 12, tzinfo=UTC)


@pytest.mark.parametrize("day,time", [("2026-03-08", "02:30"), ("2026-11-01", "01:30")])
def test_dst_invalid_or_ambiguous_start_requires_review(day, time):
    with pytest.raises(ValidationError):
        interval_moments(
            {"every_hours": 8, "interval_anchor": {"local_date": day, "local_time": time}},
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
            "America/New_York",
        )


@pytest.mark.parametrize("answer,expected", [("07:00", "patient_entered"), ("使用默认时间", "default_0800")])
def test_agent_asks_before_drafting_and_resumes_only_this_session(agent, wired, answer, expected):
    orchestrator, _ = agent
    a = orchestrator.start_session(patient_id=PATIENT)
    b = orchestrator.start_session(patient_id=PATIENT)
    reply = orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=a.id,
        turn=AgentTurn(
            text="登记间隔计划",
            language="zh",
            slots={
                "medication_name": "DEMO interval agent",
                "dose_amount": 1,
                "dose_unit": "tablet",
                "frequency_kind": "interval",
                "frequency_every_hours": 8,
                "course_start_date": "2026-10-14",
            },
        ),
    )
    assert "首次服药时间" in reply.message and "默认使用 08:00" in reply.message
    assert not wired.store.regimens and not wired.store.events
    assert orchestrator.get_session(patient_id=PATIENT, session_id=b.id).context.pending_interval_enrollment is None
    result = orchestrator.handle_turn(patient_id=PATIENT, session_id=a.id, turn=AgentTurn(text=answer, language="zh"))
    assert result.tool_results and len(wired.store.regimens) == 1
    plan = next(iter(wired.store.regimens.values()))
    assert plan.frequency_rule["interval_anchor"]["time_source"] == expected
    assert plan.state != "active" and not wired.store.events and not wired.store.challenges
    assert orchestrator.get_session(patient_id=UUID(int=200), session_id=a.id) is None


def test_agent_expired_anchor_cannot_create_draft(agent, wired):
    orchestrator, _ = agent
    a = orchestrator.start_session(patient_id=PATIENT)
    orchestrator.handle_turn(
        patient_id=PATIENT,
        session_id=a.id,
        turn=AgentTurn(
            text="add",
            slots={"medication_name": "DEMO expiry", "frequency_kind": "interval", "frequency_every_hours": 8},
        ),
    )
    wired.clock.advance(minutes=11)
    reply = orchestrator.handle_turn(patient_id=PATIENT, session_id=a.id, turn=AgentTurn(text="use default time"))
    assert "expired" in reply.message and not wired.store.regimens


def test_label_interval_asks_for_time_and_preserves_source_without_inventing_clock_time(evidence, wired):
    from uuid import uuid4

    from app.contracts.source_extraction import PrintedInstructions

    service, _, _, label, _ = evidence
    label.label_kind = "dispensing"
    label.parts = PrintedInstructions(
        text="DEMO take one tablet every eight hours",
        line="DEMO interval label",
        dose={"amount": 1, "unit": "tablet"},
        every_hours=8,
    )
    task = attach(service, uuid4(), kind="pharmacy_label")
    assert task.suggested_regimen.frequency_rule.kind == "interval"
    assert task.suggested_regimen.frequency_rule.local_times == []
    assert "08:00" in service.summary(task, "en") and "首次服药" in service.summary(task, "zh")
    draft = task.suggested_regimen.model_copy(update={"course_start_date": date(2026, 10, 14)})
    saved = service.prepare_review(
        patient_id=PATIENT, task_id=task.id, draft=draft, patient_reviewed=True, distinct_product_confirmed=False
    )
    plan = wired.enrollment.get_regimen(PATIENT, saved.draft_regimen_id)
    assert plan.frequency_rule["interval_anchor"]["time_source"] == "default_0800"
    assert plan.state != "active" and not wired.store.events


def test_conversational_model_tool_asks_and_auto_continues_without_second_model_call():
    from app.agent.conversation import ConversationService
    from app.contracts.model import FunctionCall, ModelReply
    from app.infrastructure.memory_repos import InMemoryAgentSessionRepository

    from .correctness02_support import OWNER, build_harness

    class Model:
        model = "DEMO_ONLY interval selection stub"
        calls = 0

        def create(self, **kwargs):
            self.calls += 1
            return ModelReply(
                calls=[
                    FunctionCall(
                        id="DEMO-interval-call",
                        name="prepare_interval_enrollment",
                        arguments={
                            "medication_name": "DEMO new interval",
                            "every_hours": 8,
                            "dose_amount": 1,
                            "dose_unit": "tablet",
                        },
                    )
                ]
            )

    h = build_harness()
    try:
        model = Model()
        service = ConversationService(
            model=model,
            tools=h.tools,
            fallback=h.root.orchestrator,
            sessions=InMemoryAgentSessionRepository(h.root.store),
            ids=h.root.ids,
        )
        session = h.root.orchestrator.start_session(patient_id=OWNER)
        before = len(h.root.store.regimens)
        a = service.handle_turn(
            patient_id=OWNER,
            session_id=session.id,
            turn=AgentTurn(text="Add DEMO new interval every eight hours, starting 2026-10-18.", language="en"),
        )
        assert "What time is the first dose" in a.message and "default is 08:00" in a.message
        assert len(h.root.store.regimens) == before
        b = service.handle_turn(patient_id=OWNER, session_id=session.id, turn=AgentTurn(text="use default time"))
        assert model.calls == 1 and "default 08:00" in b.message and "Draft saved for review" in b.message
        assert len(h.root.store.regimens) == before + 1
        assert len(h.root.store.events) == 3 and not b.requires_confirmation
    finally:
        h.close()
