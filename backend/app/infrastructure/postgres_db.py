"""Postgres/Supabase connection handling.

Explicit injection only (AGENTS.md rule 2): this class owns a connection
*factory*; it never exposes a module-level connection, session or engine, so
nothing in the application can reach the database without being handed one.
The application/domain layers never import this module.

Two connection *modes* exist, and the difference is a security boundary
(Session 3D — see supabase/migrations/202610130004_patient_rls_role.sql):

``transaction()``
    The **privileged** mode. It runs as the ``DATABASE_URL`` role, which on the
    Supabase development project is ``postgres`` with ``rolbypassrls = true``.
    Reserved for migrations, schema verification, maintenance and admin setup.
    It must never be the normal patient read/write path.

``patient_transaction()``
    The **RLS-enforced** patient mode. Inside one transaction it switches to a
    dedicated ``NOLOGIN NOBYPASSRLS`` role and sets ``request.jwt.claims.sub``
    from the already-verified patient identity, so ``auth.uid()`` resolves and
    the ``*_owner`` row-level-security policies decide what is visible. A
    forgotten ``WHERE patient_id = ...`` therefore cannot leak a row.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

DEFAULT_STATEMENT_TIMEOUT_MS = 15_000
DEFAULT_CONNECT_TIMEOUT_S = 15

#: The dedicated, non-PostgREST, NOBYPASSRLS role created by
#: supabase/migrations/202610130004_patient_rls_role.sql. It is NOLOGIN and is
#: not a member of ``authenticator``, so PostgREST can never assume it — the
#: guard functions therefore stay unreachable over the Data API.
PATIENT_RLS_ROLE = "pharmascan_patient"


def mask_dsn(dsn: str) -> str:
    """Return a diagnostic-safe description of a connection string.

    The host's first label (the Supabase project ref) and every credential are
    redacted, so the result is safe for logs and evidence files.
    """
    try:
        parts = urlsplit(dsn)
    except ValueError:
        return "unparseable-dsn"
    host = parts.hostname or ""
    labels = host.split(".")
    if labels and labels[0]:
        labels[0] = "***"
    return (
        f"scheme={parts.scheme or 'postgresql'} host={'.'.join(labels) or '(none)'} "
        f"port={parts.port or 5432} db={(parts.path or '/').lstrip('/') or '(none)'} "
        f"user_set={bool(parts.username)} password_set={bool(parts.password)}"
    )


@dataclass(frozen=True)
class PostgresTarget:
    """Non-secret description of the configured database target."""

    description: str
    host: str
    port: int
    database: str

    @classmethod
    def from_dsn(cls, dsn: str) -> PostgresTarget:
        parts = urlsplit(dsn)
        return cls(
            description=mask_dsn(dsn),
            host=parts.hostname or "",
            port=parts.port or 5432,
            database=(parts.path or "/postgres").lstrip("/"),
        )


class PostgresDatabase:
    """Injected connection factory for the Postgres/Supabase adapter."""

    def __init__(
        self,
        *,
        dsn: str,
        application_name: str = "pharmascan-care-agent",
        statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
        connect_timeout_s: int = DEFAULT_CONNECT_TIMEOUT_S,
    ) -> None:
        if not dsn:
            raise ValueError("dsn is required")
        if statement_timeout_ms <= 0:
            raise ValueError("statement_timeout_ms must be positive")
        self._dsn = dsn
        self._application_name = application_name
        self._options = (
            f"-c statement_timeout={statement_timeout_ms} "
            f"-c idle_in_transaction_session_timeout={statement_timeout_ms * 2}"
        )
        self._connect_timeout = connect_timeout_s

    @property
    def target(self) -> PostgresTarget:
        return PostgresTarget.from_dsn(self._dsn)

    @contextmanager
    def connect(self, *, autocommit: bool = False) -> Iterator[psycopg.Connection]:
        """Open one short-lived connection; commit on success, roll back on error."""
        connection = psycopg.connect(
            self._dsn,
            autocommit=autocommit,
            row_factory=dict_row,
            application_name=self._application_name,
            options=self._options,
            connect_timeout=self._connect_timeout,
        )
        try:
            yield connection
        except Exception:
            if not connection.closed:
                connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection]:
        """One unit of work; the caller's statements run in a single transaction."""
        with self.connect() as connection:
            with connection.transaction():
                yield connection

    @contextmanager
    def patient_transaction(self, *, patient_id: UUID, role: str = PATIENT_RLS_ROLE) -> Iterator[psycopg.Connection]:
        """One unit of work **as the RLS-enforced patient role**.

        ``patient_id`` must already be a *verified* identity (derived from a
        validated Supabase access token, or the explicitly synthetic demo
        principal). It is placed in ``request.jwt.claims.sub`` — the same claim
        PostgREST populates — so ``auth.uid()`` resolves to it and every
        ``*_owner`` policy applies to this transaction.

        The role name is a module constant, not caller input, and is re-checked
        here because it is interpolated into ``SET LOCAL ROLE`` (which cannot be
        parameterised).
        """
        if role != PATIENT_RLS_ROLE:
            raise ValueError(f"refusing to assume unexpected role {role!r}")
        claims = json.dumps({"sub": str(patient_id), "role": "authenticated"})
        with self.connect() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    # SET LOCAL is transaction-scoped: the role and the claim
                    # can never outlive this connection's transaction.
                    cursor.execute(f"SET LOCAL ROLE {PATIENT_RLS_ROLE}")
                    cursor.execute("SELECT set_config('request.jwt.claims', %s, true)", (claims,))
                yield connection
