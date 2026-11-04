"""Offline synthetic evaluation only. Reports contain grades/versions, not patient text."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Explicit local imports; no dotenv loader, model SDK or hosted configuration.
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from tests.backend.assistant_eval import build_report, load_suite  # noqa: E402
from tests.backend.assistant_eval_runtime import run_case  # noqa: E402

ARTIFACTS = ROOT / "outputs/assistant-acceptance"


def private_output(value: str) -> Path:
    output = Path(value)
    output = (ROOT / output).resolve() if not output.is_absolute() else output.resolve()
    if (
        not ARTIFACTS.resolve().is_relative_to(ROOT.resolve())
        or not output.is_relative_to(ARTIFACTS.resolve())
        or output.suffix != ".json"
    ):
        raise ValueError("Evaluation output must be a private acceptance JSON artifact")
    return output


def digest(paths):
    result = hashlib.sha256()
    for path in sorted(paths):
        result.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        result.update(hashlib.sha256(path.read_bytes()).digest())
    return result.hexdigest()


def git_read(*args):
    result = subprocess.run(
        ["git", "-C", str(ROOT), "-c", f"safe.directory={ROOT.as_posix()}", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def metadata(suite):
    code = [
        *ROOT.joinpath("backend/app").rglob("*.py"),
        ROOT / "tests/backend/assistant_eval.py",
        ROOT / "tests/backend/assistant_eval_runtime.py",
        Path(__file__).resolve(),
    ]
    fixtures = [
        ROOT / "tests/backend/workflow_support.py",
        ROOT / "tests/backend/conftest.py",
        ROOT / "tests/backend/test_workflow_originals.py",
        ROOT / "tests/backend/fixtures/ibuprofen_labels_public.json",
        ROOT / "tests/fixtures/assistant/capability_coverage.json",
    ]
    return {
        "evaluator_version": "1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "code_revision": git_read("rev-parse", "HEAD"),
        "code_dirty": bool(git_read("status", "--porcelain")),
        "code_sha256": digest(code),
        "design_sha256": digest([ROOT / "internal/docs/ASSISTANT_WORKFLOWS_DESIGN_20261025.md"]),
        "suite_version": suite.version,
        "case_sha256": digest([ROOT / "tests/fixtures/assistant/acceptance_cases.json"]),
        "fixture_version": suite.fixture_version,
        "fixture_sha256": digest(fixtures),
        "mode": "offline",
        "environment": "local_memory",
        "provider": None,
        "configured_model": None,
        "returned_model": None,
        "scope": "Fresh stage-scoped synthetic cases; prior P06 evidence is not imported as new observations.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("offline",), default="offline")
    parser.add_argument("--output", default="outputs/assistant-acceptance/offline.json")
    args = parser.parse_args(argv)
    try:
        output = private_output(args.output)
        suite = load_suite()
        versions = metadata(suite)
        manifest = json.loads((ROOT / "tests/fixtures/assistant/capability_coverage.json").read_text(encoding="utf-8"))
        required_phases = {
            row["capability_id"]: {case["phase"] for case in row["acceptance_cases"]}
            for row in manifest["capabilities"]
        }
        observations = [run_case(case) for case in suite.cases]
        report = build_report(
            suite.cases,
            observations,
            required_capabilities=suite.required_capabilities,
            required_phases=required_phases,
        )
        artifact = {"schema_version": 1, "metadata": versions, "report": report.model_dump(mode="json")}
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".json", prefix=".eval-", dir=output.parent, delete=False
            ) as handle:
                temporary = Path(handle.name)
                json.dump(artifact, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.write("\n")
            temporary.replace(output)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        print(
            json.dumps(
                {
                    "status": report.status,
                    "counts": report.counts,
                    "missing_capabilities": report.missing_capabilities,
                    "missing_cases": report.missing_cases,
                    "capabilities_with_unrun_phases": len(report.phase_gaps),
                    "artifact": output.relative_to(ROOT).as_posix(),
                }
            )
        )
        return report.exit_code
    except Exception as error:
        # Exception messages may contain request bodies or credentials. Preserve
        # only the safe exception class and a nonzero result, never a success.
        print("evaluation_failed:" + type(error).__name__.lower(), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
