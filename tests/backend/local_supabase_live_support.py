"""Closed offline receipt bindings; this module alone never admits a live write.

Runtime container/network, Auth identity and SQL/Data API nonce checks remain
separate prerequisites. A receipt describes a target and grants no authority.
"""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import unquote, urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
CLI_HASH = "81710c292b3defbfe05d990d46a56501c1be33528b0a113ff39531c2c8ee6de9"


class _FrozenReceiptPart(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class LocalSourceDigest(_FrozenReceiptPart):
    name: Annotated[
        str,
        Field(pattern=r"^supabase/(migrations|review/assistant_workflows)/[a-zA-Z0-9_.-]+\.sql$"),
    ]
    digest: Sha256


class LocalImageDigest(_FrozenReceiptPart):
    name: Literal["db", "auth", "rest", "storage", "gateway"]
    digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class LocalSupabaseTargetReceipt(_FrozenReceiptPart):
    project_id: Literal["medithread-assistant-qa"]
    instance_nonce: UUID
    api_url: Literal["http://127.0.0.1:55438"]
    database_host: Literal["127.0.0.1"]
    database_port: Annotated[int, Field(ge=55439, le=55439)]
    database_name: Literal["postgres"]
    config_hash: Sha256
    cli_version: Literal["3.0.0"]
    cli_hash: Literal[CLI_HASH]
    image_digests: tuple[LocalImageDigest, ...]
    candidate_hashes: Annotated[tuple[LocalSourceDigest, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def complete_unique_identity(self) -> Self:
        images = [item.name for item in self.image_digests]
        sources = [item.name for item in self.candidate_hashes]
        if (
            self.instance_nonce.int == 0
            or len(images) != 5
            or set(images) != {"db", "auth", "rest", "storage", "gateway"}
            or len(sources) != len(set(sources))
        ):
            raise ValueError("Incomplete or ambiguous local target receipt")
        return self


def validate_receipt_binding(
    receipt: LocalSupabaseTargetReceipt,
    *,
    config_hash: str,
    cli_hash: str,
    candidate_hashes: Mapping[str, str],
) -> None:
    """Bind to independently measured bytes; callers still need online admission."""
    if (
        receipt.config_hash != config_hash
        or receipt.cli_hash != cli_hash
        or {entry.name: entry.digest for entry in receipt.candidate_hashes} != dict(candidate_hashes)
    ):
        raise ValueError("Local target receipt does not match current artifacts")


def validate_local_sql_dsn(dsn: str, *, verifier: bool) -> None:
    """Exact local address and identity only; no connection or ambient libpq fallback."""
    try:
        parsed = urlsplit(dsn)
        users = {"assistant_evidence_login"} if verifier else {"postgres", "pharmascan_patient"}
        if (
            parsed.scheme not in {"postgres", "postgresql"}
            or parsed.netloc.rsplit("@", 1)[-1] != "127.0.0.1:55439"
            or parsed.path != "/postgres"
            or parsed.fragment
            or parsed.query not in ({"", "sslmode=disable"} if verifier else {""})
            or unquote(parsed.username or "") not in users
            or not parsed.password
        ):
            raise ValueError
    except (ValueError, TypeError, AttributeError, UnicodeError):
        raise ValueError("Explicit local SQL target and expected identity required") from None


def read_bound_local_receipt(profile) -> LocalSupabaseTargetReceipt:
    from .persistent_workflow_live_support import ROOT, candidate_hashes

    work = ROOT / "internal/acceptance/local-supabase"
    path = Path(profile.local_receipt_path)
    if path.resolve() != (work / "target-receipt.json").resolve() or path.stat().st_size > 65536:
        raise ValueError("Explicit private local receipt required")
    receipt = LocalSupabaseTargetReceipt.model_validate_json(path.read_bytes())
    with Path("D:/DevTools/Supabase/3.0.0/supabase.exe").open("rb") as cli:
        cli_hash = hashlib.file_digest(cli, "sha256").hexdigest()
    validate_receipt_binding(
        receipt,
        config_hash=hashlib.sha256((work / "supabase/config.toml").read_bytes()).hexdigest(),
        cli_hash=cli_hash,
        candidate_hashes=candidate_hashes(),
    )
    ownership = json.loads((work / "runtime-owner.json").read_bytes())
    if ownership["instance_nonce"] != str(receipt.instance_nonce) or ownership["project_id"] != receipt.project_id:
        raise ValueError("Receipt is not bound to the owned local environment")
    return receipt


def validate_local_profile(profile):
    """Structural admission only. Live consumers must verify runtime and identity pairing."""
    from .persistent_workflow_live_support import ApprovedTestTarget, candidate_hashes, validate_patient_claims

    validate_local_sql_dsn(profile.database_url, verifier=False)
    validate_local_sql_dsn(profile.evidence_dsn, verifier=True)
    owners = UUID(profile.owner_a), UUID(profile.owner_b)
    if owners[0] == owners[1] or any(owner.int == 0 for owner in owners):
        raise ValueError("Distinct synthetic owners required")
    values = profile.storage_values
    if (
        values["ASSISTANT_TEST_SUPABASE_URL"] != "http://127.0.0.1:55438"
        or values["ASSISTANT_TEST_PROJECT_REF"] != "medithread-assistant-qa"
        or values["ASSISTANT_TEST_SUPABASE_DATABASE_URL"] != profile.database_url
    ):
        raise ValueError("Local HTTP and SQL endpoints must be explicit")
    key = values["ASSISTANT_TEST_PUBLISHABLE_KEY"]
    if not key.startswith("sb_publishable_"):
        parts = key.split(".")
        if len(parts) != 3 or len(key) > 16384:
            raise ValueError("Patient publishable key required")
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        if claims.get("role") != "anon":
            raise ValueError("Administrator API key is forbidden")
    validate_patient_claims(profile, owners)
    hashes = candidate_hashes()
    if dict(profile.approved_candidate_hashes) != hashes:
        raise ValueError("Current explicit source approval required")
    receipt = read_bound_local_receipt(profile)
    if {item.name: item.digest for item in receipt.candidate_hashes} != hashes:
        raise ValueError("Receipt source inventory drift")
    fingerprint = hashlib.sha256(f"127.0.0.1:55439/postgres:{receipt.instance_nonce}".encode()).hexdigest()
    return ApprovedTestTarget(fingerprint, *owners, hashes)


SERVICE_PREFIXES = {"db": "db", "auth": "auth", "rest": "rest", "storage": "storage", "gateway": "kong"}
DOCKER_COMMAND = [
    "D:/DevTools/DockerDesktop/resources/bin/docker.exe",
    "--host",
    "npipe:////./pipe/dockerDesktopLinuxEngine",
]


def validate_runtime_snapshot(receipt, ownership, network, containers) -> None:
    """Reject a same-name foreign stack, drifted images or any public port binding."""
    try:
        if (
            network["Id"] != ownership["network_id"]
            or network["Name"] != ownership["network_name"]
            or network["Driver"] != "bridge"
            or network["Labels"]["com.medithread.acceptance.project"] != receipt.project_id
            or network["Labels"]["com.medithread.acceptance.instance"] != str(receipt.instance_nonce)
            or network["Options"]["com.docker.network.bridge.host_binding_ipv4"] != "127.0.0.1"
            or set(containers) != set(SERVICE_PREFIXES)
            or len({c["Id"] for c in containers.values()}) != 5
        ):
            raise ValueError
        images = {item.name: item.digest for item in receipt.image_digests}
        for service, container in containers.items():
            networks = container["NetworkSettings"]["Networks"]
            ports = {
                (port, bind["HostIp"], bind["HostPort"])
                for port, bindings in container["NetworkSettings"]["Ports"].items()
                for bind in bindings or []
            }
            expected = (
                {("5432/tcp", "127.0.0.1", "55439")}
                if service == "db"
                else {("8000/tcp", "127.0.0.1", "55438")}
                if service == "gateway"
                else set()
            )
            if (
                container["Name"] != f"/supabase_{SERVICE_PREFIXES[service]}_{receipt.project_id}"
                or ("container_ids" in ownership and ownership["container_ids"].get(service) != container["Id"])
                or container["Image"] != images[service]
                or container["Image"] != ownership["image_pins"][service]["config_digest"]
                or container["Config"]["Labels"]["com.supabase.cli.project"] != receipt.project_id
                or container["State"]["Running"] is not True
                or container["State"].get("Health", {}).get("Status", "healthy") != "healthy"
                or set(networks) != {ownership["network_name"]}
                or networks[ownership["network_name"]]["NetworkID"] != ownership["network_id"]
                or ports != expected
            ):
                raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ValueError("Local runtime ownership, images or loopback binding mismatch") from None


def verify_auth_data_pairing(profile, target, rows, *, http) -> None:
    """GET only: actual Auth identity plus independently read SQL/Data API markers."""
    by_owner = {row[0]: row for row in rows}
    owners = (str(target.owner_a), str(target.owner_b))
    if len(rows) != 2 or set(by_owner) != set(owners):
        raise ValueError("Distinct SQL DEMO marker rows required")
    values = profile.storage_values
    for owner, key in zip(owners, ("ASSISTANT_TEST_JWT_A", "ASSISTANT_TEST_JWT_B"), strict=True):
        headers = {"apikey": values["ASSISTANT_TEST_PUBLISHABLE_KEY"], "Authorization": "Bearer " + values[key]}
        auth = http.get("http://127.0.0.1:55438/auth/v1/user", headers=headers)
        if auth.status_code != 200 or auth.json().get("id") != owner or auth.json().get("role") != "authenticated":
            raise ValueError("Local Auth identity mismatch")
        response = http.get(
            "http://127.0.0.1:55438/rest/v1/medithread_local_acceptance",
            params={"select": "owner,instance_nonce,challenge,demo_only", "owner": "eq." + owner},
            headers=headers,
        )
        row = by_owner[owner]
        expected = [{"owner": owner, "instance_nonce": row[1], "challenge": row[2], "demo_only": True}]
        if response.status_code != 200 or response.json() != expected:
            raise ValueError("Local SQL/Data API dataset pairing failed")


def inspect_owned_runtime(receipt):
    from .persistent_workflow_live_support import ROOT

    ownership = json.loads((ROOT / "internal/acceptance/local-supabase/runtime-owner.json").read_bytes())

    def inspect(kind, name):
        reply = subprocess.run(DOCKER_COMMAND + [kind, "inspect", name], capture_output=True, check=True, timeout=20)
        return json.loads(reply.stdout)[0]

    network = inspect("network", ownership["network_id"])
    containers = {
        service: inspect("container", f"supabase_{prefix}_{receipt.project_id}")
        for service, prefix in SERVICE_PREFIXES.items()
    }
    validate_runtime_snapshot(receipt, ownership, network, containers)


def verify_local_live_target(profile, target):
    """Recheck ownership and GET-only Auth/SQL pairing before any live test writes."""
    import httpx
    import psycopg

    from .persistent_workflow_live_support import (
        PersistentProfileRefusal,
        sql_connection_parameters,
        validate_persistent_test_profile,
    )

    try:
        if validate_persistent_test_profile(profile, purpose="sql_read", require_hashes=True) != target:
            raise ValueError
        receipt = read_bound_local_receipt(profile)
        inspect_owned_runtime(receipt)
        with psycopg.connect(**sql_connection_parameters(profile, verifier=False, read_only=True)) as connection:
            if connection.execute("SELECT current_database()").fetchone()[0] != "postgres":
                raise ValueError
            rows = connection.execute(
                "SELECT owner::text,instance_nonce::text,challenge::text FROM public.medithread_local_acceptance "
                "WHERE demo_only AND owner=ANY(%s) ORDER BY owner",
                ([target.owner_a, target.owner_b],),
            ).fetchall()
        if any(row[1] != str(receipt.instance_nonce) for row in rows):
            raise ValueError
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
            verify_auth_data_pairing(profile, target, rows, http=client)
    except Exception:
        raise PersistentProfileRefusal() from None
