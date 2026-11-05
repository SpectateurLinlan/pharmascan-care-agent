"""Explicit isolated acceptance admission. Import/validation never connects or reads .env."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse, urlunparse
from uuid import UUID

from app.infrastructure.workflow_verification import EvidenceConnectionSettings

from .workflow_live_support import sql_target, storage_target

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "supabase/review/assistant_workflows"
SCOPES = frozenset({"sql_read", "sql_write", "storage_read", "storage_write", "down_probe"})


class PersistentProfileRefusal(ValueError):
    code = "target_not_authorized"

    def __init__(self):
        super().__init__(self.code)


@dataclass(frozen=True)
class PersistentWorkflowTestProfile:
    enabled: bool = False
    approved: bool = False
    sql_enabled: bool = False
    storage_enabled: bool = False
    down_approved: bool = False
    approval_id: str = field(default="", repr=False)
    operations: frozenset[str] = frozenset()
    database_url: str = field(default="", repr=False)
    evidence_dsn: str = field(default="", repr=False)
    owner_a: str = field(default="", repr=False)
    owner_b: str = field(default="", repr=False)
    storage_values: Mapping[str, str] = field(default_factory=dict, repr=False)
    approved_candidate_hashes: Mapping[str, str] = field(default_factory=dict, repr=False)
    invalid: bool = False
    target_mode: str = field(default="legacy", kw_only=True)
    local_receipt_path: str = field(default="", repr=False, kw_only=True)

    @classmethod
    def from_values(cls, values: Mapping[str, str]) -> PersistentWorkflowTestProfile:
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in values.items()):
            return cls(invalid=True)
        try:
            hashes = json.loads(values.get("ASSISTANT_TEST_CANDIDATE_HASHES", "{}"))
            if not isinstance(hashes, dict) or any(not isinstance(v, str) for v in hashes.values()):
                raise ValueError
        except (ValueError, TypeError):
            return cls(invalid=True)
        storage_names = (
            "ASSISTANT_TEST_SUPABASE_URL",
            "ASSISTANT_TEST_PROJECT_REF",
            "ASSISTANT_NORMAL_SUPABASE_URL",
            "ASSISTANT_TEST_SUPABASE_DATABASE_URL",
            "ASSISTANT_TEST_PUBLISHABLE_KEY",
            "ASSISTANT_TEST_JWT_A",
            "ASSISTANT_TEST_JWT_B",
        )
        return cls(
            target_mode=values.get("ASSISTANT_TEST_TARGET_MODE", "legacy"),
            local_receipt_path=values.get("ASSISTANT_TEST_LOCAL_RECEIPT_PATH", ""),
            enabled=values.get("RUN_ASSISTANT_PERSISTENCE_TESTS") == "1",
            approved=values.get("ASSISTANT_PERSISTENCE_APPROVED") == "1",
            sql_enabled=values.get("RUN_ASSISTANT_SQL_TESTS") == "1",
            storage_enabled=values.get("RUN_ASSISTANT_STORAGE_TESTS") == "1",
            down_approved=values.get("ASSISTANT_PERSISTENCE_DOWN_APPROVED") == "1",
            approval_id=values.get("ASSISTANT_PERSISTENCE_APPROVAL_ID", ""),
            operations=frozenset(values.get("ASSISTANT_PERSISTENCE_OPERATIONS", "").split(",")) - {""},
            database_url=values.get("ASSISTANT_TEST_DATABASE_URL", ""),
            evidence_dsn=values.get("ASSISTANT_TEST_EVIDENCE_DSN", ""),
            owner_a=values.get("ASSISTANT_TEST_OWNER_A", ""),
            owner_b=values.get("ASSISTANT_TEST_OWNER_B", ""),
            storage_values={name: values.get(name, "") for name in storage_names},
            approved_candidate_hashes=hashes,
            invalid=any(
                values.get(k)
                for k in (
                    "ASSISTANT_TEST_SERVICE_ROLE_KEY",
                    "ASSISTANT_TEST_SUPABASE_SECRET_KEY",
                )
            ),
        )


@dataclass(frozen=True)
class ApprovedTestTarget:
    database_fingerprint: str
    owner_a: UUID = field(repr=False)
    owner_b: UUID = field(repr=False)
    candidate_hashes: dict[str, str]


def candidate_hashes() -> dict[str, str]:
    """Public source inventory, never an applied-migration or target acceptance claim."""
    paths = [
        ROOT / "supabase/migrations/202610250035_assistant_workflows.sql",
        ROOT / "supabase/migrations/202610250036_enrollment_workflow_idempotency.sql",
        *sorted(REVIEW.glob("*.sql")),
    ]
    if len(paths) < 25 or any(not p.resolve().is_relative_to(ROOT.resolve()) for p in paths):
        raise PersistentProfileRefusal()
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def validate_patient_claims(profile: PersistentWorkflowTestProfile, owners: tuple[UUID, UUID]) -> None:
    """Offline consistency only; every local live entry additionally verifies real Auth."""
    expected = profile.storage_values["ASSISTANT_TEST_SUPABASE_URL"].rstrip("/") + "/auth/v1"
    for key, owner in zip(("ASSISTANT_TEST_JWT_A", "ASSISTANT_TEST_JWT_B"), owners, strict=True):
        token = profile.storage_values[key]
        if len(token) > 16384 or len(token.split(".")) != 3:
            raise ValueError
        body = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if (
            UUID(claims.get("sub", "")) != owner
            or claims.get("role") != "authenticated"
            or claims.get("iss") != expected
            or type(claims.get("exp")) is not int
            or claims["exp"] <= datetime.now(UTC).timestamp()
        ):
            raise ValueError
    # These are admission consistency checks only. Real Auth must verify each token before any Storage write.


def validate_persistent_test_profile(
    profile: PersistentWorkflowTestProfile,
    *,
    purpose: str = "sql_read",
    require_hashes: bool = False,
) -> ApprovedTestTarget:
    try:
        if (
            profile.invalid
            or profile.target_mode not in {"legacy", "local_supabase"}
            or not profile.enabled
            or not profile.approved
            or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", profile.approval_id)
            or purpose not in SCOPES
            or purpose not in profile.operations
            or profile.operations - SCOPES
            or purpose in {"sql_write", "down_probe"}
            and not profile.sql_enabled
            or purpose == "down_probe"
            and not profile.down_approved
            or purpose.startswith("storage_")
            and not profile.storage_enabled
        ):
            raise ValueError
        if profile.target_mode == "local_supabase":
            from .local_supabase_live_support import validate_local_profile

            return validate_local_profile(profile)
        name = sql_target(profile.database_url)
        db, evidence = urlparse(profile.database_url), urlparse(profile.evidence_dsn)
        EvidenceConnectionSettings(profile.evidence_dsn)
        # Reuse the loopback/database-prefix guard; only the verifier's validated TLS query may differ.
        if sql_target(urlunparse(evidence._replace(query=""))) != name:
            raise ValueError
        if (
            db.hostname != evidence.hostname
            or db.port != evidence.port
            or db.path != evidence.path
            or unquote(evidence.username or "") != "assistant_evidence_login"
            or unquote(db.username or "") not in {"postgres", "pharmascan_patient"}
            or not db.password
        ):
            raise ValueError
        owners = UUID(profile.owner_a), UUID(profile.owner_b)
        if owners[0] == owners[1] or any(owner.int == 0 for owner in owners):
            raise ValueError
        if purpose.startswith("storage_"):
            storage_target(dict(profile.storage_values))
            validate_patient_claims(profile, owners)
        hashes = candidate_hashes()
        if (require_hashes or profile.approved_candidate_hashes) and dict(profile.approved_candidate_hashes) != hashes:
            raise ValueError
        fingerprint = hashlib.sha256(f"{db.hostname}:{db.port}/{name}".encode()).hexdigest()
        return ApprovedTestTarget(fingerprint, *owners, hashes)
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, OSError):
        raise PersistentProfileRefusal() from None


def admitted_live_profile(purpose: str):
    """Pytest entry: opt-out skips before examining credentials; invalid opt-in fails before connecting."""
    import os

    import pytest

    if os.environ.get("RUN_ASSISTANT_PERSISTENCE_TESTS") != "1":
        pytest.skip("NOT_RUN: separately approved persistent target/scope required; no connection attempted")
    profile = PersistentWorkflowTestProfile.from_values(dict(os.environ))
    try:
        target = validate_persistent_test_profile(profile, purpose=purpose, require_hashes=True)
        if profile.target_mode == "local_supabase":
            from .local_supabase_live_support import verify_local_live_target

            verify_local_live_target(profile, target)
    except PersistentProfileRefusal:
        pytest.fail("target_not_authorized; no connection attempted", pytrace=False)
    return profile, target


def sql_connection_parameters(profile: PersistentWorkflowTestProfile, *, verifier: bool, read_only: bool) -> dict:
    """Explicit parameters exclude ambient libpq services, host overrides and password files."""
    import ipaddress
    import os

    if any(os.environ.get(name) for name in ("PGSERVICE", "PGSERVICEFILE", "PGHOSTADDR", "PGSSLCERT", "PGSSLKEY")):
        raise PersistentProfileRefusal()
    parsed = urlparse(profile.evidence_dsn if verifier else profile.database_url)
    query = parse_qs(parsed.query)
    try:
        hostaddr = str(ipaddress.ip_address(parsed.hostname))
    except ValueError:
        hostaddr = ""
    return {
        "host": parsed.hostname,
        "hostaddr": hostaddr,
        "port": parsed.port,
        "dbname": parsed.path[1:],
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "passfile": "",
        "sslmode": query.get("sslmode", ["disable"])[0],
        "sslrootcert": query.get("sslrootcert", [""])[0],
        "sslcert": "",
        "sslkey": "",
        "gssencmode": "disable",
        "connect_timeout": 3,
        "autocommit": True,
        "application_name": "medithread-isolated-acceptance",
        "options": "-c statement_timeout=3000 -c lock_timeout=1000"
        + (" -c default_transaction_read_only=on" if read_only else ""),
    }


def reserve_claimed_original(originals, verified, context, attachment):
    reserved = originals.reserve(context, attachment)
    writer = reserved.operation_event_id or reserved.upload_id
    ticket = verified.reserve_ticket(context, reserved.id, writer)
    verified.claim_ticket(context.owner, ticket)
    return ticket
