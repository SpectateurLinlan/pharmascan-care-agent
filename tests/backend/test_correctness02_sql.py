"""Actual localhost PostgreSQL repositories/RLS -> tools -> HTTP -> final reply.

Only the existing guarded disposable-database fixture may be used.
"""

import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from app.agent.conversation import ConversationService
from app.agent.model_tools import ModelTools
from app.agent.orchestrator import AgentOrchestrator, DeterministicIntentRouter
from app.agent.registry import ToolRegistry
from app.application.ai_quota import QuotaAgent
from app.application.dosing import DoseScheduleService, SelfReportService
from app.application.enrollment import MedicationEnrollmentService
from app.application.medication_understanding import MedicationUnderstandingService
from app.contracts.dose_display import DoseBasis
from app.contracts.dto import FrequencyRuleDTO, RegimenDraftInput
from app.contracts.preferences import PreferenceUpdate
from app.infrastructure.memory_quota import MemoryQuota
from app.infrastructure.openfda_knowledge import OpenFDAKnowledge
from app.infrastructure.postgres_db import PostgresDatabase
from app.infrastructure.postgres_repos import build_postgres_repositories
from app.transport.app_factory import create_app
from app.transport.auth import AuthBoundary, StaticTokenVerifier
from app.transport.container import build_container
from fastapi.testclient import TestClient

from .conftest import FixedClock
from .correctness02_support import LABELS, StubModel
from .test_conversation_threads_sql import A, B, owner, seeded
from .test_conversation_threads_sql import db as db

pytestmark = pytest.mark.skipif(not os.environ.get("THREADS_TEST_DSN"), reason="isolated PostgreSQL required")


def test_large_read_choice_metadata_respects_real_jsonb_bound_and_keeps_transcript(db):
    from datetime import timedelta

    from app.contracts.agent_context import AgentContext, RecentTurn
    from app.contracts.context_bounds import bounded_context
    from app.contracts.medication_dialogue import MedicationChoice, MedicationDialogue, MedicationOption
    from psycopg.types.json import Jsonb

    from .test_conversation_threads_sql import append

    conversation, session = seeded(db)
    full_text = "DEMO 完整原始问答😀" * 800
    turn = append(db, conversation, session, text=full_text)
    options = [
        MedicationOption(
            medication_id=uuid4(),
            regimen_id=uuid4(),
            display_name="合成药" * 60,
            label="合成药" * 100,
            ingredient_names=["成分" * 100] * 8,
        )
        for _ in range(10)
    ]
    context = AgentContext(
        medication_dialogue=MedicationDialogue(
            choice=MedicationChoice(
                id=uuid4(),
                question="general_use",
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
                options=options,
            )
        ),
        recent_turns=[RecentTurn(user="当前问题😀", assistant="请重新选择")],
    )
    bounded = bounded_context(context)
    with owner(db, A):
        db.execute(
            "update agent_sessions set context=%s where id=%s", (Jsonb(bounded.model_dump(mode="json")), session)
        )
        assert (
            db.execute("select octet_length(context::text) from agent_sessions where id=%s", (session,)).fetchone()[0]
            <= 20000
        )
        assert (
            db.execute("select full_assistant_text from conversation_turns where id=%s", (turn,)).fetchone()[0]
            == full_text
        )
    assert bounded.recent_turns[-1].user == "当前问题😀"
    assert bounded.medication_dialogue is None


def test_actual_sql_patient_reads_choices_knowledge_and_http_answer(db):
    exercise_sql_patient_reads(db)


def exercise_sql_patient_reads(db, *, model=None, first_question="Which medicines do I have?", write_report=True):
    """Shared real-SQL acceptance path; optional model injection never changes facts/RLS."""
    import psycopg
    from psycopg.rows import dict_row

    dsn = f"postgresql://postgres@127.0.0.1:55439/{db.info.dbname}"

    @contextmanager
    def scoped(patient):
        with psycopg.connect(dsn, row_factory=dict_row) as c:
            with owner(c, patient):
                yield c

    repos = build_postgres_repositories(PostgresDatabase(dsn=dsn), session=scoped)
    clock = FixedClock(datetime.now(UTC))
    root = build_container(
        clock=clock,
        auth=AuthBoundary(
            mode="supabase",
            verifier=StaticTokenVerifier({"DEMO.sql-A": {"sub": str(A)}, "DEMO.sql-B": {"sub": str(B)}}),
        ),
    )
    enrollment = MedicationEnrollmentService(
        medications=repos.medications,
        regimens=repos.regimens,
        sources=repos.sources,
        source_fields=repos.source_fields,
        dose_rules=repos.dose_rules,
        challenges=repos.challenges,
        clock=clock,
        ids=root.ids,
    )
    schedule = DoseScheduleService(
        regimens=repos.regimens, rules=repos.dose_rules, occurrences=repos.occurrences, clock=clock, ids=root.ids
    )
    reports = SelfReportService(
        regimens=repos.regimens,
        medications=repos.medications,
        occurrences=repos.occurrences,
        events=repos.events,
        challenges=repos.challenges,
        sessions=repos.sessions,
        clock=clock,
        ids=root.ids,
    )
    registry = ToolRegistry(
        enrollment=enrollment, schedule=schedule, self_report=reports, traces=repos.traces, clock=clock, ids=root.ids
    )
    agent = AgentOrchestrator(
        registry=registry, sessions=repos.sessions, router=DeterministicIntentRouter(), clock=clock, ids=root.ids
    )
    for name, strength in [("AMLODIPINE", "5 mg"), ("METFORMIN HYDROCHLORIDE", "500 mg")]:
        draft = enrollment.enroll_draft(
            patient_id=A,
            draft=RegimenDraftInput(
                medication_name=name,
                dose_amount=1,
                dose_unit="tablet",
                frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["08:00"]),
            ),
            dose_basis=DoseBasis(strength_text=strength, form="tablet", patient_checked=True),
        )
        enrollment.review_source_fields(patient_id=A, source_id=draft.regimen.source_id)
        activation = agent.start_session(patient_id=A)
        activation = agent.await_confirmation(patient_id=A, session_id=activation.id)
        challenge, _ = enrollment.request_activation_challenge(
            patient_id=A,
            regimen_id=draft.regimen.id,
            session_id=activation.id,
            session_state_version=activation.state_version,
        )
        enrollment.confirm_challenge(patient_id=A, challenge_id=challenge.id)
        enrollment.activate_regimen(
            patient_id=A,
            regimen_id=draft.regimen.id,
            challenge_id=challenge.id,
            session_state="awaiting_confirmation",
            session_state_version=activation.state_version,
        )
    provider = OpenFDAKnowledge(
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"results": LABELS}))),
        clock,
        monotonic=lambda: 0,
    )
    tools = ModelTools(
        registry=registry,
        fallback=agent,
        medication_understanding=MedicationUnderstandingService(enrollment, provider, clock),
        clock=clock,
    )
    conversation = ConversationService(
        model=model or StubModel(), tools=tools, fallback=agent, sessions=repos.sessions, ids=root.ids
    )
    root.enrollment, root.schedule, root.self_report, root.registry, root.orchestrator = (
        enrollment,
        schedule,
        reports,
        registry,
        agent,
    )
    root.preferences.save(A, PreferenceUpdate(conversation_history_enabled=False))
    root.ai_agent = QuotaAgent(
        repository=MemoryQuota(clock=clock, nonce_factory=lambda: str(uuid4()), limit=200),
        conversation=conversation,
        fallback=agent,
        daily_limit=200,
    )
    session = agent.start_session(patient_id=A)
    rows = []
    with TestClient(create_app(container=root)) as client:

        def ask(text, selection=None, actor="A", sid=None):
            request = {"text": text, "session_id": str(sid or session.id), "client_turn_id": str(uuid4())}
            if selection:
                request["medication_selection"] = selection
            response = client.post(
                "/api/agent/messages", headers={"Authorization": "Bearer DEMO.sql-" + actor}, json=request
            )
            assert response.status_code == 200, response.text
            data = response.json()
            rows.append(
                {
                    "user": text,
                    "actual": data["message"],
                    "traces": data["tool_traces"],
                    "selection": selection,
                    "mode": data["mode"],
                    "actor": actor,
                }
            )
            return data

        listed = ask(first_question)
        assert "AMLODIPINE" in listed["message"] and "METFORMIN HYDROCHLORIDE" in listed["message"]
        choice = ask("What is this medicine for?")["medication_choice"]
        assert len(choice["options"]) == 2
        selected = choice["options"][1]
        explained = ask(selected["label"], {"choice_id": choice["id"], "medication_id": selected["medication_id"]})
        assert "blood sugar" in explained["message"] and "https://" not in explained["message"]
        assert (
            "dailymed.nlm.nih.gov" in explained["tool_traces"][-1]["payload"]["general_knowledge"]["sources"][0]["url"]
        )
        assert explained["tool_traces"][-1]["payload"]["medication_id"] == selected["medication_id"]
        saved = repos.sessions.get(A, session.id)
        assert (
            saved.context.referenced_medication_id == selected["medication_id"]
            or str(saved.context.referenced_medication_id) == selected["medication_id"]
        )
        assert repos.sessions.get(B, session.id) is None
        foreign = agent.start_session(patient_id=B)
        denied = ask(
            selected["label"],
            {"choice_id": choice["id"], "medication_id": selected["medication_id"]},
            actor="B",
            sid=foreign.id,
        )
        assert "AMLODIPINE" not in denied["message"] and "METFORMIN" not in denied["message"]
        assert not denied["requires_confirmation"]
        history = ask("Show my medication history.")
        assert history["tool_traces"][0]["status"] == "success" and "No stored records" in history["message"]
    with owner(db, B):
        assert db.execute("select count(*) from agent_sessions where id=%s", (session.id,)).fetchone() == (0,)
        assert db.execute("select count(*) from agent_tool_calls where session_id=%s", (session.id,)).fetchone() == (0,)
    assert db.execute("select count(*) from dose_events").fetchone() == (0,)
    if not write_report:
        return rows
    lines = [
        "# Actual Backend + Synthetic PostgreSQL — Correctness 02",
        "",
        (
            "Mode: actual FastAPI/Application/PostgreSQL patient-medication, r"
            "egimen, source, session and audit repositories with authenticated"
            "-role RLS. Public source labels are cached replay; Gemini is a st"
            "ub. The empty historical result is real SQL, not fabricated event"
            "s. No production connection."
        ),
        "",
    ]
    for i, row in enumerate(rows, 1):
        lines += [
            f"## Turn {i}",
            "",
            "User:",
            "> " + row["user"],
            "",
            "Actual Assistant:",
            "\n".join("> " + line for line in row["actual"].splitlines()),
            "",
            "Actual tool evidence:",
            json.dumps(row["traces"], ensure_ascii=False, indent=2),
            "",
            (
                "Assessment: PASS — actual SQL-owned records/source/session contex"
                "t and final reply were asserted; cross-patient reads/selections e"
                "xpose no A data."
            ),
            "",
        ]
    Path("outputs/correctness02-postgres-conversations.md").write_text("\n".join(lines), encoding="utf8")
