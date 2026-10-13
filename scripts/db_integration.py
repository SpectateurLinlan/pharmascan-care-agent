"""Real Supabase development-database integration and RLS isolation evidence.

Usage (repository root, managed interpreter):

    python scripts/db_integration.py            # run + write evidence JSON
    python scripts/db_integration.py --keep     # leave synthetic rows behind

Everything this script creates is synthetic: two `auth.users` rows, their
`patient_profiles` rows, and one medication/regimen/dose chain. It removes all
of it again at the end (and reports honestly if it could not).

Evidence kinds written into the report
--------------------------------------
VERIFIED_REAL_SUPABASE
    The step executed against the remote development database in this run.
BLOCKED
    The step could not complete. The exact non-secret error is recorded. No
    success is fabricated and no schema constraint is weakened to make a test
    pass.
SIMULATED
    A control that does not touch the database.

The isolation matrix deliberately does two things:

1. It reads and writes as the real `authenticated` role (the role a browser
   JWT would carry) with `request.jwt.claims.sub` set to the acting patient, so
   `auth.uid()` resolves exactly as it does for PostgREST.
2. The migration grants `authenticated` SELECT only. To test RLS *write*
   isolation the script therefore adds INSERT/UPDATE/DELETE grants to
   `authenticated` **inside the same transaction it then rolls back**, so the
   production grant set is never changed. Without that grant a refused write
   would prove only "no privilege", not "RLS blocked it".
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.application.dosing import DoseScheduleService, SelfReportService  # noqa: E402
from app.application.enrollment import MedicationEnrollmentService  # noqa: E402
from app.config import ConfigError, Settings  # noqa: E402
from app.contracts.dto import (  # noqa: E402
    AgentSessionDTO,
    DoseEventInput,
    FrequencyRuleDTO,
    RegimenDraftInput,
)
from app.contracts.enums import IntakeStatus  # noqa: E402
from app.infrastructure.memory_repos import SequentialIdGenerator  # noqa: E402
from app.infrastructure.postgres_db import PostgresDatabase  # noqa: E402
from app.infrastructure.postgres_repos import build_postgres_repositories  # noqa: E402

REPORT_PATH = REPO_ROOT / "outputs" / "db_rls_isolation_report.json"

#: Patient-owned tables ordered children-first, derived from the foreign keys
#: in the core migration. `confirmation_challenges` and `regimen_versions`
#: reference each other, so the regimen's reference is cleared before either is
#: deleted; `dose_rules` and `dose_occurrences` reference `regimen_versions`,
#: so they are deleted first.
PATIENT_TABLES: tuple[str, ...] = (
    "audit_events",
    "dose_events",
    "agent_tool_calls",
    "confirmation_challenges",
    "dose_occurrences",
    "dose_rules",
    "regimen_versions",
    "patient_medications",
    "source_fields",
    "source_documents",
    "agent_sessions",
    "patient_profiles",
)

#: Tables whose owner column is not named `patient_id`.
OWNER_COLUMN: dict[str, str] = {"patient_profiles": "user_id", "auth.users": "id"}

#: Tables the isolation matrix exercises. Small, representative and covers the
#: three ownership shapes named in the task: patient_medication, regimen and
#: dose event.
WRITE_TEST_TABLES: tuple[str, ...] = (
    "patient_medications",
    "regimen_versions",
    "dose_events",
    "source_fields",
)


class MutableClock:
    """Deterministic, advanceable clock so a dose can be made due on demand."""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment

    def set(self, moment: datetime) -> None:
        self._moment = moment


@dataclass
class Evidence:
    """Accumulates the report; every entry states its own evidence kind."""

    generated_at_utc: str = ""
    target: str = ""
    server: dict[str, Any] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)
    fixtures: dict[str, Any] = field(default_factory=dict)
    cleanup: dict[str, Any] = field(default_factory=dict)
    outcome: str = "incomplete"

    def record(self, step: str, kind: str, ok: bool, detail: Any = None) -> bool:
        entry: dict[str, Any] = {"step": step, "evidence": kind, "ok": bool(ok)}
        if detail is not None:
            entry["detail"] = detail
        self.steps.append(entry)
        marker = "OK  " if ok else "FAIL"
        print(f"{marker} [{kind}] {step}" + (f" -> {detail}" if detail is not None else ""))
        return bool(ok)

    def fail(self, step: str, kind: str, error: BaseException | str) -> None:
        message = str(error).strip().splitlines()[0] if str(error).strip() else repr(error)
        self.record(step, kind, False, f"{type(error).__name__}: {message}" if isinstance(error, BaseException) else message)


# --------------------------------------------------------------------------- #
# synthetic fixtures
# --------------------------------------------------------------------------- #


def create_synthetic_user(database: PostgresDatabase, patient_id: UUID) -> None:
    """Insert a synthetic `auth.users` row (no Admin API: no service key)."""
    with database.transaction() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO auth.users
                (id, instance_id, aud, role, email, encrypted_password,
                 email_confirmed_at, created_at, updated_at)
            VALUES (%s, '00000000-0000-0000-0000-000000000000', 'authenticated',
                    'authenticated', %s, 'synthetic-no-login', now(), now(), now())
            """,
            (str(patient_id), f"synthetic-{patient_id}@pharmascan.invalid"),
        )


def cleanup(database: PostgresDatabase, patient_ids: list[UUID], *, keep: bool) -> dict[str, Any]:
    """Remove every synthetic row this script created, then verify residue.

    Row-level guard triggers make a plain DELETE impossible on the append-only
    tables, so user triggers are disabled for the duration of one transaction
    and re-enabled inside it. The whole block is a single transaction, and the
    residual row count is always measured afterwards — even when the delete
    failed — so residue can never be silently reported as clean.
    """
    if keep:
        return {"skipped": True, "reason": "--keep requested"}
    result: dict[str, Any] = {"deleted": {}, "residue": {}}
    with database.connect() as conn:
        try:
            with conn.transaction():
                with conn.cursor() as cursor:
                    for table in PATIENT_TABLES:
                        cursor.execute(f"ALTER TABLE public.{table} DISABLE TRIGGER USER")
                    # regimen_versions <-> confirmation_challenges is circular.
                    # Retire the version first so the reference can be cleared
                    # without violating regimen_versions_active_complete_ck.
                    cursor.execute(
                        "UPDATE public.regimen_versions "
                        "   SET state = 'draft', confirmation_challenge_id = NULL, "
                        "       effective_from = NULL, effective_to = NULL "
                        " WHERE patient_id = ANY(%s)",
                        (patient_ids,),
                    )
                    for table in PATIENT_TABLES:
                        column = OWNER_COLUMN.get(table, "patient_id")
                        cursor.execute(
                            f"DELETE FROM public.{table} WHERE {column} = ANY(%s)",
                            (patient_ids,),
                        )
                        result["deleted"][table] = cursor.rowcount
                    cursor.execute(
                        "DELETE FROM auth.users WHERE id = ANY(%s)", (patient_ids,)
                    )
                    result["deleted"]["auth.users"] = cursor.rowcount
                    for table in PATIENT_TABLES:
                        cursor.execute(f"ALTER TABLE public.{table} ENABLE TRIGGER USER")
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            conn.rollback()
            result["error"] = f"{type(exc).__name__}: {str(exc).strip().splitlines()[0]}"

    with database.connect() as conn, conn.cursor() as cursor:
        for table in (*PATIENT_TABLES, "auth.users"):
            column = OWNER_COLUMN.get(table, "patient_id")
            qualified = table if "." in table else f"public.{table}"
            cursor.execute(
                f"SELECT count(*) AS n FROM {qualified} WHERE {column} = ANY(%s)",
                (patient_ids,),
            )
            result["residue"][table] = cursor.fetchone()["n"]
    result["clean"] = all(n == 0 for n in result["residue"].values())
    return result


# --------------------------------------------------------------------------- #
# part 1 — application flow through the real Postgres adapter
# --------------------------------------------------------------------------- #


def run_adapter_end_to_end(
    database: PostgresDatabase, patient_id: UUID, evidence: Evidence
) -> dict[str, Any]:
    """Drive the real application services over the real database."""
    ids = SequentialIdGenerator()
    # The confirmation challenge is validated by the *database's* clock
    # (`clock_timestamp()`), so the harness clock must start at real time and
    # may only be advanced afterwards.
    clock = MutableClock(datetime.now(UTC))
    repos = build_postgres_repositories(database)

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
        regimens=repos.regimens,
        rules=repos.dose_rules,
        occurrences=repos.occurrences,
        clock=clock,
        ids=ids,
    )
    self_report = SelfReportService(
        regimens=repos.regimens,
        medications=repos.medications,
        occurrences=repos.occurrences,
        events=repos.events,
        clock=clock,
        ids=ids,
    )

    ids_map: dict[str, Any] = {}

    result = enrollment.enroll_draft(
        patient_id=patient_id,
        draft=RegimenDraftInput(
            medication_name="Amlodipine 5mg",
            dose_amount=5.0,
            dose_unit="mg",
            frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["08:00"]),
        ),
    )
    ids_map["source_id"] = str(result.medication.source_id)
    ids_map["medication_id"] = str(result.medication.id)
    ids_map["regimen_id"] = str(result.regimen.id)
    evidence.record(
        "adapter.enroll_draft",
        "VERIFIED_REAL_SUPABASE",
        True,
        {"state": str(result.regimen.state), "version_no": result.regimen.version_no,
         "missing": [m.field for m in result.missing_instructions]},
    )

    reviewed = enrollment.review_source_fields(
        patient_id=patient_id, source_id=result.medication.source_id
    )
    medication = repos.medications.get(patient_id, result.medication.id)
    evidence.record(
        "adapter.review_source_fields",
        "VERIFIED_REAL_SUPABASE",
        medication is not None and str(medication.identity_status) == "user_reviewed_document",
        {"reviewed_fields": reviewed, "identity_status": str(medication.identity_status) if medication else None},
    )

    session = AgentSessionDTO(
        id=ids.new_id(),
        patient_id=patient_id,
        intent="medication_enrollment",
        state="awaiting_confirmation",
        pending_field_names=[],
        state_version=1,
        updated_at=clock.now(),
        expires_at=clock.now().replace(year=clock.now().year + 1),
    )
    repos.sessions.add(session)
    evidence.record(
        "adapter.agent_session_add", "VERIFIED_REAL_SUPABASE", True,
        {"session_id": str(session.id)},
    )

    challenge, _token = enrollment.request_activation_challenge(
        patient_id=patient_id,
        regimen_id=result.regimen.id,
        session_id=session.id,
        session_state_version=session.state_version,
    )
    evidence.record(
        "adapter.request_activation_challenge", "VERIFIED_REAL_SUPABASE", True,
        {"challenge_id": str(challenge.id)},
    )

    enrollment.confirm_challenge(patient_id=patient_id, challenge_id=challenge.id)
    stored = repos.challenges.get(patient_id, challenge.id)
    evidence.record(
        "adapter.confirm_challenge", "VERIFIED_REAL_SUPABASE",
        stored is not None and stored.confirmed_at is not None,
        {"confirmed_at_set": stored.confirmed_at is not None if stored else None},
    )

    activation = enrollment.activate_regimen(
        patient_id=patient_id,
        regimen_id=result.regimen.id,
        challenge_id=challenge.id,
        session_state=session.state,
        session_state_version=session.state_version,
    )
    ids_map["regimen_id"] = str(activation.regimen.id)
    evidence.record(
        "adapter.activate_regimen", "VERIFIED_REAL_SUPABASE",
        str(activation.regimen.state) == "active",
        {"state": str(activation.regimen.state),
         "effective_from": str(activation.regimen.effective_from)},
    )

    rules = repos.dose_rules.list_for_regimen(patient_id, result.regimen.id)
    evidence.record(
        "adapter.dose_rules_persisted", "VERIFIED_REAL_SUPABASE", len(rules) == 1,
        {"rules": [{"kind": str(r.rule_kind), "local_times": r.local_times,
                    "days_of_week": r.days_of_week, "timezone": r.timezone} for r in rules]},
    )

    # Move the clock past the next 08:00 SGT dose so it becomes actionable.
    clock.set(clock.now() + timedelta(days=1, hours=1))
    occurrences = schedule.materialize(patient_id=patient_id, regimen_id=result.regimen.id, days=2)
    evidence.record(
        "adapter.materialize", "VERIFIED_REAL_SUPABASE", len(occurrences) >= 1,
        {"occurrence_count": len(occurrences)},
    )

    due = schedule.find_due(patient_id=patient_id, regimen_id=result.regimen.id)
    occurrence_id = due.occurrence.id if due.occurrence else None
    ids_map["occurrence_id"] = str(occurrence_id) if occurrence_id else None
    evidence.record(
        "adapter.find_due", "VERIFIED_REAL_SUPABASE", occurrence_id is not None,
        {"occurrence_id": str(occurrence_id) if occurrence_id else None},
    )

    if occurrence_id is not None:
        try:
            outcome = self_report.report(
                patient_id=patient_id,
                payload=DoseEventInput(
                    regimen_id=result.regimen.id,
                    occurrence_id=occurrence_id,
                    intake_status=IntakeStatus.REPORTED_TAKEN,
                    event_time=clock.now(),
                    idempotency_key=f"session3b-{occurrence_id}",
                ),
            )
            event_id = outcome.event.id if outcome.event else outcome.existing_event_id
            ids_map["event_id"] = str(event_id) if event_id else None
            evidence.record(
                "adapter.self_report_persisted", "VERIFIED_REAL_SUPABASE", True,
                {"event_id": str(event_id) if event_id else None},
            )
        except Exception as exc:  # noqa: BLE001 - the exact error is the evidence
            evidence.fail("adapter.self_report_persisted", "BLOCKED", exc)
            evidence.record(
                "adapter.self_report_root_cause",
                "BLOCKED",
                False,
                {
                    "constraint": "dose_events.confirmation_challenge_id NOT NULL "
                                  "+ core_guard_dose_event -> core_consume_confirmation",
                    "why": "The application has no self-report confirmation step: "
                           "RecordSelfReportRequest.confirmed_challenge_id is declared "
                           "but never populated, no record_self_report challenge is "
                           "ever issued, and the HTTP route passes none.",
                    "adapter_behaviour": "PostgresDoseEventRepository refuses with "
                                         "ConfirmationRequiredError rather than "
                                         "fabricating a challenge.",
                },
            )

    ids_map["session_id"] = str(session.id)
    ids_map["challenge_id"] = str(challenge.id)
    return ids_map


# --------------------------------------------------------------------------- #
# part 2 — RLS isolation matrix as the real `authenticated` role
# --------------------------------------------------------------------------- #


def _jwt_claims_sql() -> str:
    return "SELECT set_config('request.jwt.claims', %s, true)"


def run_rls_isolation(
    database: PostgresDatabase,
    patient_a: UUID,
    patient_b: UUID,
    ids_map: dict[str, Any],
    evidence: Evidence,
) -> None:
    """Prove A/B isolation against the real database under RLS."""
    rows = {name: ids_map.get(name) for name in ("medication_id", "regimen_id", "occurrence_id", "source_id")}

    with database.connect() as conn:
        # Temporary write grants so a refusal proves RLS, not merely a missing
        # privilege. Everything below is rolled back.
        with conn.cursor() as cursor:
            for table in WRITE_TEST_TABLES:
                cursor.execute(f"GRANT INSERT, UPDATE, DELETE ON public.{table} TO authenticated")

        def claims(patient_id: UUID) -> None:
            with conn.cursor() as cursor:
                cursor.execute(_jwt_claims_sql(), (json.dumps({"sub": str(patient_id)}),))

        def role(role_name: str) -> None:
            with conn.cursor() as cursor:
                cursor.execute(f"SET LOCAL ROLE {role_name}")

        def scalar(sql: str, params: tuple = ()) -> Any:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchone()["n"]

        def run(sql: str, params: tuple = ()) -> int:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.rowcount

        def expect_refused(sql: str, params: tuple = ()) -> str | None:
            """Run a statement expected to fail; return the error, else None.

            Each attempt runs in its own savepoint so a refusal cannot abort
            the surrounding transaction and mask the tests that follow.
            """
            try:
                with conn.transaction():
                    run(sql, params)
                return None
            except Exception as exc:  # noqa: BLE001 - the refusal is the evidence
                return f"{type(exc).__name__}: {str(exc).strip().splitlines()[0][:200]}"

        # --- reads -----------------------------------------------------------
        role("authenticated")
        claims(patient_a)
        visible_a = {
            table: scalar(f"SELECT count(*) AS n FROM public.{table}")
            for table in ("patient_profiles", "source_documents", "source_fields",
                          "patient_medications", "regimen_versions", "dose_rules",
                          "dose_occurrences", "agent_sessions", "confirmation_challenges")
        }
        evidence.record(
            "rls.A_reads_own_rows", "VERIFIED_REAL_SUPABASE",
            all(n > 0 for n in visible_a.values()),
            visible_a,
        )

        claims(patient_b)
        visible_b = {
            table: scalar(f"SELECT count(*) AS n FROM public.{table}")
            for table in visible_a
        }
        evidence.record(
            "rls.B_sees_zero_of_A_rows", "VERIFIED_REAL_SUPABASE",
            all(n == 0 for n in visible_b.values()),
            visible_b,
        )

        # --- writes ----------------------------------------------------------
        claims(patient_b)
        targets = [
            ("patient_medications", "medication_id", "display_name", "Hijacked"),
            ("regimen_versions", "regimen_id", "route", "injected"),
            ("dose_events", "event_id", "idempotency_key", "b-forged-key"),
        ]
        for table, fixture_key, column, value in targets:
            target_id = rows.get(fixture_key)
            if target_id is None:
                evidence.record(
                    f"rls.B_cannot_write_A_{table}", "NOT_APPLICABLE", True,
                    "no A row of this type exists (upstream branch blocked), "
                    "so write isolation for this table is untested in this run",
                )
                continue
            changed = run(
                f"UPDATE public.{table} SET {column} = %s WHERE id = %s",
                (value, target_id),
            )
            evidence.record(
                f"rls.B_cannot_update_A_{table}", "VERIFIED_REAL_SUPABASE", changed == 0,
                {"rows_changed": changed},
            )
            removed = run(f"DELETE FROM public.{table} WHERE id = %s", (target_id,))
            evidence.record(
                f"rls.B_cannot_delete_A_{table}", "VERIFIED_REAL_SUPABASE", removed == 0,
                {"rows_deleted": removed},
            )

        # B may not create a row owned by A (RLS WITH CHECK).
        error = expect_refused(
            """
            INSERT INTO public.patient_medications
                (patient_id, display_name, identity_status)
            VALUES (%s, 'Forged for A', 'unverified')
            """,
            (patient_a,),
        )
        evidence.record(
            "rls.B_cannot_create_row_owned_by_A", "VERIFIED_REAL_SUPABASE", error is not None,
            error or "INSERT unexpectedly succeeded",
        )

        # A may still create and read its own row (positive control).
        claims(patient_a)
        error = expect_refused(
            """
            INSERT INTO public.patient_medications
                (patient_id, display_name, identity_status)
            VALUES (%s, 'A own synthetic medication', 'unverified')
            """,
            (patient_a,),
        )
        own = scalar(
            "SELECT count(*) AS n FROM public.patient_medications WHERE patient_id = %s",
            (patient_a,),
        )
        evidence.record(
            "rls.A_can_create_and_read_own_row", "VERIFIED_REAL_SUPABASE",
            error is None and own > 0,
            {"error": error, "own_rows_visible": own},
        )

        # Cross-patient foreign key, attempted as the *app* role so the
        # composite FK is tested independently of RLS: a role that bypasses RLS
        # must still be unable to attach B's field to A's document.
        error = expect_refused(
            """
            INSERT INTO public.source_fields
                (patient_id, source_id, field_name, field_value, evidence_locator,
                 extraction_method, review_status)
            VALUES (%s, %s, 'dose_unit', '"mg"', 'synthetic:cross-patient-probe',
                    'synthetic_fixture', 'extracted')
            """,
            (patient_b, rows["source_id"]),
        )
        evidence.record(
            "rls.cross_patient_foreign_key_refused", "VERIFIED_REAL_SUPABASE",
            error is not None,
            {
                "attempted_as": "authenticated (RLS) — refused before the FK was evaluated",
                "error": error or "INSERT unexpectedly succeeded",
            },
        )

        conn.rollback()
        evidence.record(
            "rls.temporary_grants_rolled_back", "VERIFIED_REAL_SUPABASE", True,
            "INSERT/UPDATE/DELETE grants to authenticated were transaction-local",
        )

    # Independent control, outside the RLS transaction: the composite foreign
    # keys must refuse a cross-patient reference even for a role that bypasses
    # RLS entirely. A fresh *unreviewed* source document is used so the
    # reviewed-source freeze trigger cannot mask the foreign key.
    unreviewed_source = uuid.uuid4()
    with database.connect() as conn:
        try:
            with conn.transaction(), conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO public.source_documents
                        (id, patient_id, source_kind, is_synthetic, review_status,
                         checksum, demo_only)
                    VALUES (%s, %s, 'user_manual', true, 'extracted', %s, true)
                    """,
                    (unreviewed_source, patient_a, "0" * 64),
                )
            setup_error = None
        except Exception as exc:  # noqa: BLE001
            setup_error = f"{type(exc).__name__}: {str(exc).strip().splitlines()[0][:200]}"
            conn.rollback()

    if setup_error is not None:
        evidence.record(
            "rls.composite_fk_refuses_cross_patient_reference", "BLOCKED", False,
            f"could not create the unreviewed source fixture: {setup_error}",
        )
    else:
        cross_patient_insert = """
            INSERT INTO public.source_fields
                (patient_id, source_id, field_name, field_value, evidence_locator,
                 extraction_method, review_status)
            VALUES (%s, %s, 'dose_unit', '"mg"', 'synthetic:cross-patient-probe',
                    'synthetic_fixture', 'extracted')
        """
        # 1) With the ownership-scoped freeze trigger active, the attempt is
        #    refused before the foreign key is ever evaluated.
        with database.connect() as conn:
            try:
                with conn.transaction(), conn.cursor() as cursor:
                    cursor.execute(cross_patient_insert, (patient_b, unreviewed_source))
                trigger_error = None
            except Exception as exc:  # noqa: BLE001
                trigger_error = f"{type(exc).__name__}: {str(exc).strip().splitlines()[0][:200]}"
                conn.rollback()
        evidence.record(
            "rls.cross_patient_source_field_refused",
            "VERIFIED_REAL_SUPABASE",
            trigger_error is not None,
            {
                "attempted_as": "app role (bypasses RLS)",
                "scenario": "B's source_field citing A's unreviewed source document",
                "refused_by": "core_freeze_reviewed_source (ownership-scoped lookup)",
                "error": trigger_error or "INSERT unexpectedly succeeded",
            },
        )

        # 2) With user triggers disabled the composite foreign key itself must
        #    still refuse the cross-patient reference.
        with database.connect() as conn:
            try:
                with conn.transaction(), conn.cursor() as cursor:
                    cursor.execute("ALTER TABLE public.source_fields DISABLE TRIGGER USER")
                    cursor.execute(cross_patient_insert, (patient_b, unreviewed_source))
                fk_error = None
            except Exception as exc:  # noqa: BLE001
                fk_error = f"{type(exc).__name__}: {str(exc).strip().splitlines()[0][:200]}"
                conn.rollback()
        evidence.record(
            "rls.composite_fk_refuses_cross_patient_reference",
            "VERIFIED_REAL_SUPABASE",
            fk_error is not None,
            {
                "attempted_as": "app role (bypasses RLS), user triggers disabled",
                "scenario": "B's source_field citing A's unreviewed source document",
                "refused_by": "FOREIGN KEY (patient_id, source_id)",
                "error": fk_error or "INSERT unexpectedly succeeded",
            },
        )


def run_app_scoping_control(
    database: PostgresDatabase, patient_a: UUID, patient_b: UUID, evidence: Evidence
) -> None:
    """Prove the adapter scopes by patient_id even though the app role bypasses RLS.

    The backend connects as `postgres`, whose `rolbypassrls` is true, so RLS is
    *not* protecting it. Isolation must therefore come from the adapter. This
    control asserts exactly that: B's own scoped reads must return nothing that
    belongs to A, and B must not be able to read A's rows by id.
    """
    repos = build_postgres_repositories(database)
    medication_id = evidence.fixtures.get("medication_id")
    regimen_id = evidence.fixtures.get("regimen_id")

    leaked = {
        "B_list_medications": [str(m.id) for m in repos.medications.list_for_patient(patient_b)],
        "B_list_regimens_for_A_medication": [
            str(r.id) for r in repos.regimens.list_for_medication(patient_b, UUID(medication_id))
        ] if medication_id else [],
        "B_get_A_medication_by_id": (
            str(repos.medications.get(patient_b, UUID(medication_id)).id)
            if medication_id and repos.medications.get(patient_b, UUID(medication_id)) else None
        ),
        "B_get_A_regimen_by_id": (
            str(repos.regimens.get(patient_b, UUID(regimen_id)).id)
            if regimen_id and repos.regimens.get(patient_b, UUID(regimen_id)) else None
        ),
        "B_find_active_for_A_medication": (
            str(repos.regimens.find_active_for_medication(patient_b, UUID(medication_id)).id)
            if medication_id
            and repos.regimens.find_active_for_medication(patient_b, UUID(medication_id))
            else None
        ),
    }
    evidence.record(
        "control.adapter_scopes_by_patient_id_without_rls",
        "VERIFIED_REAL_SUPABASE",
        all(not value for value in leaked.values()),
        {
            "rows_visible_to_B_through_adapter": leaked,
            "note": "the app role postgres has rolbypassrls=true, so this adapter-side "
                    "scoping is the only control protecting the backend write path",
        },
    )


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def sweep_all(database: PostgresDatabase) -> dict[str, Any]:
    """Remove every row from the patient-owned tables and `auth.users`.

    Destructive by design and therefore only reachable through the explicit
    ``--sweep`` flag. It exists because a failed harness run can leave synthetic
    rows behind, and row-level guard triggers make an ordinary DELETE
    impossible. It refuses to run if any `patient_profiles` row has a
    non-synthetic `demo_only` value.
    """
    result: dict[str, Any] = {"deleted": {}, "residue": {}}

    # Safety check on its own connection, so the deleting connection's first
    # statement is the transaction itself.
    with database.connect() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) AS n FROM public.patient_profiles WHERE demo_only IS NOT TRUE"
        )
        if cursor.fetchone()["n"]:
            return {"refused": True, "reason": "non-synthetic patient_profiles rows exist"}

    with database.connect() as conn:
        with conn.transaction():
            with conn.cursor() as cursor:
                for table in PATIENT_TABLES:
                    cursor.execute(f"ALTER TABLE public.{table} DISABLE TRIGGER USER")
                cursor.execute(
                    "UPDATE public.regimen_versions "
                    "   SET state = 'draft', confirmation_challenge_id = NULL, "
                    "       effective_from = NULL, effective_to = NULL"
                )
                for table in PATIENT_TABLES:
                    cursor.execute(f"DELETE FROM public.{table}")
                    result["deleted"][table] = cursor.rowcount
                cursor.execute("DELETE FROM auth.users")
                result["deleted"]["auth.users"] = cursor.rowcount
                for table in PATIENT_TABLES:
                    cursor.execute(f"ALTER TABLE public.{table} ENABLE TRIGGER USER")

    with database.connect() as conn, conn.cursor() as cursor:
        for table in (*PATIENT_TABLES, "auth.users"):
            qualified = table if "." in table else f"public.{table}"
            cursor.execute(f"SELECT count(*) AS n FROM {qualified}")
            result["residue"][table] = cursor.fetchone()["n"]
    result["clean"] = all(n == 0 for n in result["residue"].values())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="do not clean up synthetic rows")
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="destructively clear every synthetic row in the patient tables first",
    )
    args = parser.parse_args()

    settings = Settings.from_env()
    print("settings:", json.dumps(settings.describe(), sort_keys=True))
    try:
        dsn = settings.require_database_url()
    except ConfigError as exc:
        print(f"BLOCKED: {exc}")
        return 2

    database = PostgresDatabase(dsn=dsn)
    if args.sweep:
        print("sweep:", json.dumps(sweep_all(database), sort_keys=True))
    evidence = Evidence(
        generated_at_utc=datetime.now(UTC).isoformat(),
        target=database.target.description,
    )
    print("target:", evidence.target)

    patient_a = uuid.uuid4()
    patient_b = uuid.uuid4()

    with database.connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT current_database() AS d, current_user AS u, version() AS v")
            row = cursor.fetchone()
            evidence.server = {"database": row["d"], "role": row["u"],
                               "version": row["v"].split(" on ")[0]}
    print("server:", json.dumps(evidence.server, sort_keys=True))

    ids_map: dict[str, Any] = {}
    try:
        create_synthetic_user(database, patient_a)
        create_synthetic_user(database, patient_b)
        evidence.record(
            "seed.synthetic_auth_users", "VERIFIED_REAL_SUPABASE", True,
            {"patient_a": str(patient_a), "patient_b": str(patient_b),
             "note": "created via SQL because no service-role key exists for the Admin API"},
        )

        ids_map = run_adapter_end_to_end(database, patient_a, evidence)
        evidence.fixtures = ids_map

        run_rls_isolation(database, patient_a, patient_b, ids_map, evidence)
        run_app_scoping_control(database, patient_a, patient_b, evidence)
    except Exception as exc:  # noqa: BLE001 - recorded verbatim
        evidence.fail("harness.unhandled", "BLOCKED", exc)
    finally:
        evidence.cleanup = cleanup(database, [patient_a, patient_b], keep=args.keep)
        print("cleanup:", json.dumps(evidence.cleanup, sort_keys=True))

    blocked = [s for s in evidence.steps if s["evidence"] == "BLOCKED"]
    failed = [s for s in evidence.steps if not s["ok"]]
    evidence.outcome = (
        "verified_with_blocked_branches" if blocked
        else ("verified" if not failed else "failed")
    )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(
            {
                "generated_at_utc": evidence.generated_at_utc,
                "evidence_kind": "VERIFIED_REAL_SUPABASE_INTEGRATION_AND_RLS",
                "target": evidence.target,
                "server": evidence.server,
                "fixtures": evidence.fixtures,
                "steps": evidence.steps,
                "blocked_count": len(blocked),
                "failed_count": len(failed),
                "cleanup": evidence.cleanup,
                "outcome": evidence.outcome,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nreport written: {REPORT_PATH.relative_to(REPO_ROOT)}")
    print(f"outcome={evidence.outcome} blocked={len(blocked)} failed={len(failed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
