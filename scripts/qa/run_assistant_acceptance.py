"""Default-offline bounded synthetic acceptance; never loads a project .env."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.application.agent_runtime_metadata import runtime_hash, source_revision  # noqa: E402

from scripts.qa.eval_assistant import private_output  # noqa: E402
from tests.backend.assistant_acceptance import RunnerBudget, RunnerConfig, run_acceptance  # noqa: E402


def metadata(config):
    digest = hashlib.sha256()
    # Conservative source manifest: include executable helpers/graders and every
    # controlled fixture/resource, including transitive test support imports.
    paths = set()
    for relative in ("tests/backend", "scripts/qa"):
        paths.update((ROOT / relative).rglob("*.py"))
    for relative in ("tests/backend/fixtures", "tests/fixtures/assistant", "backend/app/resources"):
        paths.update(path for path in (ROOT / relative).rglob("*") if path.is_file())
    for relative in ("tests/__init__.py", "scripts/__init__.py"):
        if (ROOT / relative).is_file():
            paths.add(ROOT / relative)
    for path in sorted(paths):
        name = path.relative_to(ROOT).as_posix()
        digest.update(name.encode())
        digest.update(path.read_bytes())
    return {
        "runner_version": "1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_revision": source_revision(),
        "application_hash": runtime_hash(),
        "runner_fixture_hash": digest.hexdigest(),
        "provenance_files": [path.relative_to(ROOT).as_posix() for path in sorted(paths)],
        "mode": config.mode,
        "configured_model": config.model,
        "scope": ("Six synthetic scenario categories; evidence layers are separate. Not full application acceptance."),
        "limits": "Wire-attempt cap includes retries. No currency cap. Synchronous I/O stops cooperatively.",
        "isolated_integration": (
            "Requires a separately verified isolated Auth/SQL/Storage profile; currently unavailable."
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("offline", "provider-memory", "isolated-integration"), default="offline")
    parser.add_argument("--max-requests", type=int, default=0)
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--max-seconds", type=int, default=0)
    parser.add_argument("--allow-provider", action="store_true")
    parser.add_argument("--model")
    parser.add_argument("--api-key-env")
    parser.add_argument("--output", default="outputs/assistant-acceptance/acceptance-run.json")
    parser.add_argument(
        "--persistence-preflight", action="store_true", help="Offline target/hash admission only; never runs live tests"
    )
    parser.add_argument("--persistence-profile", type=Path)
    parser.add_argument(
        "--persistence-purpose", choices=("sql_read", "sql_write", "storage_read", "storage_write"), default="sql_read"
    )
    args = parser.parse_args(argv)
    try:
        output = private_output(args.output)
        if args.persistence_preflight:
            return persistence_preflight(args, output)
        if args.persistence_profile is not None or args.persistence_purpose != "sql_read":
            return 2  # A profile cannot bypass the existing runner's isolated-integration refusal.
        config = RunnerConfig(
            mode=args.mode,
            budget=RunnerBudget(max_requests=args.max_requests, max_cases=args.max_cases, max_seconds=args.max_seconds),
            allow_provider=args.allow_provider,
            model=args.model,
            api_key_env=args.api_key_env,
        )
        versions = metadata(config)
        report = run_acceptance(config)
        artifact = {
            "schema_version": 1,
            "metadata": versions,
            "report": report.model_dump(mode="json"),
            "exit_code": report.exit_code,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", prefix=".acceptance-", suffix=".json", dir=output.parent, delete=False
            ) as file:
                temporary = Path(file.name)
                json.dump(artifact, file, ensure_ascii=False, indent=2, allow_nan=False)
                file.write("\n")
            temporary.replace(output)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        print(
            json.dumps(
                {
                    "status": "passed" if report.exit_code == 0 else "partial" if report.exit_code == 2 else "failed",
                    "reason": report.reason,
                    "case_count": len(report.cases),
                    "real_requests": report.real_requests,
                    "wire_attempts": report.wire_attempts,
                    "model_requests": report.model_requests,
                    "model_successes": sum(case.model_success for case in report.cases),
                    "artifact": output.relative_to(ROOT).as_posix(),
                }
            )
        )
        return report.exit_code
    except Exception as error:
        print("acceptance_failed:" + type(error).__name__.lower(), file=sys.stderr)
        return 1


def persistence_preflight(args, output):
    from tests.backend.persistent_workflow_live_support import (
        PersistentProfileRefusal,
        PersistentWorkflowTestProfile,
        candidate_hashes,
        validate_persistent_test_profile,
    )

    artifact = {
        "schema_version": 1,
        "status": "NOT_RUN",
        "reason": "target_not_authorized",
        "real_requests": 0,
        "provider_requests": 0,
        "admitted_offline": False,
        "candidate_hashes": candidate_hashes(),
    }
    mixed = (
        args.mode != "offline"
        or args.allow_provider
        or args.model
        or args.api_key_env
        or args.max_requests
        or args.max_cases
        or args.max_seconds
    )
    try:
        if mixed or args.persistence_profile is None or args.persistence_profile.suffix != ".json":
            raise PersistentProfileRefusal()
        values = json.loads(args.persistence_profile.read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            raise PersistentProfileRefusal()
        profile = PersistentWorkflowTestProfile.from_values(values)
        target = validate_persistent_test_profile(profile, purpose=args.persistence_purpose, require_hashes=True)
        artifact.update(admitted_offline=True, reason="preflight_only", target_fingerprint=target.database_fingerprint)
    except (PersistentProfileRefusal, OSError, ValueError, TypeError):
        pass
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: artifact[k] for k in ("status", "reason", "real_requests", "provider_requests")}))
    return 2  # Offline admission can never report real acceptance success.


if __name__ == "__main__":
    raise SystemExit(main())
