"""Lazy, fixed-command evidence connection; never a patient/admin repository."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic
from urllib.parse import parse_qsl, unquote, urlsplit

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..contracts.agent_execution import BudgetExceeded, DeadlineExceeded, TaskCancelled
from ..contracts.workflow_media_cleanup import MediaDeleteObservation, VerifiedMediaDeleteRef
from ..contracts.workflow_media_storage import MediaStorageObservation, VerifiedMediaOperationRef
from ..contracts.workflow_run_control import RUN_WORKER_COMMAND, RunControlState
from ..contracts.workflow_runtime import RuntimeReleaseSnapshot
from ..contracts.workflow_verification import StorageObservation, VerifiedOperationRef
from ..domain.errors import DuplicateEventError, NotFoundError, ProviderUnavailableError, StaleVersionError

_ROLE = "assistant_evidence_login"
_NATIVE_MEDIA_COMMAND = "SELECT assistant_evidence.record_native_media_observation(%s) AS result"
_STORAGE_COMMAND = "SELECT assistant_evidence.record_storage_observation(%s) AS result"
_MEDIA_COMMAND = "SELECT assistant_evidence.record_media_storage_observation(%s) AS result"
_MEDIA_DELETE_COMMAND = "SELECT assistant_evidence.record_media_delete_observation(%s) AS result"
_RUN_COMMAND = "SELECT assistant_evidence.record_run_observation(%s) AS result"
_IDENTITY = """SELECT session_user AS login,current_user AS role,
 r.rolsuper,r.rolcreatedb,r.rolcreaterole,r.rolreplication,r.rolbypassrls,r.rolinherit,
 EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members m WHERE m.member=r.oid) AS has_memberships
 FROM pg_catalog.pg_roles r WHERE r.rolname=session_user"""
_FALSE_ATTRIBUTES = (
    "rolsuper",
    "rolcreatedb",
    "rolcreaterole",
    "rolreplication",
    "rolbypassrls",
    "rolinherit",
    "has_memberships",
)


class _RunRejection(Exception):
    def __init__(self, code):
        super().__init__("Run observation rejected")
        allowed = {"budget", "deadline", "cancelled", "duplicate", "not_found", "stale"}
        self.code = code if code in allowed else "unavailable"


@dataclass(frozen=True)
class EvidenceConnectionSettings:
    dsn: str = field(repr=False)

    def __post_init__(self):
        self._parameters()

    def _parameters(self):
        try:
            url = urlsplit(self.dsn)
            user = unquote(url.username or "")
            password = unquote(url.password or "")
            pairs = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True)
            query = dict(pairs)
            loopback = url.hostname in {"127.0.0.1", "localhost", "::1"}
            if (
                url.scheme not in {"postgres", "postgresql"}
                or not url.hostname
                or not re.fullmatch(r"[a-zA-Z0-9.:-]+", url.hostname)
                or url.fragment
                or not re.fullmatch(r"assistant_evidence_login(?:\.[a-z0-9]+)?", user)
                or not password
                or not re.fullmatch(r"/[a-zA-Z0-9_]+", url.path)
                or len(query) != len(pairs)
                or set(query) - {"sslmode", "sslrootcert"}
                or not 1 <= (url.port or 5432) <= 65535
                or query.get("sslmode", "verify-full")
                not in ({"verify-full", "disable"} if loopback else {"verify-full"})
            ):
                raise ValueError
            return {
                "host": url.hostname,
                "port": url.port or 5432,
                "user": user,
                "password": password,
                "dbname": url.path[1:],
                "sslmode": query.get("sslmode", "disable" if loopback else "verify-full"),
                "sslrootcert": query.get(
                    "sslrootcert", "" if loopback and query.get("sslmode", "disable") == "disable" else "system"
                ),
                "passfile": "",
                "gssencmode": "disable",
                "application_name": "medithread-evidence",
            }
        except (ValueError, TypeError, AttributeError):
            raise ValueError(
                "ASSISTANT_EVIDENCE_DSN requires an explicit restricted identity and verified target"
            ) from None


class RestrictedEvidenceConnection:
    def __init__(
        self,
        settings: EvidenceConnectionSettings,
        *,
        connect: Callable[..., psycopg.Connection] = psycopg.connect,
        clock: Callable[[], float] = monotonic,
    ):
        self._settings, self._connect, self._clock = settings, connect, clock

    def record_storage_observation(
        self, observation: StorageObservation, *, timeout_seconds: float
    ) -> VerifiedOperationRef:
        return self._execute("storage", observation, timeout_seconds=timeout_seconds)

    def record_run_observation(self, command, *, timeout_seconds: float) -> RunControlState:
        command = RUN_WORKER_COMMAND.validate_python(command)
        return self._execute("run", command, timeout_seconds=timeout_seconds)

    def record_media_storage_observation(
        self, observation: MediaStorageObservation, *, timeout_seconds: float
    ) -> VerifiedMediaOperationRef:
        observation = MediaStorageObservation.model_validate(observation)
        return self._execute('media', observation, timeout_seconds=timeout_seconds)

    def record_media_delete_observation(
        self, observation: MediaDeleteObservation, *, timeout_seconds: float
    ) -> VerifiedMediaDeleteRef:
        observation=MediaDeleteObservation.model_validate(observation)
        return self._execute('media_delete',observation,timeout_seconds=timeout_seconds)

    def record_native_media_observation(self, observation, *, timeout_seconds):
        from ..contracts.native_media_verification import NativeMediaObservation
        observation = NativeMediaObservation.model_validate(observation)
        return self._execute("native_object", observation, timeout_seconds=timeout_seconds)

    def read_release(self, *, timeout_seconds: float) -> RuntimeReleaseSnapshot:
        return self._execute("readiness", None, timeout_seconds=timeout_seconds)

    def _execute(self, operation, payload, *, timeout_seconds):
        # libpq cannot honor a sub-two-second connect timeout. Refuse instead of
        # silently giving a near-expired request a larger connection budget.
        if type(timeout_seconds) not in {int, float} or not math.isfinite(timeout_seconds) or timeout_seconds < 2:
            raise ProviderUnavailableError("Verification budget unavailable; inspect current operation before retrying")
        deadline = self._clock() + timeout_seconds
        connection = None
        try:
            initial_ms = max(1, math.floor(min(2, timeout_seconds) * 1000))
            connection = self._connect(
                **self._settings._parameters(),
                connect_timeout=math.floor(min(3, timeout_seconds)),
                options=f"-c statement_timeout={initial_ms} -c lock_timeout={initial_ms}",
                row_factory=dict_row,
            )
            with connection.transaction():
                if operation == "readiness":
                    connection.execute("SET TRANSACTION READ ONLY")
                self._set_remaining(connection, deadline)
                identity = connection.execute(_IDENTITY).fetchone()
                if (
                    not isinstance(identity, dict)
                    or identity.get("login") != _ROLE
                    or identity.get("role") != _ROLE
                    or any(identity.get(name) is not False for name in _FALSE_ATTRIBUTES)
                ):
                    raise ValueError("Restricted verification identity required")
                self._set_remaining(connection, deadline)
                sql = {'storage':_STORAGE_COMMAND, 'media':_MEDIA_COMMAND, 'run':_RUN_COMMAND,
                       'media_delete':_MEDIA_DELETE_COMMAND, 'native_object':_NATIVE_MEDIA_COMMAND,
                       'readiness': 'SELECT assistant_evidence.runtime_readiness() AS result'}[operation]
                row = (connection.execute(sql).fetchone() if operation == "readiness" else
                       connection.execute(sql, (Jsonb(payload.model_dump(mode="json")),)).fetchone())
                if operation == "readiness":
                    result = RuntimeReleaseSnapshot.model_validate_json(json.dumps(row["result"]))
                elif operation in {'storage','media','media_delete','native_object'}:
                    from ..contracts.native_media_verification import VerifiedNativeMediaRef
                    model = {'media':VerifiedMediaOperationRef,'storage':VerifiedOperationRef,
                             'media_delete':VerifiedMediaDeleteRef, 'native_object':VerifiedNativeMediaRef}[operation]
                    result = model.model_validate(row["result"])
                    if (result.ticket_id != payload.ticket_id or result.generation != payload.generation
                            or (result.result != payload.result and payload.result != "outcome_unknown")):
                        raise ValueError("Verification response binding changed")
                else:
                    raw = row["result"]
                    if isinstance(raw, dict) and set(raw) == {"error"}:
                        raise _RunRejection(raw["error"] if isinstance(raw["error"], str) else "unavailable")
                    result = RunControlState.model_validate(raw)
                    if (result.worker_ticket != payload.ticket_id or result.worker_nonce != payload.nonce
                            or result.epoch != (1 if payload.kind == "claim" else payload.epoch)):
                        raise ValueError("Run observation response binding changed")
                if self._clock() >= deadline:
                    raise ValueError("Verification deadline exceeded")
            return result
        except _RunRejection as error:
            stops = {"budget": BudgetExceeded, "deadline": DeadlineExceeded, "cancelled": TaskCancelled}
            if error.code in stops:
                raise stops[error.code]() from None
            errors = {"duplicate": DuplicateEventError, "not_found": NotFoundError, "stale": StaleVersionError}
            error_type = errors.get(error.code, ProviderUnavailableError)
            raise error_type("Run observation changed; inspect its current state") from None
        except Exception:
            # Driver, validation and remote errors can contain credentials or raw
            # JSON. None of their messages crosses this infrastructure boundary.
            raise ProviderUnavailableError(
                "Verification outcome unavailable; inspect current operation before retrying"
            ) from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    def _set_remaining(self, connection, deadline):
        milliseconds = math.floor(min(2, deadline - self._clock()) * 1000)
        if milliseconds < 1:
            raise ValueError("Verification deadline exceeded")
        connection.execute("SELECT pg_catalog.set_config('statement_timeout', %s, true)", (str(milliseconds),))


class PostgresEvidenceVerifier:
    def __init__(self, connection: RestrictedEvidenceConnection):
        self._connection = connection

    def read_release(self, *, timeout_seconds: float) -> RuntimeReleaseSnapshot:
        return self._connection.read_release(timeout_seconds=timeout_seconds)

    def record_storage(self, observation: StorageObservation, *, timeout_seconds: float) -> VerifiedOperationRef:
        return self._connection.record_storage_observation(observation, timeout_seconds=timeout_seconds)

    def record_run(self, command, *, timeout_seconds: float) -> RunControlState:
        return self._connection.record_run_observation(command, timeout_seconds=timeout_seconds)

    def record_media_storage(
        self, observation: MediaStorageObservation, *, timeout_seconds: float
    ) -> VerifiedMediaOperationRef:
        return self._connection.record_media_storage_observation(observation, timeout_seconds=timeout_seconds)

    def record_media_delete(
        self, observation: MediaDeleteObservation, *, timeout_seconds: float
    ) -> VerifiedMediaDeleteRef:
        return self._connection.record_media_delete_observation(observation,timeout_seconds=timeout_seconds)

    def record_native_media(self, observation, *, timeout_seconds):
        return self._connection.record_native_media_observation(observation, timeout_seconds=timeout_seconds)
