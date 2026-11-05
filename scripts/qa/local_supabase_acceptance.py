"""Explicit local DEMO acceptance. Default check never starts services or writes SQL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from uuid import UUID, uuid4, uuid5

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from tests.backend.local_supabase_live_support import (  # noqa: E402
    CLI_HASH,
    DOCKER_COMMAND,
    SERVICE_PREFIXES,
    LocalSupabaseTargetReceipt,
    inspect_owned_runtime,
    validate_local_sql_dsn,
    validate_runtime_snapshot,
)
from tests.backend.persistent_workflow_live_support import (  # noqa: E402
    PersistentWorkflowTestProfile,
    candidate_hashes,
    validate_persistent_test_profile,
)

WORKDIR = ROOT / "internal/acceptance/local-supabase"
CLI = Path("D:/DevTools/Supabase/3.0.0/supabase.exe")
PROFILE = "profile.json"
PROFILE_KEYS = frozenset(
    {
        "RUN_ASSISTANT_PERSISTENCE_TESTS",
        "RUN_ASSISTANT_SQL_TESTS",
        "RUN_ASSISTANT_STORAGE_TESTS",
        "ASSISTANT_PERSISTENCE_APPROVED",
        "ASSISTANT_PERSISTENCE_APPROVAL_ID",
        "ASSISTANT_PERSISTENCE_OPERATIONS",
        "ASSISTANT_TEST_TARGET_MODE",
        "ASSISTANT_TEST_LOCAL_RECEIPT_PATH",
        "ASSISTANT_TEST_DATABASE_URL",
        "ASSISTANT_TEST_EVIDENCE_DSN",
        "ASSISTANT_TEST_SUPABASE_DATABASE_URL",
        "ASSISTANT_TEST_SUPABASE_URL",
        "ASSISTANT_TEST_PROJECT_REF",
        "ASSISTANT_TEST_PUBLISHABLE_KEY",
        "ASSISTANT_TEST_CANDIDATE_HASHES",
        "ASSISTANT_TEST_OWNER_A",
        "ASSISTANT_TEST_OWNER_B",
        "ASSISTANT_TEST_JWT_A",
        "ASSISTANT_TEST_JWT_B",
        "ASSISTANT_TEST_NATIVE_MEDICATION_A",
    }
)


def private_json(path: Path, value, *, replace=False):
    with path.open("w" if replace else "x", encoding="utf-8") as output:
        json.dump(value, output, indent=2)
        output.write("\n")


def local_environment():
    """Do not inherit hosted credentials, provider keys or application .env state."""
    names = {"SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"}
    env = {k: v for k, v in os.environ.items() if k.upper() in {name.upper() for name in names}}
    env.update(
        PATH=str(Path(DOCKER_COMMAND[0]).parent)
        + os.pathsep
        + str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32"),
        DOCKER_HOST=DOCKER_COMMAND[2],
        SUPABASE_HOME="D:/DevTools/Supabase/home",
        SUPABASE_TELEMETRY_DISABLED="1",
        DO_NOT_TRACK="1",
        PYTHONIOENCODING="utf-8",
        PYTHONPATH=str(ROOT / "backend"),
        NO_PROXY="127.0.0.1,localhost",
    )
    return env


def invoke(args, *, timeout=60):
    result = subprocess.run(args, capture_output=True, timeout=timeout, env=local_environment())
    if result.returncode:
        raise ValueError("Local command failed; inspect owned service state before retrying")
    return result.stdout


def docker_inspect(kind, name):
    return json.loads(invoke(DOCKER_COMMAND + [kind, "inspect", name]))[0]


def owned_configuration():
    """Verify executable/configuration bytes before invoking any Supabase command."""
    ownership = json.loads((WORKDIR / "runtime-owner.json").read_bytes())
    config_hash = hashlib.sha256((WORKDIR / "supabase/config.toml").read_bytes()).hexdigest()
    with CLI.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != CLI_HASH:
            raise ValueError("Pinned CLI changed")
    if ownership["project_id"] != "medithread-assistant-qa" or ownership["config_hash"] != config_hash:
        raise ValueError("Owned project configuration changed")
    pins = (WORKDIR / "image-pins.json").read_bytes()
    if (
        hashlib.sha256(pins).hexdigest() != ownership["image_pins_hash"]
        or json.loads(pins) != ownership["image_pins"]
    ):
        raise ValueError("Independent official image pins changed")
    return ownership, config_hash


def verified_receipt():
    """Capture content IDs once; existing receipt must keep matching current artifacts."""
    ownership, config_hash = owned_configuration()
    project = ownership["project_id"]
    containers = {
        service: docker_inspect("container", f"supabase_{prefix}_{project}")
        for service, prefix in SERVICE_PREFIXES.items()
    }
    data = dict(
        project_id=project,
        instance_nonce=ownership["instance_nonce"],
        api_url="http://127.0.0.1:55438",
        database_host="127.0.0.1",
        database_port=55439,
        database_name="postgres",
        config_hash=config_hash,
        cli_version="3.0.0",
        cli_hash=CLI_HASH,
        image_digests=[{"name": name, "digest": container["Image"]} for name, container in containers.items()],
        candidate_hashes=[{"name": name, "digest": digest} for name, digest in candidate_hashes().items()],
    )
    receipt = LocalSupabaseTargetReceipt.model_validate_json(json.dumps(data))
    network = docker_inspect("network", ownership["network_id"])
    validate_runtime_snapshot(receipt, ownership, network, containers)
    path = WORKDIR / "target-receipt.json"
    if "container_ids" not in ownership:
        if path.exists():
            raise ValueError("Existing receipt has no owned container identity")
        ownership["container_ids"] = {name: container["Id"] for name, container in containers.items()}
        private_json(WORKDIR / "runtime-owner.json", ownership, replace=True)
    if path.exists():
        if LocalSupabaseTargetReceipt.model_validate_json(path.read_bytes()) != receipt:
            raise ValueError("Existing local receipt drift; refusing replacement")
    else:
        private_json(path, receipt.model_dump(mode="json"))
    return receipt, containers


def source_plan():
    """Freeze raw bytes and separately retain the migration runner's canonical hash."""
    from app.infrastructure.postgres_migrations import MigrationFile

    inventory = json.loads((WORKDIR / "source-inventory.json").read_bytes())
    if inventory["project_id"] != "medithread-assistant-qa" or inventory["down_execution_authorized"]:
        raise ValueError("Local source inventory is not admitted")
    hashes = inventory["source_hashes"]
    for relative, digest in hashes.items():
        path = ROOT / relative
        if not path.resolve().is_relative_to((ROOT / "supabase").resolve()):
            raise ValueError("Source path escaped Supabase inventory")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Local source bytes changed")
    result = []
    for index, relative in enumerate(inventory["planned_apply_order"]):
        if relative not in hashes or relative.endswith(".down.sql"):
            raise ValueError("Unapproved source in local apply plan")
        path = ROOT / relative
        sql = path.read_text(encoding="utf-8")
        version = path.stem.partition("_")[0] if "/migrations/" in relative else f"local_assistant_{index:02d}"
        result.append(MigrationFile(version, path.stem, path, sql, hashlib.sha256(sql.encode()).hexdigest()))
    if len(result) != 50 or len({item.version for item in result}) != 50:
        raise ValueError("Complete distinct local source plan required")
    return result


def bootstrap(approval_id):
    import httpx
    import psycopg
    from app.infrastructure.postgres_migrations import (
        applied_migrations,
        apply_recorded_migration,
        ensure_ledger,
        existing_core_tables,
    )
    from psycopg import sql
    from psycopg.rows import dict_row

    plan = source_plan()  # All source checks precede network/SQL I/O.
    receipt, _ = verified_receipt()
    if (WORKDIR / PROFILE).exists():
        raise ValueError("Local bootstrap profile already exists; use check/accept, never reseed")
    status = json.loads(invoke([str(CLI), "status", "--workdir", str(WORKDIR), "--output", "json"]))
    database_url = status["DB_URL"]
    validate_local_sql_dsn(database_url, verifier=False)
    if status["API_URL"] != receipt.api_url:
        raise ValueError("CLI status endpoint mismatch")
    secret_path = WORKDIR / "bootstrap-secrets.json"
    if secret_path.exists():
        private = json.loads(secret_path.read_bytes())
        if private["instance_nonce"] != str(receipt.instance_nonce):
            raise ValueError("Bootstrap state belongs to another instance")
    else:
        private = {
            "instance_nonce": str(receipt.instance_nonce),
            "verifier_password": secrets.token_urlsafe(32),
            "password_a": secrets.token_urlsafe(32),
            "password_b": secrets.token_urlsafe(32),
            "owner_a": None,
            "owner_b": None,
        }
        private_json(secret_path, private)
    parsed = urlsplit(database_url)
    with psycopg.connect(
        host="127.0.0.1",
        hostaddr="127.0.0.1",
        port=55439,
        dbname="postgres",
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        service="",
        passfile="",
        sslmode="disable",
        autocommit=True,
        connect_timeout=5,
        row_factory=dict_row,
        options="-c statement_timeout=30000 -c lock_timeout=3000",
    ) as connection:
        recorded = applied_migrations(connection)
        if not recorded and existing_core_tables(connection):
            raise ValueError("Existing unowned application schema; refusing bootstrap")
        if set(recorded) - {item.version for item in plan}:
            raise ValueError("Unknown migration history on local target")
        ensure_ledger(connection)
        for index, migration in enumerate(plan):
            apply_recorded_migration(connection, migration, prerequisites=tuple(plan[:index]))
        observed = applied_migrations(connection)
        if observed != {item.version: item.sha256 for item in plan}:
            raise ValueError("Applied local ledger differs from reviewed sources")
        connection.execute(
            sql.SQL("ALTER ROLE assistant_evidence_login PASSWORD {}").format(sql.Literal(private["verifier_password"]))
        )
        connection.execute("GRANT CONNECT ON DATABASE postgres TO assistant_evidence_login")
        with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as http:
            headers = {"apikey": status["ANON_KEY"], "Authorization": "Bearer " + status["SERVICE_ROLE_KEY"]}
            for suffix in ("a", "b"):
                if private["owner_" + suffix] is None:
                    reply = http.post(
                        receipt.api_url + "/auth/v1/admin/users",
                        headers=headers,
                        json={
                            "email": f"medithread-demo-{receipt.instance_nonce}-{suffix}@example.invalid",
                            "password": private["password_" + suffix],
                            "email_confirm": True,
                            "user_metadata": {"demo_only": True},
                        },
                    )
                    if reply.status_code not in {200, 201}:
                        raise ValueError("Local DEMO user provisioning refused; preserve bootstrap state")
                    private["owner_" + suffix] = str(UUID(reply.json()["id"]))
                    private_json(secret_path, private, replace=True)
                connection.execute(
                    "INSERT INTO public.patient_profiles(user_id,display_name,timezone,language,demo_only) "
                    "VALUES(%s,%s,'Asia/Singapore','en',true) ON CONFLICT(user_id) DO NOTHING",
                    (private["owner_" + suffix], "DEMO ONLY " + suffix.upper()),
                )
            # One explicitly synthetic, unscheduled medication supports native photo/PDF tests.
            # No dosing, historical ingestion or clinical instructions are invented.
            native_medication = uuid5(receipt.instance_nonce, "native-medication-a")
            connection.execute(
                "INSERT INTO public.patient_medications(id,patient_id,display_name,demo_only) "
                "VALUES(%s,%s,'DEMO ONLY native media fixture',true) ON CONFLICT(id) DO NOTHING",
                (native_medication, private["owner_a"]),
            )
            owned = connection.execute(
                "SELECT patient_id::text,demo_only FROM public.patient_medications WHERE id=%s",
                (native_medication,),
            ).fetchone()
            if owned != {"patient_id": private["owner_a"], "demo_only": True}:
                raise ValueError("Native DEMO fixture ownership mismatch")
            connection.execute("""CREATE TABLE IF NOT EXISTS public.medithread_local_acceptance(
                owner uuid PRIMARY KEY REFERENCES public.patient_profiles(user_id),
                instance_nonce uuid NOT NULL,challenge uuid NOT NULL DEFAULT gen_random_uuid(),
                demo_only boolean NOT NULL DEFAULT true CHECK(demo_only));
                ALTER TABLE public.medithread_local_acceptance ENABLE ROW LEVEL SECURITY;
                ALTER TABLE public.medithread_local_acceptance FORCE ROW LEVEL SECURITY;
                REVOKE ALL ON public.medithread_local_acceptance FROM PUBLIC,anon,authenticated;
                GRANT SELECT ON public.medithread_local_acceptance TO authenticated;""")
            policy = connection.execute(
                "SELECT 1 FROM pg_policies WHERE schemaname='public' "
                "AND tablename='medithread_local_acceptance' AND policyname='demo_marker_owner'"
            ).fetchone()
            if policy is None:
                connection.execute(
                    "CREATE POLICY demo_marker_owner ON public.medithread_local_acceptance "
                    "FOR SELECT TO authenticated USING(owner=auth.uid())"
                )
            for suffix in ("a", "b"):
                connection.execute(
                    "INSERT INTO public.medithread_local_acceptance(owner,instance_nonce) "
                    "VALUES(%s,%s) ON CONFLICT(owner) DO NOTHING",
                    (private["owner_" + suffix], receipt.instance_nonce),
                )
            profile = {
                "RUN_ASSISTANT_PERSISTENCE_TESTS": "1",
                "RUN_ASSISTANT_SQL_TESTS": "1",
                "RUN_ASSISTANT_STORAGE_TESTS": "1",
                "ASSISTANT_PERSISTENCE_APPROVED": "1",
                "ASSISTANT_PERSISTENCE_APPROVAL_ID": approval_id,
                "ASSISTANT_PERSISTENCE_OPERATIONS": "sql_read,sql_write,storage_read,storage_write",
                "ASSISTANT_TEST_TARGET_MODE": "local_supabase",
                "ASSISTANT_TEST_LOCAL_RECEIPT_PATH": str(WORKDIR / "target-receipt.json"),
                "ASSISTANT_TEST_DATABASE_URL": database_url,
                "ASSISTANT_TEST_EVIDENCE_DSN": "postgresql://assistant_evidence_login:"
                + quote(private["verifier_password"], safe="")
                + "@127.0.0.1:55439/postgres",
                "ASSISTANT_TEST_SUPABASE_DATABASE_URL": database_url,
                "ASSISTANT_TEST_SUPABASE_URL": receipt.api_url,
                "ASSISTANT_TEST_PROJECT_REF": receipt.project_id,
                "ASSISTANT_TEST_PUBLISHABLE_KEY": status["ANON_KEY"],
                "ASSISTANT_TEST_CANDIDATE_HASHES": json.dumps(candidate_hashes()),
                "ASSISTANT_TEST_NATIVE_MEDICATION_A": str(native_medication),
            }
            for suffix in ("a", "b"):
                response = http.post(
                    receipt.api_url + "/auth/v1/token?grant_type=password",
                    headers={"apikey": status["ANON_KEY"]},
                    json={
                        "email": f"medithread-demo-{receipt.instance_nonce}-{suffix}@example.invalid",
                        "password": private["password_" + suffix],
                    },
                )
                if response.status_code != 200:
                    raise ValueError("Local patient login failed")
                profile["ASSISTANT_TEST_OWNER_" + suffix.upper()] = private["owner_" + suffix]
                profile["ASSISTANT_TEST_JWT_" + suffix.upper()] = response.json()["access_token"]
    private_json(WORKDIR / PROFILE, profile)
    return {"status": "BOOTSTRAPPED", "real_acceptance": "NOT_RUN"}


def load_profile(approval_id):
    values = json.loads((WORKDIR / PROFILE).read_bytes())
    if set(values) - PROFILE_KEYS or values.get("ASSISTANT_PERSISTENCE_APPROVAL_ID") != approval_id:
        raise ValueError("Unapproved child environment or approval mismatch")
    profile = PersistentWorkflowTestProfile.from_values(values)
    if profile.target_mode != "local_supabase":
        raise ValueError("Explicit local mode required")
    validate_persistent_test_profile(profile, purpose="sql_write", require_hashes=True)
    validate_persistent_test_profile(profile, purpose="storage_write", require_hashes=True)
    return values, profile


def serve(profile):
    """Reuse the ordinary launcher process ownership; do not load its .env settings."""
    from scripts.start_dev import check_port, start_process, stop_process
    from tests.backend.local_supabase_live_support import verify_local_live_target

    target = validate_persistent_test_profile(profile, purpose="sql_read", require_hashes=True)
    verify_local_live_target(profile, target)
    node, npm = shutil.which("node"), shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not node or not npm or not (ROOT / "frontend/node_modules/.bin/vite").exists():
        raise ValueError("Existing frontend tools/dependencies required; never install implicitly")
    for port in (8027, 5195):
        check_port(port)
    env = local_environment() | {"MEDITHREAD_LOCAL_ACCEPTANCE": "1"}
    env["PATH"] = str(Path(node).parent) + os.pathsep + env["PATH"]
    front = env | {
        "VITE_API_TARGET": "http://127.0.0.1:8027",
        "VITE_SUPABASE_URL": profile.storage_values["ASSISTANT_TEST_SUPABASE_URL"],
        "VITE_SUPABASE_PUBLISHABLE_KEY": profile.storage_values["ASSISTANT_TEST_PUBLISHABLE_KEY"],
    }
    backend = [
        sys.executable,
        "-m",
        "uvicorn",
        "tests.backend.local_supabase_runtime:create_app",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        "8027",
        "--no-access-log",
    ]
    frontend = [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", "5195", "--strictPort"]
    processes = []
    try:
        for command, cwd, child_env in ((backend, ROOT, env), (frontend, ROOT / "frontend", front)):
            processes.append(start_process(command, cwd, child_env))
        print(
            "Local DEMO: http://127.0.0.1:5195 (real local services; public knowledge replay). Ctrl+C stops both.",
            flush=True,
        )
        while all(process.poll() is None for process in processes):
            time.sleep(0.25)
        raise ValueError("A local development server exited; both servers stopped")
    except KeyboardInterrupt:
        return {"status": "APP_STOPPED", "volumes": "PRESERVED"}
    finally:
        for process in reversed(processes):
            stop_process(process)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage", nargs="?", choices=("check", "start", "bootstrap", "accept", "serve", "stop"), default="check"
    )
    parser.add_argument("--approval-id", default="")
    args = parser.parse_args(argv)
    result = {"status": "NOT_READY", "real_services": "NOT_CHECKED"}
    code = 2
    acceptance_log = None
    try:
        if args.stage != "check" and not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", args.approval_id):
            result["reason"] = "explicit_local_approval_required"
        elif args.stage == "check":
            if (WORKDIR / PROFILE).exists():
                profile = PersistentWorkflowTestProfile.from_values(json.loads((WORKDIR / PROFILE).read_bytes()))
                validate_persistent_test_profile(profile, require_hashes=True)
                result["status"], code = "PROFILE_BOUND", 0
        elif args.stage == "start":
            ownership, _ = owned_configuration()
            source_plan()
            network = docker_inspect("network", ownership["network_id"])
            if network["Labels"]["com.medithread.acceptance.instance"] != ownership["instance_nonce"]:
                raise ValueError("Foreign runtime")
            invoke(
                [
                    str(CLI),
                    "start",
                    "--workdir",
                    str(WORKDIR),
                    "--network-id",
                    ownership["network_name"],
                    "--exclude",
                    "realtime,imgproxy,mailpit,postgres-meta,studio,edge-runtime,logflare,vector,supavisor",
                ],
                timeout=3600,
            )
            verified_receipt()
            result, code = {"status": "RUNNING", "real_acceptance": "NOT_RUN"}, 0
        elif args.stage == "bootstrap":
            result, code = bootstrap(args.approval_id), 0
        elif args.stage == "accept":
            profile_values, _ = load_profile(args.approval_id)
            env = local_environment() | profile_values
            run_id = uuid4().hex
            acceptance_log = WORKDIR / f"real-acceptance-{run_id}.log"
            with acceptance_log.open("x", encoding="utf-8") as output:
                reply = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "tests/backend/test_persistent_workflow_sql_live.py",
                        "tests/backend/test_persistent_workflow_storage_live.py",
                        "-q",
                        "--tb=short",
                        "--basetemp=" + str(WORKDIR / ("pytest-real-" + run_id)),
                    ],
                    cwd=ROOT,
                    env=env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    timeout=1800,
                )
            result, code = (
                {
                    "status": "PASS" if reply.returncode == 0 else "FAIL",
                    "layer": "LOCAL_REAL_SERVICES",
                    "evidence": str(acceptance_log),
                },
                reply.returncode,
            )
        elif args.stage == "serve":
            _, profile = load_profile(args.approval_id)
            result, code = serve(profile), 0
        elif args.stage == "stop":
            receipt, containers = verified_receipt()
            inspect_owned_runtime(receipt)
            invoke(
                DOCKER_COMMAND
                + ["stop", *[containers[name]["Id"] for name in ("gateway", "storage", "rest", "auth", "db")]],
                timeout=90,
            )
            result, code = {"status": "STOPPED", "volumes": "PRESERVED"}, 0
    except Exception:
        result = {
            "status": "REFUSED",
            "reason": "local_target_or_operation_unavailable",
            "real_acceptance": "INTERRUPTED" if acceptance_log else "NOT_RUN",
        }
        if acceptance_log:
            result["evidence"] = str(acceptance_log)
    print(json.dumps(result))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
