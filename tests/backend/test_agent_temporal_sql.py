"""Actual disposable local PostgreSQL contracts; no remote DSN or production writes."""

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from app.agent.registry import ToolRegistry
from app.agent.tools import EnrollMedicationRequest
from app.contracts.agent_context import AgentContext, CandidateReference, ClarificationContext, RecentTurn
from app.contracts.context_bounds import bounded_context
from app.contracts.enums import ErrorCode, ToolName

from .test_conversation_threads_sql import A, B, append, owner, seeded
from .test_conversation_threads_sql import db as db
from .test_dose_status_query import _activate, _base

pytestmark = pytest.mark.skipif(not os.environ.get("THREADS_TEST_DSN"), reason="isolated PostgreSQL required")


def test_028_additive_rollback_before_new_error_rows(db):
    from psycopg import Rollback

    sql = Path("supabase/rollback/202610180028_agent_overlap_audit_down.sql").read_text(encoding="utf-8-sig")
    with db.transaction():
        db.execute(sql.replace("BEGIN;", "").replace("COMMIT;", ""))
        assert db.execute('select core_trace_summary_is_safe(\'{"error_code":"REGIMEN_OVERLAP"}\')').fetchone() == (
            False,
        )
        raise Rollback()
    assert db.execute('select core_trace_summary_is_safe(\'{"error_code":"REGIMEN_OVERLAP"}\')').fetchone() == (True,)


@pytest.mark.parametrize("code", [code.value for code in ErrorCode])
def test_closed_application_error_contract_in_postgres(db, code):
    from psycopg.types.json import Jsonb

    with owner(db, A):
        assert db.execute("select core_trace_summary_is_safe(%s)", (Jsonb({"error_code": code}),)).fetchone() == (True,)


@pytest.mark.parametrize(
    "summary",
    [
        {"error_code": "arbitrary free text"},
        {"patient_text": "DEMO private"},
        {"visual_status": "matched"},
        {"demo_only": False},
        {"state": "made_up"},
        {"item_count": -1},
        {"error_code": "a" * 1100},
    ],
)
def test_redaction_guards_still_reject_invalid_summaries(db, summary):
    from psycopg.types.json import Jsonb

    assert db.execute("select core_trace_summary_is_safe(%s)", (Jsonb(summary),)).fetchone() == (False,)


def test_real_application_overlap_is_audited_and_owner_isolated(db, wired):
    import psycopg
    from psycopg.types.json import Jsonb

    _, session = seeded(db)

    class SqlTraces:
        def add(self, trace):
            with owner(db, trace.patient_id):
                db.execute(
                    "insert into agent_tool_calls(id,patient_id,session_id,correlation_id,tool_name,tool_status,"
                    "request_summary,response_summary) values(%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        trace.id,
                        trace.patient_id,
                        trace.session_id,
                        trace.correlation_id,
                        trace.tool_name,
                        trace.tool_status,
                        Jsonb(trace.request_summary),
                        Jsonb(trace.response_summary),
                    ),
                )

        def list_for_session(self, patient_id, session_id):
            raise NotImplementedError("No read is used by this contract test")

    _activate(wired, patient_id=A)
    registry = ToolRegistry(
        enrollment=wired.enrollment,
        schedule=wired.schedule,
        self_report=wired.self_report,
        traces=SqlTraces(),
        clock=wired.clock,
        ids=wired.ids,
    )
    result = registry.execute(
        ToolName.ENROLL_MEDICATION_DRAFT,
        EnrollMedicationRequest(
            **_base(A, session),
            medication_name="Amlodipine 5mg",
            dose_amount=1,
            dose_unit="tablet",
            frequency_kind="daily",
            frequency_local_times=["08:00"],
        ),
    )
    assert result.blocked and result.error_code == "REGIMEN_OVERLAP"
    with owner(db, A):
        assert db.execute(
            "select response_summary->>'error_code' from agent_tool_calls where session_id=%s", (session,)
        ).fetchone() == ("REGIMEN_OVERLAP",)
    with owner(db, B):
        assert db.execute("select count(*) from agent_tool_calls where session_id=%s", (session,)).fetchone() == (0,)
    with pytest.raises(psycopg.errors.RaiseException), db.transaction():
        sql = Path("supabase/rollback/202610180028_agent_overlap_audit_down.sql").read_text(encoding="utf-8-sig")
        db.execute(sql.replace("BEGIN;", "").replace("COMMIT;", ""))


@pytest.mark.parametrize("text", ["合成中文😀" * 175, "DEMO English 中文 😀" * 60])
def test_actual_context_jsonb_bytes_and_full_history_retained(db, text):
    import psycopg
    from psycopg.types.json import Jsonb

    conversation, session = seeded(db)
    turn = append(db, conversation, session, text="DEMO 完整历史" * 1000)
    context = AgentContext(
        conversation_summary="😀" * 600,
        recent_turns=[RecentTurn(user=text[:500], assistant=text[:700]) for _ in range(6)],
        awaiting_clarification=ClarificationContext(
            candidates=[
                CandidateReference(medication_id=uuid4(), regimen_id=uuid4(), display_name="😀" * 200)
                for _ in range(10)
            ]
        ),
    )
    bounded = bounded_context(context)
    assert len(json.dumps(bounded.model_dump(mode="json"), ensure_ascii=False).encode()) <= 16000
    with owner(db, A):
        db.execute(
            "update agent_sessions set context=%s where id=%s", (Jsonb(bounded.model_dump(mode="json")), session)
        )
        size = db.execute("select octet_length(context::text) from agent_sessions where id=%s", (session,)).fetchone()[
            0
        ]
        assert size <= 20000
        assert (
            db.execute("select full_assistant_text from conversation_turns where id=%s", (turn,)).fetchone()[0]
            == "DEMO 完整历史" * 1000
        )
    with pytest.raises(psycopg.errors.CheckViolation), owner(db, A):
        raw = context.model_dump(mode="json")
        raw["recent_turns"] = [{"user": "😀" * 500, "assistant": "😀" * 700}] * 6
        db.execute("update agent_sessions set context=%s where id=%s", (Jsonb(raw), session))
    with owner(db, B):
        assert db.execute("select count(*) from agent_sessions where id=%s", (session,)).fetchone() == (0,)


def test_historical_tool_reads_actual_postgres_versions_under_patient_rls(db, wired):
    from contextlib import contextmanager
    from datetime import UTC, datetime

    import psycopg
    from app.agent.tools import GetDoseStatusRequest
    from app.application.dosing import DoseScheduleService, SelfReportService
    from app.application.enrollment import MedicationEnrollmentService
    from app.infrastructure.postgres_db import PostgresDatabase
    from app.infrastructure.postgres_repos import build_postgres_repositories
    from psycopg.rows import dict_row

    from .test_draft_deletion_sql import activate_seed

    _, medication, plan = activate_seed(db)
    dsn = f"postgresql://postgres@127.0.0.1:55439/{db.info.dbname}"

    @contextmanager
    def patient_session(patient):
        with psycopg.connect(dsn, row_factory=dict_row) as connection:
            with owner(connection, patient):
                yield connection

    repos = build_postgres_repositories(PostgresDatabase(dsn=dsn), session=patient_session)
    from .conftest import FixedClock

    clock = FixedClock(datetime.now(UTC))
    enrollment = MedicationEnrollmentService(
        medications=repos.medications,
        regimens=repos.regimens,
        sources=repos.sources,
        source_fields=repos.source_fields,
        dose_rules=repos.dose_rules,
        challenges=repos.challenges,
        clock=clock,
        ids=wired.ids,
    )
    schedule = DoseScheduleService(
        regimens=repos.regimens, rules=repos.dose_rules, occurrences=repos.occurrences, clock=clock, ids=wired.ids
    )
    reports = SelfReportService(
        regimens=repos.regimens,
        medications=repos.medications,
        occurrences=repos.occurrences,
        events=repos.events,
        challenges=repos.challenges,
        sessions=repos.sessions,
        clock=clock,
        ids=wired.ids,
    )
    enrollment.end_regimen(patient_id=A, regimen_id=plan)
    clock.advance(days=1)
    registry = ToolRegistry(
        enrollment=enrollment, schedule=schedule, self_report=reports, traces=wired.traces, clock=clock, ids=wired.ids
    )
    historical = registry.execute(
        ToolName.GET_DOSE_STATUS, GetDoseStatusRequest(**_base(A, uuid4()), medication_id=medication, day_offset=-1)
    )
    assert historical.ok and historical.payload["regimen_id"] == str(plan)
    assert not historical.payload["regimen_active"] and historical.payload["intake_status"] == "no_report"
    today = registry.execute(
        ToolName.GET_DOSE_STATUS, GetDoseStatusRequest(**_base(A, uuid4()), medication_id=medication)
    )
    assert today.ok and today.payload["regimen_id"] is None  # never fall back to newest ended plan
    foreign = registry.execute(
        ToolName.GET_DOSE_STATUS, GetDoseStatusRequest(**_base(B, uuid4()), medication_id=medication, day_offset=-1)
    )
    assert foreign.blocked and foreign.error_code == "NOT_FOUND"
