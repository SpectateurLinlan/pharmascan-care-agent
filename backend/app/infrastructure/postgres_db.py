"""Postgres/Supabase connection handling.

Explicit injection only (AGENTS.md rule 2): this class owns a connection
*factory*; it never exposes a module-level connection, session or engine, so
nothing in the application can reach the database without being handed one.
The application/domain layers never import this module.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit

import psycopg
from psycopg.rows import dict_row

DEFAULT_STATEMENT_TIMEOUT_MS = 15_000
DEFAULT_CONNECT_TIMEOUT_S = 15


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
