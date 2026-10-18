"""Actual disposable localhost PostgreSQL/RLS for the additive interval JSON contract."""

import os
from contextlib import contextmanager
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from app.agent.orchestrator import AgentOrchestrator, AgentTurn, DeterministicIntentRouter
from app.agent.registry import ToolRegistry
from app.application.dosing import DoseScheduleService, SelfReportService
from app.application.enrollment import MedicationEnrollmentService
from app.infrastructure.postgres_db import PostgresDatabase
from app.infrastructure.postgres_repos import build_postgres_repositories

from .conftest import CountingIdGenerator, FixedClock
from .test_conversation_threads_sql import A, B, owner
from .test_conversation_threads_sql import db as db

pytestmark = pytest.mark.skipif(not os.environ.get("THREADS_TEST_DSN"), reason="isolated PostgreSQL required")


def test_actual_sql_anchor_pending_context_activation_and_owner_isolation(db):
    import psycopg
    from psycopg.rows import dict_row

    dsn = f"postgresql://postgres@127.0.0.1:55439/{db.info.dbname}"

    @contextmanager
    def scoped(patient):
        with psycopg.connect(dsn, row_factory=dict_row) as connection, owner(connection, patient):
            yield connection

    repos = build_postgres_repositories(PostgresDatabase(dsn=dsn), session=scoped)
    clock = FixedClock(datetime.now(UTC))
    ids = CountingIdGenerator()
    enrollment = MedicationEnrollmentService(
        medications=repos.medications,
        regimens=repos.regimens,
        sources=repos.sources,
        source_fields=repos.source_fields,
        dose_rules=repos.dose_rules,
        challenges=repos.challenges,
        clock=clock,
        ids=ids,
    )
    schedule = DoseScheduleService(
        regimens=repos.regimens, rules=repos.dose_rules, occurrences=repos.occurrences, clock=clock, ids=ids
    )
    reports = SelfReportService(
        regimens=repos.regimens,
        medications=repos.medications,
        occurrences=repos.occurrences,
        events=repos.events,
        challenges=repos.challenges,
        sessions=repos.sessions,
        clock=clock,
        ids=ids,
    )
    registry = ToolRegistry(
        enrollment=enrollment, schedule=schedule, self_report=reports, traces=repos.traces, clock=clock, ids=ids
    )
    agent = AgentOrchestrator(
        registry=registry, sessions=repos.sessions, router=DeterministicIntentRouter(), clock=clock, ids=ids
    )
    session = agent.start_session(patient_id=A)
    today = clock.now().astimezone(ZoneInfo("Asia/Singapore")).date()
    reply = agent.handle_turn(
        patient_id=A,
        session_id=session.id,
        turn=AgentTurn(
            text="DEMO interval enrollment",
            slots={
                "medication_name": "DEMO interval SQL",
                "dose_amount": 1,
                "dose_unit": "tablet",
                "frequency_kind": "interval",
                "frequency_every_hours": 8,
                "course_start_date": today,
            },
        ),
    )
    assert "08:00" in reply.message and not enrollment.list_medications(A)
    pending = repos.sessions.get(A, session.id).context.pending_interval_enrollment
    assert pending.every_hours == 8 and pending.course_start_date == today
    assert repos.sessions.get(B, session.id) is None
    reply = agent.handle_turn(patient_id=A, session_id=session.id, turn=AgentTurn(text="use default time"))
    assert "default 08:00" in reply.message
    medication = enrollment.list_medications(A)[0]
    plan = enrollment.list_regimens(A, medication.id)[0]
    assert plan.frequency_rule["interval_anchor"]["time_source"] == "default_0800"
    assert enrollment.get_regimen(B, plan.id) is None
    enrollment.review_source_fields(patient_id=A, source_id=plan.source_id)
    session = agent.await_confirmation(patient_id=A, session_id=session.id)
    challenge, _ = enrollment.request_activation_challenge(
        patient_id=A, regimen_id=plan.id, session_id=session.id, session_state_version=session.state_version
    )
    enrollment.confirm_challenge(patient_id=A, challenge_id=challenge.id)
    enrollment.activate_regimen(
        patient_id=A,
        regimen_id=plan.id,
        challenge_id=challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=session.state_version,
    )
    moments = schedule.materialize(patient_id=A, regimen_id=plan.id, days=3)
    assert len(moments) >= 6
    assert all((b.due_at - a.due_at).total_seconds() == 28800 for a, b in zip(moments, moments[1:], strict=False))
    assert db.execute("select count(*) from dose_events").fetchone()[0] == 0
    with owner(db, B):
        assert db.execute("select count(*) from regimen_versions").fetchone()[0] == 0
