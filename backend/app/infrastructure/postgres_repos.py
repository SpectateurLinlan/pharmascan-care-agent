"""Real PostgreSQL/Supabase repository adapters.

These classes implement the public Repository Ports
(``backend/app/contracts/ports.py``) against the committed schema in
``supabase/migrations/``. Nothing above this module changes: the application
and domain layers still depend only on the Port protocols, and the concrete
implementation is selected by the composition root.

Design rules honoured here
--------------------------
* **Explicit injection.** Every adapter receives a ``SessionFactory``; there is
  no module-level engine, session or connection, so no code path can reach the
  database without being handed one (AGENTS.md rule 2).
* **Short-lived transactions.** Each Port call opens its own connection and
  transaction, commits on success and rolls back on error. No connection is
  shared between calls and none outlives the call.
* **Two connection modes, one adapter.** The adapter code is identical for both
  trust boundaries; only the injected ``SessionFactory`` differs:

  ``privileged_session(database)``
      Runs as the ``DATABASE_URL`` role (``rolbypassrls = true`` on the Supabase
      development project). Migrations, schema verification, maintenance, admin
      setup and the evidence harness only.
  ``patient_rls_session(database)``
      Runs as ``pharmascan_patient`` (``NOBYPASSRLS``) with ``auth.uid()`` set
      from the verified patient identity, so the database's own RLS policies
      scope every statement. This is an explicit administrative RLS diagnostic path; HTTP uses the user JWT Data API.

* **Patient scoping twice, deliberately.** Every statement here *also* carries
  an explicit ``patient_id = %s`` predicate. On the privileged path that
  predicate is the only control; on the patient path it is defence in depth
  behind RLS. ``tests/backend/test_patient_scoping_regression.py`` fails if a
  future statement drops it.
* **No invented safety decisions.** Where the schema demands a column the
  application DTO does not carry, the adapter either derives it
  deterministically from data the application already produced, or refuses the
  write with a typed domain error. It never fabricates an authorisation.

Deterministic derivations (documented because they are real)
------------------------------------------------------------
``source_documents.checksum``
    ``NOT NULL`` with a 64-hex CHECK. The P0 slice stores no document bytes
    (synthetic, no photo), so the checksum is derived deterministically from
    the owning patient and the source id. It is a stable identifier for
    synthetic provenance, not a content hash of real evidence.
``source_fields.evidence_locator`` / ``extraction_method``
    ``NOT NULL``. Derived from the field id and the parent source kind
    (``mock_import`` -> ``synthetic_fixture``, ``user_manual`` -> ``manual``).
``agent_sessions.prompt_version``
    ``NOT NULL``. The build ships a deterministic, non-LLM router, so the
    version string names that router rather than a prompt.
``regimen_versions`` provenance columns
    ``medication_name_field_id`` / ``quantity_field_id`` / ``unit_field_id`` /
    ``frequency_field_id`` / ``prn_field_id`` / ``source_reviewed_at`` are bound
    by looking up the patient's own reviewed ``source_fields`` for the cited
    source document. This is exactly the provenance link the SQL guard
    validates; it is read from data the application already created, never
    invented.
``dose_events.confirmation_challenge_id``
    ``NOT NULL`` and validated by ``core_consume_confirmation``. The adapter
    resolves it from a genuinely confirmed, unconsumed ``record_self_report``
    challenge bound to the same regimen, occurrence, intake status and
    idempotency key. If no such challenge exists the write is refused with
    ``ConfirmationRequiredError`` — the adapter never manufactures consent.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from ..contracts.dto import (
    AgentSessionDTO,
    ConfirmationChallengeDTO,
    DoseEventDTO,
    DoseOccurrenceDTO,
    DoseRuleDTO,
    PatientMedicationDTO,
    RegimenVersionDTO,
    SourceDocumentDTO,
    SourceFieldDTO,
    ToolTraceDTO,
)
from ..contracts.enums import RuleKind
from ..domain.errors import ConfirmationRequiredError, NotFoundError, ValidationError
from .postgres_db import PostgresDatabase

#: Opens one short-lived, already-scoped session for a patient. The adapter
#: never decides *which* trust boundary it is running under; the composition
#: root injects either the privileged or the RLS-enforced factory below.
SessionFactory = Callable[[UUID], AbstractContextManager[psycopg.Connection]]

#: Timezone used when bootstrapping a patient_profiles row. Matches
#: application.timezone.DEFAULT_PATIENT_TZ.
DEFAULT_PATIENT_TIMEZONE = "Asia/Singapore"

#: Names the deterministic (non-LLM) router this build ships.
DETERMINISTIC_PROMPT_VERSION = "deterministic_router_v1"

REVIEWED_SOURCE_STATUSES = ("user_reviewed", "professional_verified")


# --------------------------------------------------------------------------- #
# session factories — the only place the trust boundary is chosen
# --------------------------------------------------------------------------- #


def privileged_session(database: PostgresDatabase) -> SessionFactory:
    """Session factory for the privileged role (BYPASSRLS).

    The patient argument is deliberately ignored: this mode's isolation comes
    entirely from the explicit ``patient_id`` predicate in each statement.
    Reserved for migrations, schema verification, maintenance, admin setup and
    the evidence harness — never the normal patient request path.
    """

    def open_session(patient_id: UUID) -> AbstractContextManager[psycopg.Connection]:
        del patient_id
        return database.transaction()

    return open_session


def patient_rls_session(database: PostgresDatabase) -> SessionFactory:
    """Session factory for the RLS-enforced patient role (NOBYPASSRLS)."""

    def open_session(patient_id: UUID) -> AbstractContextManager[psycopg.Connection]:
        return database.patient_transaction(patient_id=patient_id)

    return open_session


# --------------------------------------------------------------------------- #
# deterministic derivations
# --------------------------------------------------------------------------- #


def synthetic_source_checksum(patient_id: UUID, source_id: UUID) -> str:
    """Deterministic 64-hex checksum for a synthetic, byte-less source."""
    material = f"pharmascan-synthetic-source::{patient_id}::{source_id}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def synthetic_evidence_locator(field_id: UUID) -> str:
    """Locator satisfying ``^synthetic:[A-Za-z0-9_.:-]{1,120}$``."""
    return f"synthetic:field:{field_id}"


def challenge_request_hash(
    *,
    patient_id: UUID,
    action: str,
    regimen_id: UUID,
    occurrence_id: UUID | None,
    intake_status: str | None,
    idempotency_key: str,
) -> str:
    """Deterministic 64-hex hash of a challenge's binding (never the token)."""
    material = json.dumps(
        {
            "patient_id": str(patient_id),
            "action": action,
            "regimen_id": str(regimen_id),
            "occurrence_id": str(occurrence_id) if occurrence_id else None,
            "intake_status": intake_status,
            "idempotency_key": idempotency_key,
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# low-level helpers
# --------------------------------------------------------------------------- #


def _rows(conn: psycopg.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def _one(conn: psycopg.Connection, sql: str, params: tuple = ()) -> dict[str, Any] | None:
    rows = _rows(conn, sql, params)
    return rows[0] if rows else None


def _scalar(conn: psycopg.Connection, sql: str, params: tuple = ()) -> Any:
    row = _one(conn, sql, params)
    return next(iter(row.values())) if row else None


def _run(conn: psycopg.Connection, sql: str, params: tuple = ()) -> int:
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.rowcount


def _as_uuid(value: object) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _as_uuid_or_none(value: object) -> UUID | None:
    return None if value is None else _as_uuid(value)


def _enum(value: object) -> Any:
    """Pass a database text value through; the DTO coerces it to its enum."""
    return value


def _json_or_none(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else None
    return dict(value)  # type: ignore[arg-type]


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("naive datetime returned by the database; expected timestamptz")
    return value.astimezone(UTC)


def ensure_patient_profile(
    conn: psycopg.Connection, patient_id: UUID, *, timezone: str = DEFAULT_PATIENT_TIMEZONE
) -> None:
    """Bootstrap the owner row the schema requires.

    ``patient_profiles`` is the parent of every patient-owned table, so a
    synthetic demo patient must have one before anything can be written. The
    insert is a no-op when the row already exists, so the first writer wins and
    a later writer can never rewrite the patient's timezone.
    """
    _run(
        conn,
        """
        INSERT INTO public.patient_profiles (user_id, timezone, demo_only)
        VALUES (%s, %s, true)
        ON CONFLICT (user_id) DO NOTHING
        """,
        (patient_id, timezone),
    )


# --------------------------------------------------------------------------- #
# row -> DTO mappers
# --------------------------------------------------------------------------- #


def _source_document(row: dict[str, Any]) -> SourceDocumentDTO:
    return SourceDocumentDTO(
        dose_basis=row.get("dose_basis"),
        extraction_evidence=row.get("extraction_evidence"),
        id=_as_uuid(row["id"]),
        patient_id=_as_uuid(row["patient_id"]),
        source_kind=_enum(row["source_kind"]),
        review_status=_enum(row["review_status"]),
        reviewed_at=row["reviewed_at"],
        demo_only=row["demo_only"],
    )


def _source_field(row: dict[str, Any]) -> SourceFieldDTO:
    return SourceFieldDTO(
        id=_as_uuid(row["id"]),
        patient_id=_as_uuid(row["patient_id"]),
        source_id=_as_uuid(row["source_id"]),
        field_name=_enum(row["field_name"]),
        field_value=row["field_value"],
        review_status=_enum(row["review_status"]),
        reviewed_at=row["reviewed_at"],
        demo_only=row["demo_only"],
    )


def _patient_medication(row: dict[str, Any]) -> PatientMedicationDTO:
    return PatientMedicationDTO(
        id=_as_uuid(row["id"]),
        patient_id=_as_uuid(row["patient_id"]),
        display_name=row["display_name"],
        product_id=_as_uuid_or_none(row["product_id"]),
        source_id=_as_uuid_or_none(row["source_id"]),
        identity_status=_enum(row["identity_status"]),
        archived_at=row["archived_at"],
        demo_only=row["demo_only"],
    )


def _regimen(row: dict[str, Any]) -> RegimenVersionDTO:
    return RegimenVersionDTO(
        patient_edited=bool(row.get("patient_edited", False)),
        id=_as_uuid(row["id"]),
        patient_id=_as_uuid(row["patient_id"]),
        patient_medication_id=_as_uuid(row["patient_medication_id"]),
        source_id=_as_uuid_or_none(row["source_id"]),
        version_no=row["version_no"],
        state=_enum(row["state"]),
        dose_amount=float(row["dose_amount"]) if row["dose_amount"] is not None else None,
        dose_unit=row["dose_unit"],
        frequency_rule=_json_or_none(row["frequency_rule"]),
        is_prn=row["is_prn"],
        route=row["route"],
        food_instruction=row["food_instruction"],
        effective_from=row["effective_from"],
        effective_to=row["effective_to"],
        course_start_date=row["course_start_date"],
        course_end_date=row["course_end_date"],
        supersedes_id=_as_uuid_or_none(row["supersedes_id"]),
        confirmation_challenge_id=_as_uuid_or_none(row["confirmation_challenge_id"]),
        created_at=row["created_at"],
        demo_only=row["demo_only"],
    )


def _dose_rule(row: dict[str, Any]) -> DoseRuleDTO:
    local_time = row["local_time"]
    days = row["days_of_week"] or []
    return DoseRuleDTO(
        id=_as_uuid(row["id"]),
        patient_id=_as_uuid(row["patient_id"]),
        regimen_id=_as_uuid(row["regimen_id"]),
        rule_kind=_enum(row["rule_kind"]),
        local_times=[local_time.strftime("%H:%M")] if local_time is not None else [],
        days_of_week=[int(d) for d in days],
        timezone=row["timezone"],
        enabled=row["enabled"],
    )


def _occurrence(row: dict[str, Any]) -> DoseOccurrenceDTO:
    return DoseOccurrenceDTO(
        id=_as_uuid(row["id"]),
        patient_id=_as_uuid(row["patient_id"]),
        regimen_id=_as_uuid(row["regimen_id"]),
        rule_id=_as_uuid(row["rule_id"]),
        due_at=_to_utc(row["due_at"]),
        status=_enum(row["status"]),
        generation_key=row["generation_key"],
    )


def _dose_event(row: dict[str, Any]) -> DoseEventDTO:
    return DoseEventDTO(
        id=_as_uuid(row["id"]),
        patient_id=_as_uuid(row["patient_id"]),
        regimen_id=_as_uuid(row["regimen_id"]),
        occurrence_id=_as_uuid_or_none(row["occurrence_id"]),
        event_time=_to_utc(row["event_time"]),
        intake_status=_enum(row["intake_status"]),
        visual_status=_enum(row["visual_status"]),
        ingestion_proven=row["ingestion_proven"],
        idempotency_key=row["idempotency_key"],
        created_at=_to_utc(row["created_at"]),
        reported_late=row.get("reported_late", False),
        actual_administration_at=row.get("actual_administration_at"),
    )


def _session(row: dict[str, Any]) -> AgentSessionDTO:
    return AgentSessionDTO(
        conversation_id=_as_uuid_or_none(row.get("conversation_id")),
        context=row.get("context", {}),
        id=_as_uuid(row["id"]),
        patient_id=_as_uuid(row["patient_id"]),
        intent=row["intent"],
        state=row["state"],
        pending_field_names=list(row["pending_field_names"] or []),
        state_version=row["state_version"],
        updated_at=_to_utc(row["updated_at"]),
        expires_at=_to_utc(row["expires_at"]),
    )


def _challenge(row: dict[str, Any]) -> ConfirmationChallengeDTO:
    return ConfirmationChallengeDTO(
        id=_as_uuid(row["id"]),
        patient_id=_as_uuid(row["patient_id"]),
        session_id=_as_uuid(row["session_id"]),
        session_state_version=row["session_state_version"],
        action=row["action"],
        regimen_id=_as_uuid(row["regimen_id"]),
        occurrence_id=_as_uuid_or_none(row["occurrence_id"]),
        intended_intake_status=_enum(row["intended_intake_status"]),
        idempotency_key=row["idempotency_key"],
        token_hash=row["token_hash"],
        issued_at=_to_utc(row["issued_at"]),
        expires_at=_to_utc(row["expires_at"]),
        confirmed_at=row["confirmed_at"],
        consumed_at=row["consumed_at"],
    )


def _trace(row: dict[str, Any]) -> ToolTraceDTO:
    return ToolTraceDTO(
        id=_as_uuid(row["id"]),
        patient_id=_as_uuid(row["patient_id"]),
        session_id=_as_uuid(row["session_id"]),
        correlation_id=_as_uuid(row["correlation_id"]),
        tool_name=row["tool_name"],
        tool_status=row["tool_status"],
        request_summary=dict(row["request_summary"] or {}),
        response_summary=dict(row["response_summary"] or {}),
        called_at=_to_utc(row["called_at"]),
        duration_ms=row["duration_ms"],
    )


# --------------------------------------------------------------------------- #
# repositories
# --------------------------------------------------------------------------- #


class PostgresSourceDocumentRepository:
    """``SourceDocumentRepository`` over ``public.source_documents``."""

    def __init__(self, session: SessionFactory) -> None:
        self._session = session

    def get(self, patient_id: UUID, source_id: UUID) -> SourceDocumentDTO | None:
        with self._session(patient_id) as conn:
            row = _one(
                conn,
                """
                SELECT id, patient_id, source_kind, review_status, reviewed_at, demo_only, dose_basis,
                       extraction_evidence
                  FROM public.source_documents
                 WHERE patient_id = %s AND id = %s
                """,
                (patient_id, source_id),
            )
        return _source_document(row) if row else None

    def add(self, document: SourceDocumentDTO) -> None:
        with self._session(document.patient_id) as conn:
            ensure_patient_profile(conn, document.patient_id)
            _run(
                conn,
                """
                INSERT INTO public.source_documents
                    (id, patient_id, source_kind, is_synthetic, review_status,
                     reviewed_at, checksum, demo_only, dose_basis, extraction_evidence)
                VALUES (%s, %s, %s, true, %s, %s, %s, true, %s, %s)
                """,
                (
                    document.id,
                    document.patient_id,
                    str(document.source_kind),
                    str(document.review_status),
                    document.reviewed_at,
                    synthetic_source_checksum(document.patient_id, document.id),
                    Jsonb(document.dose_basis.model_dump(mode="json")) if document.dose_basis else None,
                    Jsonb(document.extraction_evidence.model_dump(mode="json"))
                    if document.extraction_evidence
                    else None,
                ),
            )

    def update(self, document: SourceDocumentDTO) -> None:
        with self._session(document.patient_id) as conn:
            changed = _run(
                conn,
                """
                UPDATE public.source_documents
                   SET review_status = %s, reviewed_at = %s
                 WHERE patient_id = %s AND id = %s
                """,
                (
                    str(document.review_status),
                    document.reviewed_at,
                    document.patient_id,
                    document.id,
                ),
            )
        if changed == 0:
            raise NotFoundError(f"Source document {document.id} not found")


class PostgresSourceFieldRepository:
    """``SourceFieldRepository`` over ``public.source_fields``."""

    def __init__(self, session: SessionFactory) -> None:
        self._session = session

    def list_for_source(self, patient_id: UUID, source_id: UUID) -> list[SourceFieldDTO]:
        with self._session(patient_id) as conn:
            rows = _rows(
                conn,
                """
                SELECT id, patient_id, source_id, field_name, field_value,
                       review_status, reviewed_at, demo_only
                  FROM public.source_fields
                 WHERE patient_id = %s AND source_id = %s
                 ORDER BY field_name
                """,
                (patient_id, source_id),
            )
        return [_source_field(row) for row in rows]

    def add(self, field: SourceFieldDTO) -> None:
        with self._session(field.patient_id) as conn:
            ensure_patient_profile(conn, field.patient_id)
            source_kind = _scalar(
                conn,
                "SELECT source_kind FROM public.source_documents WHERE patient_id = %s AND id = %s",
                (field.patient_id, field.source_id),
            )
            # 'mock_import' provenance is generated from a synthetic fixture;
            # anything else is treated as a manual entry.
            extraction = "manual" if source_kind == "user_manual" else "synthetic_fixture"
            _run(
                conn,
                """
                INSERT INTO public.source_fields
                    (id, patient_id, source_id, field_name, field_value,
                     evidence_locator, extraction_method, review_status, reviewed_at, demo_only)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, true)
                """,
                (
                    field.id,
                    field.patient_id,
                    field.source_id,
                    str(field.field_name),
                    Jsonb(field.field_value),
                    synthetic_evidence_locator(field.id),
                    extraction,
                    str(field.review_status),
                    field.reviewed_at,
                ),
            )

    def update(self, field: SourceFieldDTO) -> None:
        with self._session(field.patient_id) as conn:
            changed = _run(
                conn,
                """
                UPDATE public.source_fields
                   SET review_status = %s, reviewed_at = %s
                 WHERE patient_id = %s AND id = %s
                """,
                (
                    str(field.review_status),
                    field.reviewed_at,
                    field.patient_id,
                    field.id,
                ),
            )
        if changed == 0:
            raise NotFoundError(f"Source field {field.id} not found")


class PostgresPatientMedicationRepository:
    """``PatientMedicationRepository`` over ``public.patient_medications``."""

    _COLUMNS = "id, patient_id, product_id, display_name, source_id, identity_status, archived_at, demo_only"

    def __init__(self, session: SessionFactory) -> None:
        self._session = session

    def get(self, patient_id: UUID, medication_id: UUID) -> PatientMedicationDTO | None:
        with self._session(patient_id) as conn:
            row = _one(
                conn,
                f"SELECT {self._COLUMNS} FROM public.patient_medications WHERE patient_id = %s AND id = %s",
                (patient_id, medication_id),
            )
        return _patient_medication(row) if row else None

    def list_for_patient(self, patient_id: UUID) -> list[PatientMedicationDTO]:
        with self._session(patient_id) as conn:
            rows = _rows(
                conn,
                f"SELECT {self._COLUMNS} FROM public.patient_medications WHERE patient_id = %s ORDER BY created_at, id",
                (patient_id,),
            )
        return [_patient_medication(row) for row in rows]

    def add(self, medication: PatientMedicationDTO) -> None:
        with self._session(medication.patient_id) as conn:
            ensure_patient_profile(conn, medication.patient_id)
            _run(
                conn,
                """
                INSERT INTO public.patient_medications
                    (id, patient_id, product_id, display_name, source_id,
                     identity_status, archived_at, demo_only)
                VALUES (%s, %s, %s, %s, %s, %s, %s, true)
                """,
                (
                    medication.id,
                    medication.patient_id,
                    medication.product_id,
                    medication.display_name,
                    medication.source_id,
                    str(medication.identity_status),
                    medication.archived_at,
                ),
            )

    def update(self, medication: PatientMedicationDTO) -> None:
        with self._session(medication.patient_id) as conn:
            changed = _run(
                conn,
                """
                UPDATE public.patient_medications
                   SET display_name = %s, product_id = %s, source_id = %s,
                       identity_status = %s, archived_at = %s
                 WHERE patient_id = %s AND id = %s
                """,
                (
                    medication.display_name,
                    medication.product_id,
                    medication.source_id,
                    str(medication.identity_status),
                    medication.archived_at,
                    medication.patient_id,
                    medication.id,
                ),
            )
        if changed == 0:
            raise NotFoundError(f"Medication {medication.id} not found")


class PostgresRegimenVersionRepository:
    """``RegimenVersionRepository`` over ``public.regimen_versions``.

    The update path mirrors ``core_guard_regimen`` exactly:

    * an ``ended``/``superseded`` row is never written;
    * an ``active`` row may only be retired (``state`` + ``effective_to``);
    * a ``draft``/``pending_clarification`` row may become ``active``, and the
      activation binds the provenance columns the SQL guard validates.
    """

    _COLUMNS = (
        "id, patient_id, patient_medication_id, source_id, version_no, state, "
        "dose_amount, dose_unit, frequency_rule, is_prn, route, food_instruction, "
        "effective_from, effective_to, supersedes_id, confirmation_challenge_id, "
        "course_start_date, course_end_date, created_at, patient_edited, demo_only"
    )

    def __init__(self, session: SessionFactory) -> None:
        self._session = session

    def get(self, patient_id: UUID, regimen_id: UUID) -> RegimenVersionDTO | None:
        with self._session(patient_id) as conn:
            row = _one(
                conn,
                f"SELECT {self._COLUMNS} FROM public.regimen_versions WHERE patient_id = %s AND id = %s",
                (patient_id, regimen_id),
            )
        return _regimen(row) if row else None

    def list_for_medication(self, patient_id: UUID, medication_id: UUID) -> list[RegimenVersionDTO]:
        with self._session(patient_id) as conn:
            rows = _rows(
                conn,
                f"SELECT {self._COLUMNS} FROM public.regimen_versions "
                "WHERE patient_id = %s AND patient_medication_id = %s "
                "ORDER BY version_no",
                (patient_id, medication_id),
            )
        return [_regimen(row) for row in rows]

    def find_active_for_medication(self, patient_id: UUID, medication_id: UUID) -> RegimenVersionDTO | None:
        with self._session(patient_id) as conn:
            row = _one(
                conn,
                f"SELECT {self._COLUMNS} FROM public.regimen_versions "
                "WHERE patient_id = %s AND patient_medication_id = %s AND state = 'active'",
                (patient_id, medication_id),
            )
        return _regimen(row) if row else None

    def next_version_no(self, patient_id: UUID, medication_id: UUID) -> int:
        with self._session(patient_id) as conn:
            current = _scalar(
                conn,
                "SELECT COALESCE(MAX(version_no), 0) AS n FROM public.regimen_versions "
                "WHERE patient_id = %s AND patient_medication_id = %s",
                (patient_id, medication_id),
            )
        return int(current or 0) + 1

    def add(self, regimen: RegimenVersionDTO) -> None:
        with self._session(regimen.patient_id) as conn:
            ensure_patient_profile(conn, regimen.patient_id)
            provenance = self._bind_provenance(conn, regimen) if str(regimen.state) == "active" else {}
            _run(
                conn,
                """
                INSERT INTO public.regimen_versions
                    (id, patient_id, patient_medication_id, source_id, version_no, state,
                     dose_amount, dose_unit, frequency_rule, is_prn, route, food_instruction,
                     medication_name_field_id, quantity_field_id, unit_field_id,
                     frequency_field_id, prn_field_id, source_reviewed_at,
                     effective_from, effective_to, supersedes_id, confirmation_challenge_id,
                     course_start_date, course_end_date, patient_edited, demo_only)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true)
                """,
                (
                    regimen.id,
                    regimen.patient_id,
                    regimen.patient_medication_id,
                    regimen.source_id,
                    regimen.version_no,
                    str(regimen.state),
                    regimen.dose_amount,
                    regimen.dose_unit,
                    Jsonb(regimen.frequency_rule) if regimen.frequency_rule is not None else None,
                    regimen.is_prn,
                    regimen.route,
                    regimen.food_instruction,
                    provenance.get("medication_name_field_id"),
                    provenance.get("quantity_field_id"),
                    provenance.get("unit_field_id"),
                    provenance.get("frequency_field_id"),
                    provenance.get("prn_field_id"),
                    provenance.get("source_reviewed_at"),
                    regimen.effective_from,
                    regimen.effective_to,
                    regimen.supersedes_id,
                    regimen.confirmation_challenge_id,
                    regimen.course_start_date,
                    regimen.course_end_date,
                    regimen.patient_edited,
                ),
            )

    def update(self, regimen: RegimenVersionDTO) -> None:
        with self._session(regimen.patient_id) as conn:
            current = _one(
                conn,
                "SELECT state FROM public.regimen_versions WHERE patient_id = %s AND id = %s FOR UPDATE",
                (regimen.patient_id, regimen.id),
            )
            if current is None:
                raise NotFoundError(f"Regimen {regimen.id} not found")
            previous_state = current["state"]
            if previous_state in ("ended", "superseded"):
                raise ValidationError(f"Regimen {regimen.id} is {previous_state}; historical versions are immutable")

            if previous_state == "active":
                # Retiring only: state + effective_to. Any other change is
                # rejected by core_guard_regimen.
                if str(regimen.state) not in ("ended", "superseded") or regimen.effective_to is None:
                    raise ValidationError("An active regimen may only be retired with an effective_to")
                _run(
                    conn,
                    "UPDATE public.regimen_versions SET state = %s, effective_to = %s "
                    "WHERE patient_id = %s AND id = %s",
                    (str(regimen.state), regimen.effective_to, regimen.patient_id, regimen.id),
                )
                return

            if str(regimen.state) not in ("draft", "pending_clarification", "active"):
                raise ValidationError(f"Illegal regimen transition {previous_state} -> {regimen.state}")

            if str(regimen.state) == "active":
                provenance = self._bind_provenance(conn, regimen)
                _run(
                    conn,
                    """
                    UPDATE public.regimen_versions
                       SET state = 'active',
                           source_id = %s,
                           dose_amount = %s, dose_unit = %s, frequency_rule = %s,
                           is_prn = %s, route = %s, food_instruction = %s,
                           medication_name_field_id = %s, quantity_field_id = %s,
                           unit_field_id = %s, frequency_field_id = %s, prn_field_id = %s,
                           source_reviewed_at = %s,
                           effective_from = %s, effective_to = %s,
                           supersedes_id = %s, confirmation_challenge_id = %s,
                           course_start_date = %s, course_end_date = %s
                     WHERE patient_id = %s AND id = %s
                    """,
                    (
                        regimen.source_id,
                        regimen.dose_amount,
                        regimen.dose_unit,
                        Jsonb(regimen.frequency_rule) if regimen.frequency_rule is not None else None,
                        regimen.is_prn,
                        regimen.route,
                        regimen.food_instruction,
                        provenance["medication_name_field_id"],
                        provenance["quantity_field_id"],
                        provenance["unit_field_id"],
                        provenance["frequency_field_id"],
                        provenance["prn_field_id"],
                        provenance["source_reviewed_at"],
                        regimen.effective_from,
                        regimen.effective_to,
                        regimen.supersedes_id,
                        regimen.confirmation_challenge_id,
                        regimen.course_start_date,
                        regimen.course_end_date,
                        regimen.patient_id,
                        regimen.id,
                    ),
                )
                return

            _run(
                conn,
                """
                UPDATE public.regimen_versions
                   SET state = %s,
                       dose_amount = %s, dose_unit = %s, frequency_rule = %s,
                       is_prn = %s, route = %s, food_instruction = %s
                 WHERE patient_id = %s AND id = %s
                """,
                (
                    str(regimen.state),
                    regimen.dose_amount,
                    regimen.dose_unit,
                    Jsonb(regimen.frequency_rule) if regimen.frequency_rule is not None else None,
                    regimen.is_prn,
                    regimen.route,
                    regimen.food_instruction,
                    regimen.patient_id,
                    regimen.id,
                ),
            )

    # -- provenance binding --------------------------------------------------

    @staticmethod
    def _bind_provenance(conn: psycopg.Connection, regimen: RegimenVersionDTO) -> dict[str, Any]:
        """Resolve the reviewed source-field ids an active regimen must cite.

        Read-only: the ids come from the patient's own ``source_fields`` rows
        for the cited source document. Nothing is created here, and a missing
        slot is reported rather than invented.
        """
        if regimen.source_id is None:
            raise ValidationError("An active regimen requires a reviewed source document")

        source = _one(
            conn,
            "SELECT review_status, reviewed_at FROM public.source_documents "
            "WHERE patient_id = %s AND id = %s FOR SHARE",
            (regimen.patient_id, regimen.source_id),
        )
        if source is None:
            raise ValidationError(f"Source document {regimen.source_id} not found")
        if source["review_status"] not in REVIEWED_SOURCE_STATUSES:
            raise ValidationError(
                f"Source document review status is {source['review_status']}; "
                "a reviewed source is required before activation"
            )

        rows = _rows(
            conn,
            "SELECT id, field_name FROM public.source_fields "
            "WHERE patient_id = %s AND source_id = %s AND review_status = ANY(%s)",
            (regimen.patient_id, regimen.source_id, list(REVIEWED_SOURCE_STATUSES)),
        )
        by_name = {row["field_name"]: row["id"] for row in rows}

        required = {
            "medication_name": by_name.get("medication_name"),
            "dose_amount": by_name.get("dose_amount"),
            "dose_unit": by_name.get("dose_unit"),
        }
        schedule_slot = "is_prn" if regimen.is_prn else "frequency_rule"
        required[schedule_slot] = by_name.get(schedule_slot)

        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValidationError(
                "Cannot activate: reviewed source evidence is missing for " + ", ".join(sorted(missing))
            )

        return {
            "medication_name_field_id": required["medication_name"],
            "quantity_field_id": required["dose_amount"],
            "unit_field_id": required["dose_unit"],
            "frequency_field_id": required["frequency_rule"] if not regimen.is_prn else None,
            "prn_field_id": required["is_prn"] if regimen.is_prn else None,
            "source_reviewed_at": source["reviewed_at"],
        }


class PostgresDoseRuleRepository:
    """``DoseRuleRepository`` over ``public.dose_rules``.

    One row carries exactly one local time (the schema models a multi-time
    regimen as several rows). A DTO carrying several times in one rule is
    therefore rejected rather than silently collapsed.
    """

    def __init__(self, session: SessionFactory) -> None:
        self._session = session

    def list_for_regimen(self, patient_id: UUID, regimen_id: UUID) -> list[DoseRuleDTO]:
        with self._session(patient_id) as conn:
            rows = _rows(
                conn,
                """
                SELECT id, patient_id, regimen_id, rule_kind, local_time, days_of_week,
                       timezone, enabled
                  FROM public.dose_rules
                 WHERE patient_id = %s AND regimen_id = %s
                 ORDER BY local_time NULLS FIRST, id
                """,
                (patient_id, regimen_id),
            )
        return [_dose_rule(row) for row in rows]

    def add(self, rule: DoseRuleDTO) -> None:
        kind = str(rule.rule_kind)
        if kind == RuleKind.SCHEDULED and len(rule.local_times) != 1:
            raise ValidationError(
                "a scheduled dose rule must carry exactly one local time; express several times as several rules"
            )
        local_time = rule.local_times[0] if kind == RuleKind.SCHEDULED else None
        days = [int(d) for d in rule.days_of_week] if kind == RuleKind.SCHEDULED else None

        with self._session(rule.patient_id) as conn:
            # The patient profile timezone must match the rule timezone
            # (core_guard_rule), so it is created with the rule's own value.
            ensure_patient_profile(conn, rule.patient_id, timezone=rule.timezone)
            _run(
                conn,
                """
                INSERT INTO public.dose_rules
                    (id, patient_id, regimen_id, rule_kind, local_time, days_of_week,
                     timezone, enabled, demo_only)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true)
                """,
                (
                    rule.id,
                    rule.patient_id,
                    rule.regimen_id,
                    kind,
                    local_time,
                    days,
                    rule.timezone,
                    rule.enabled,
                ),
            )

    def update(self, rule: DoseRuleDTO) -> None:
        if rule.enabled:
            raise ValidationError("An existing dose rule may only be disabled")
        with self._session(rule.patient_id) as conn:
            _run(
                conn,
                "UPDATE public.dose_rules SET enabled = false WHERE patient_id = %s AND id = %s",
                (rule.patient_id, rule.id),
            )


class PostgresDoseOccurrenceRepository:
    """``DoseOccurrenceRepository`` over ``public.dose_occurrences``."""

    _COLUMNS = "id, patient_id, regimen_id, rule_id, due_at, status, generation_key"

    def __init__(self, session: SessionFactory) -> None:
        self._session = session

    def get(self, patient_id: UUID, occurrence_id: UUID) -> DoseOccurrenceDTO | None:
        with self._session(patient_id) as conn:
            row = _one(
                conn,
                f"SELECT {self._COLUMNS} FROM public.dose_occurrences WHERE patient_id = %s AND id = %s",
                (patient_id, occurrence_id),
            )
        return _occurrence(row) if row else None

    def find_by_generation_key(self, patient_id: UUID, key: str) -> DoseOccurrenceDTO | None:
        with self._session(patient_id) as conn:
            row = _one(
                conn,
                f"SELECT {self._COLUMNS} FROM public.dose_occurrences WHERE patient_id = %s AND generation_key = %s",
                (patient_id, key),
            )
        return _occurrence(row) if row else None

    def list_for_regimen(
        self, patient_id: UUID, regimen_id: UUID, window_start: datetime, window_end: datetime
    ) -> list[DoseOccurrenceDTO]:
        with self._session(patient_id) as conn:
            rows = _rows(
                conn,
                f"SELECT {self._COLUMNS} FROM public.dose_occurrences "
                "WHERE patient_id = %s AND regimen_id = %s "
                "AND due_at >= %s AND due_at < %s ORDER BY due_at",
                (patient_id, regimen_id, window_start, window_end),
            )
        return [_occurrence(row) for row in rows]

    def add(self, occurrence: DoseOccurrenceDTO) -> None:
        with self._session(occurrence.patient_id) as conn:
            ensure_patient_profile(conn, occurrence.patient_id)
            _run(
                conn,
                """
                INSERT INTO public.dose_occurrences
                    (id, patient_id, regimen_id, rule_id, due_at, status,
                     generation_key, demo_only)
                VALUES (%s, %s, %s, %s, %s, %s, %s, true)
                """,
                (
                    occurrence.id,
                    occurrence.patient_id,
                    occurrence.regimen_id,
                    occurrence.rule_id,
                    occurrence.due_at,
                    str(occurrence.status),
                    occurrence.generation_key,
                ),
            )

    def update(self, occurrence: DoseOccurrenceDTO) -> None:
        with self._session(occurrence.patient_id) as conn:
            changed = _run(
                conn,
                "UPDATE public.dose_occurrences SET status = %s WHERE patient_id = %s AND id = %s",
                (str(occurrence.status), occurrence.patient_id, occurrence.id),
            )
        if changed == 0:
            raise NotFoundError(f"Occurrence {occurrence.id} not found")


class PostgresDoseEventRepository:
    """``DoseEventRepository`` over ``public.dose_events``.

    ``confirmation_challenge_id`` is resolved from a genuinely confirmed,
    unconsumed ``record_self_report`` challenge bound to the same regimen,
    occurrence, intake status and idempotency key. When no such challenge
    exists the write is refused with ``ConfirmationRequiredError`` — the
    adapter never manufactures consent to satisfy a NOT NULL column.
    """

    _COLUMNS = (
        "id, patient_id, regimen_id, occurrence_id, event_time, intake_status, "
        "visual_status, ingestion_proven, idempotency_key, created_at"
    )

    def __init__(self, session: SessionFactory, *, include_late_reports: bool = False) -> None:
        self._session = session
        self._read_table = "public.effective_dose_events" if include_late_reports else "public.dose_events"
        self._read_columns = self._COLUMNS + (
            ", reported_late, actual_administration_at" if include_late_reports else ""
        )

    def find_by_idempotency_key(self, patient_id: UUID, key: str) -> DoseEventDTO | None:
        with self._session(patient_id) as conn:
            row = _one(
                conn,
                f"SELECT {self._COLUMNS} FROM public.dose_events WHERE patient_id = %s AND idempotency_key = %s",
                (patient_id, key),
            )
        return _dose_event(row) if row else None

    def find_by_occurrence(self, patient_id: UUID, occurrence_id: UUID) -> DoseEventDTO | None:
        with self._session(patient_id) as conn:
            row = _one(
                conn,
                f"SELECT {self._read_columns} FROM {self._read_table} WHERE patient_id = %s AND occurrence_id = %s",
                (patient_id, occurrence_id),
            )
        return _dose_event(row) if row else None

    def list_for_patient(self, patient_id: UUID, window_start: datetime, window_end: datetime) -> list[DoseEventDTO]:
        with self._session(patient_id) as conn:
            rows = _rows(
                conn,
                f"SELECT {self._read_columns} FROM {self._read_table} "
                "WHERE patient_id = %s AND event_time >= %s AND event_time < %s "
                "ORDER BY event_time",
                (patient_id, window_start, window_end),
            )
        return [_dose_event(row) for row in rows]

    def add(self, event: DoseEventDTO) -> None:
        if event.ingestion_proven:
            raise ValidationError("ingestion_proven must never be true (CHECK constraint)")
        if str(event.visual_status) != "not_checked":
            raise ValidationError("P0 slice: photo evidence is unsupported, visual_status must be not_checked")
        with self._session(event.patient_id) as conn:
            ensure_patient_profile(conn, event.patient_id)
            challenge_id = self._resolve_confirmed_challenge(conn, event)
            _run(
                conn,
                """
                INSERT INTO public.dose_events
                    (id, patient_id, occurrence_id, regimen_id, confirmation_challenge_id,
                     event_time, intake_status, visual_status, evidence_method,
                     ingestion_proven, idempotency_key, demo_only)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'self_report', false, %s, true)
                """,
                (
                    event.id,
                    event.patient_id,
                    event.occurrence_id,
                    event.regimen_id,
                    challenge_id,
                    event.event_time,
                    str(event.intake_status),
                    str(event.visual_status),
                    event.idempotency_key,
                ),
            )

    @staticmethod
    def _resolve_confirmed_challenge(conn: psycopg.Connection, event: DoseEventDTO) -> UUID:
        row = _one(
            conn,
            """
            SELECT id FROM public.confirmation_challenges
             WHERE patient_id = %s
               AND idempotency_key = %s
               AND action = 'record_self_report'
               AND regimen_id = %s
               AND occurrence_id IS NOT DISTINCT FROM %s
               AND intended_intake_status = %s
               AND confirmed_at IS NOT NULL
               AND consumed_at IS NULL
               AND expires_at > now()
             ORDER BY confirmed_at DESC
             LIMIT 1
            """,
            (
                event.patient_id,
                event.idempotency_key,
                event.regimen_id,
                event.occurrence_id,
                str(event.intake_status),
            ),
        )
        if row is None:
            raise ConfirmationRequiredError(
                "Recording a dose event requires a confirmed, unconsumed "
                "'record_self_report' confirmation challenge bound to this regimen, "
                "occurrence, intake status and idempotency key"
            )
        return _as_uuid(row["id"])


class PostgresAgentSessionRepository:
    """``AgentSessionRepository`` over ``public.agent_sessions``."""

    _COLUMNS = (
        "id, patient_id, intent, state, pending_field_names, "
        "state_version, updated_at, expires_at, context, conversation_id"
    )

    def __init__(self, session: SessionFactory) -> None:
        self._session = session

    def get(self, patient_id: UUID, session_id: UUID) -> AgentSessionDTO | None:
        with self._session(patient_id) as conn:
            row = _one(
                conn,
                f"SELECT {self._COLUMNS} FROM public.agent_sessions WHERE patient_id = %s AND id = %s",
                (patient_id, session_id),
            )
        return _session(row) if row else None

    def is_owned_by_other_patient(self, patient_id: UUID, session_id: UUID) -> bool:
        """True when the session id already belongs to a different patient."""
        with self._session(patient_id) as conn:
            found = _scalar(
                conn,
                "SELECT 1 FROM public.agent_sessions WHERE id = %s AND patient_id <> %s LIMIT 1",
                (session_id, patient_id),
            )
        return found is not None

    def add(self, session: AgentSessionDTO) -> None:
        with self._session(session.patient_id) as conn:
            ensure_patient_profile(conn, session.patient_id)
            _run(
                conn,
                """
                INSERT INTO public.agent_sessions
                    (id, patient_id, intent, state, pending_field_names, prompt_version,
                     state_version, updated_at, expires_at, context, conversation_id, demo_only)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true)
                """,
                (
                    session.id,
                    session.patient_id,
                    session.intent,
                    session.state,
                    list(session.pending_field_names),
                    DETERMINISTIC_PROMPT_VERSION,
                    session.state_version,
                    session.updated_at,
                    session.expires_at,
                    Jsonb(session.context.model_dump(mode="json")),
                    session.conversation_id,
                ),
            )

    def update(self, session: AgentSessionDTO) -> None:
        with self._session(session.patient_id) as conn:
            changed = _run(
                conn,
                """
                UPDATE public.agent_sessions
                   SET intent = %s, state = %s, pending_field_names = %s,
                       state_version = %s, updated_at = %s, expires_at = %s, context = %s, conversation_id = %s
                 WHERE patient_id = %s AND id = %s
                """,
                (
                    session.intent,
                    session.state,
                    list(session.pending_field_names),
                    session.state_version,
                    session.updated_at,
                    session.expires_at,
                    Jsonb(session.context.model_dump(mode="json")),
                    session.conversation_id,
                    session.patient_id,
                    session.id,
                ),
            )
        if changed == 0:
            raise NotFoundError(f"Agent session {session.id} not found")


class PostgresConfirmationChallengeRepository:
    """``ConfirmationChallengeRepository`` over ``public.confirmation_challenges``.

    ``core_guard_challenge`` makes the binding immutable and consumption
    one-time, so the update path writes only ``confirmed_at`` and
    ``consumed_at``, and only when that specific transition is still legal. An
    activation performed by ``core_guard_regimen`` consumes the challenge
    inside the database, so a later application write of the same fact is
    recognised as already done instead of being sent as a second write.
    """

    _COLUMNS = (
        "id, patient_id, session_id, session_state_version, action, regimen_id, "
        "occurrence_id, intended_intake_status, idempotency_key, token_hash, "
        "issued_at, expires_at, confirmed_at, consumed_at"
    )

    def __init__(self, session: SessionFactory) -> None:
        self._session = session

    def get(self, patient_id: UUID, challenge_id: UUID) -> ConfirmationChallengeDTO | None:
        with self._session(patient_id) as conn:
            row = _one(
                conn,
                f"SELECT {self._COLUMNS} FROM public.confirmation_challenges WHERE patient_id = %s AND id = %s",
                (patient_id, challenge_id),
            )
        return _challenge(row) if row else None

    def find_by_token_hash(self, patient_id: UUID, token_hash: str) -> ConfirmationChallengeDTO | None:
        with self._session(patient_id) as conn:
            row = _one(
                conn,
                f"SELECT {self._COLUMNS} FROM public.confirmation_challenges WHERE patient_id = %s AND token_hash = %s",
                (patient_id, token_hash),
            )
        return _challenge(row) if row else None

    def find_by_idempotency_key(self, patient_id: UUID, idempotency_key: str) -> ConfirmationChallengeDTO | None:
        """Patient-scoped lookup; mirrors UNIQUE (patient_id, idempotency_key)."""
        with self._session(patient_id) as conn:
            row = _one(
                conn,
                f"SELECT {self._COLUMNS} FROM public.confirmation_challenges "
                "WHERE patient_id = %s AND idempotency_key = %s",
                (patient_id, idempotency_key),
            )
        return _challenge(row) if row else None

    def add(self, challenge: ConfirmationChallengeDTO) -> None:
        with self._session(challenge.patient_id) as conn:
            ensure_patient_profile(conn, challenge.patient_id)
            _run(
                conn,
                """
                INSERT INTO public.confirmation_challenges
                    (id, patient_id, session_id, session_state_version, action, regimen_id,
                     occurrence_id, intended_intake_status, idempotency_key, token_hash,
                     request_hash, issued_at, expires_at, confirmed_at, consumed_at, demo_only)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true)
                """,
                (
                    challenge.id,
                    challenge.patient_id,
                    challenge.session_id,
                    challenge.session_state_version,
                    challenge.action,
                    challenge.regimen_id,
                    challenge.occurrence_id,
                    str(challenge.intended_intake_status) if challenge.intended_intake_status is not None else None,
                    challenge.idempotency_key,
                    challenge.token_hash,
                    challenge_request_hash(
                        patient_id=challenge.patient_id,
                        action=challenge.action,
                        regimen_id=challenge.regimen_id,
                        occurrence_id=challenge.occurrence_id,
                        intake_status=(
                            str(challenge.intended_intake_status)
                            if challenge.intended_intake_status is not None
                            else None
                        ),
                        idempotency_key=challenge.idempotency_key,
                    ),
                    challenge.issued_at,
                    challenge.expires_at,
                    challenge.confirmed_at,
                    challenge.consumed_at,
                ),
            )

    def update(self, challenge: ConfirmationChallengeDTO) -> None:
        with self._session(challenge.patient_id) as conn:
            current = _one(
                conn,
                "SELECT confirmed_at, consumed_at FROM public.confirmation_challenges "
                "WHERE patient_id = %s AND id = %s FOR UPDATE",
                (challenge.patient_id, challenge.id),
            )
            if current is None:
                raise NotFoundError(f"Challenge {challenge.id} not found")

            if challenge.confirmed_at is not None and current["confirmed_at"] is None:
                _run(
                    conn,
                    "UPDATE public.confirmation_challenges SET confirmed_at = %s "
                    "WHERE patient_id = %s AND id = %s AND confirmed_at IS NULL",
                    (challenge.confirmed_at, challenge.patient_id, challenge.id),
                )

            # Consumption is performed by core_guard_regimen / core_guard_dose_event
            # inside the protected write. If the row is already consumed the
            # application's write of the same fact is a no-op, not a second one.
            if challenge.consumed_at is not None and current["consumed_at"] is None:
                _run(
                    conn,
                    "UPDATE public.confirmation_challenges SET consumed_at = %s "
                    "WHERE patient_id = %s AND id = %s AND consumed_at IS NULL",
                    (challenge.consumed_at, challenge.patient_id, challenge.id),
                )


class PostgresToolTraceRepository:
    """``ToolTraceRepository`` over ``public.agent_tool_calls``."""

    _COLUMNS = (
        "id, patient_id, session_id, correlation_id, tool_name, tool_status, "
        "request_summary, response_summary, called_at, duration_ms"
    )

    def __init__(self, session: SessionFactory) -> None:
        self._session = session

    def add(self, trace: ToolTraceDTO) -> None:
        with self._session(trace.patient_id) as conn:
            ensure_patient_profile(conn, trace.patient_id)
            _run(
                conn,
                """
                INSERT INTO public.agent_tool_calls
                    (id, patient_id, session_id, correlation_id, tool_name, tool_status,
                     request_summary, response_summary, duration_ms, called_at, demo_only)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true)
                """,
                (
                    trace.id,
                    trace.patient_id,
                    trace.session_id,
                    trace.correlation_id,
                    trace.tool_name,
                    trace.tool_status,
                    Jsonb(trace.request_summary),
                    Jsonb(trace.response_summary),
                    trace.duration_ms,
                    trace.called_at,
                ),
            )

    def list_for_session(self, patient_id: UUID, session_id: UUID) -> list[ToolTraceDTO]:
        with self._session(patient_id) as conn:
            rows = _rows(
                conn,
                f"SELECT {self._COLUMNS} FROM public.agent_tool_calls "
                "WHERE patient_id = %s AND session_id = %s ORDER BY called_at, id",
                (patient_id, session_id),
            )
        return [_trace(row) for row in rows]


@dataclass(frozen=True)
class PostgresRepositories:
    """Bundle of every Port implementation backed by one database target."""

    database: PostgresDatabase
    #: Which trust boundary this bundle runs under. Recorded so a diagnostic
    #: report can state it instead of assuming it.
    session_mode: str
    sources: PostgresSourceDocumentRepository
    source_fields: PostgresSourceFieldRepository
    medications: PostgresPatientMedicationRepository
    regimens: PostgresRegimenVersionRepository
    dose_rules: PostgresDoseRuleRepository
    occurrences: PostgresDoseOccurrenceRepository
    events: PostgresDoseEventRepository
    sessions: PostgresAgentSessionRepository
    challenges: PostgresConfirmationChallengeRepository
    traces: PostgresToolTraceRepository


def build_postgres_repositories(
    database: PostgresDatabase, *, session: SessionFactory | None = None, include_late_reports: bool = False
) -> PostgresRepositories:
    """Construct the adapter bundle over one database target.

    ``session`` selects the trust boundary. It defaults to the **privileged**
    factory so existing admin/verification callers are unchanged, but any code
    path that serves a patient request must pass ``patient_rls_session(database)``
    explicitly — see ``build_patient_rls_repositories``.
    """
    if session is None:
        session = privileged_session(database)
        mode = "privileged_bypassrls"
    else:
        mode = "patient_rls_enforced"
    return PostgresRepositories(
        database=database,
        session_mode=mode,
        sources=PostgresSourceDocumentRepository(session),
        source_fields=PostgresSourceFieldRepository(session),
        medications=PostgresPatientMedicationRepository(session),
        regimens=PostgresRegimenVersionRepository(session),
        dose_rules=PostgresDoseRuleRepository(session),
        occurrences=PostgresDoseOccurrenceRepository(session),
        events=PostgresDoseEventRepository(session, include_late_reports=include_late_reports),
        sessions=PostgresAgentSessionRepository(session),
        challenges=PostgresConfirmationChallengeRepository(session),
        traces=PostgresToolTraceRepository(session),
    )


def build_patient_rls_repositories(database: PostgresDatabase) -> PostgresRepositories:
    """Adapter bundle for the **normal authenticated patient** path.

    Every statement runs as ``pharmascan_patient`` with ``auth.uid()`` set from
    the verified identity, so the database's RLS policies are an independent
    control behind the adapter's own ``patient_id`` predicate.
    """
    return build_postgres_repositories(database, session=patient_rls_session(database))
