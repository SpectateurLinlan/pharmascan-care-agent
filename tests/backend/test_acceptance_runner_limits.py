"""Offline guard tests. No live credentials, provider, Auth or database access."""

from importlib.util import find_spec
from uuid import uuid4

import pytest


def test_guarded_acceptance_runner_exists():
    assert find_spec("tests.backend.assistant_acceptance"), "Guarded acceptance runner is missing"


@pytest.mark.parametrize(
    "relative",
    [
        "tests/backend/assistant_eval.py",
        "tests/backend/assistant_eval_runtime.py",
        "tests/backend/workflow_support.py",
        "tests/backend/test_workflow_originals.py",
        "tests/backend/conftest.py",
        "tests/backend/fixtures/ibuprofen_labels_public.json",
        "scripts/qa/eval_assistant.py",
    ],
)
def test_acceptance_provenance_changes_with_actual_grader_and_fixture_dependencies(monkeypatch, relative):
    from pathlib import Path

    from scripts.qa import run_assistant_acceptance as cli

    from .assistant_acceptance import RunnerConfig

    original = Path.read_bytes
    before = cli.metadata(RunnerConfig())["runner_fixture_hash"]
    changed = (cli.ROOT / relative).resolve()

    def read(path):
        data = original(path)
        return data + b"\nDEMO_PROVENANCE_CHANGE" if path.resolve() == changed else data

    monkeypatch.setattr(Path, "read_bytes", read)
    after = cli.metadata(RunnerConfig())["runner_fixture_hash"]
    assert after != before, f"Untracked executed dependency: {relative}"


@pytest.fixture
def api():
    from . import assistant_acceptance

    return assistant_acceptance


def test_default_configuration_does_no_work_and_keeps_all_missing_cases(api):
    calls = []
    report = api.run_acceptance(api.RunnerConfig(), factory=lambda *_: calls.append(1))
    assert not calls and report.real_requests == 0 and report.model_requests == 0
    assert len(report.cases) == 6 and all(case.status == "not_run" for case in report.cases)
    assert report.exit_code == 2


@pytest.mark.parametrize(
    "field,value", [("max_requests", -1), ("max_cases", True), ("max_seconds", float("inf")), ("max_requests", 1.5)]
)
def test_invalid_budget_rejected(api, field, value):
    with pytest.raises(ValueError):
        api.RunnerBudget(**{field: value})


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({}, "provider_not_enabled"),
        ({"allow_provider": True}, "request_budget_missing"),
        (
            {"allow_provider": True, "budget": {"max_cases": 6, "max_seconds": 120, "max_requests": 12}},
            "provider_configuration_missing",
        ),
        ({"mode": "isolated-integration", "allow_provider": True}, "isolated_target_unverified"),
        ({"synthetic": False}, "synthetic_fixture_required"),
    ],
)
def test_rejected_before_factory_secrets_or_first_external_call(api, changes, reason, monkeypatch):
    monkeypatch.setattr("os.getenv", lambda *_: pytest.fail("secret access before authorization"))
    config = api.RunnerConfig.model_validate(
        {"mode": "provider-memory", "budget": {"max_cases": 6, "max_seconds": 120}, **changes}
    )
    report = api.run_acceptance(config, factory=lambda *_: pytest.fail("external factory before authorization"))
    assert report.reason == reason and report.real_requests == 0
    assert all(case.status == "not_run" for case in report.cases)


def test_request_limit_counts_retries_and_global_turns(api):
    now = [0.0]
    limiter = api.RunnerLimiter(
        api.RunnerBudget(max_cases=6, max_requests=12, max_seconds=120), monotonic=lambda: now[0]
    )
    for _case in range(3):
        limiter.begin_case()
        for _turn in range(2):
            limiter.user_turn()
            limiter.model_request()
            limiter.before_request()
            limiter.before_request()  # An SDK retry is another wire attempt.
    with pytest.raises(api.RunnerStopped):
        limiter.before_request()
    assert limiter.real_requests == 12 and limiter.model_requests == 6 and limiter.user_turns == 6


def test_deadline_and_case_limit_prevent_next_side_effect(api):
    now = [0.0]
    limiter = api.RunnerLimiter(api.RunnerBudget(max_cases=1, max_requests=2, max_seconds=3), monotonic=lambda: now[0])
    limiter.begin_case()
    with pytest.raises(api.RunnerStopped):
        limiter.begin_case()
    now[0] = 3
    with pytest.raises(api.RunnerStopped):
        limiter.before_request()
    assert limiter.real_requests == 0


def test_case_cap_reports_all_unstarted_cases_without_factory_replay(api):
    class Local:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def execute(self, case, limiter):
            return api.CaseResult(case_id=case.id, status="passed", evidence_layer="local_memory")

    report = api.run_acceptance(
        api.RunnerConfig(budget=api.RunnerBudget(max_cases=1, max_seconds=10)), factory=lambda *_: Local()
    )
    assert len(report.cases) == 6 and sum(case.status == "not_run" for case in report.cases) == 5
    assert report.exit_code == 2


def test_failure_is_not_model_success_and_does_not_leak_exception(api):
    class Broken:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def execute(self, *_args):
            raise RuntimeError("PRIVATE_TOKEN_AND_PATIENT_BODY")

    config = api.RunnerConfig(budget=api.RunnerBudget(max_cases=1, max_seconds=10))
    report = api.run_acceptance(config, factory=lambda *_: Broken())
    assert report.cases[0].status == "failed" and not report.cases[0].model_success
    assert report.exit_code == 1 and "PRIVATE" not in report.model_dump_json()


def test_runner_stop_preserves_actual_counts_and_marks_remaining_not_run(api):
    class Capped:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def execute(self, _case, limiter):
            limiter.before_request()
            limiter.before_request()

    config = api.RunnerConfig(
        mode="provider-memory",
        allow_provider=True,
        model="gemini-demo",
        api_key_env="MEDITHREAD_ACCEPTANCE_KEY",
        budget=api.RunnerBudget(max_cases=6, max_seconds=120, max_requests=1),
    )
    report = api.run_acceptance(config, factory=lambda *_: Capped())
    assert report.real_requests == 1 and len(report.cases) == 6
    assert all(case.status == "not_run" for case in report.cases)
    assert report.reason == "request_limit"
    assert report.cases[0].real_requests == 1 and report.cases[0].wire_attempts == 1
    assert all(case.real_requests == 0 for case in report.cases[1:])


def test_unexpected_factory_failure_is_not_misreported_as_missing_key(api):
    def broken(*_args):
        raise RuntimeError("PRIVATE_SETUP_FAILURE")

    config = api.RunnerConfig(
        mode="provider-memory",
        allow_provider=True,
        model="gemini-demo",
        api_key_env="MEDITHREAD_ACCEPTANCE_KEY",
        budget=api.RunnerBudget(max_cases=6, max_seconds=120, max_requests=1),
    )
    report = api.run_acceptance(config, factory=broken)
    assert report.reason == "execution_failed" and report.exit_code == 1
    assert "PRIVATE" not in report.model_dump_json()


def test_failed_case_preserves_spent_attempts(api):
    class Broken:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def execute(self, _case, limiter):
            limiter.before_request()
            raise RuntimeError("PRIVATE")

    config = api.RunnerConfig(
        mode="provider-memory",
        allow_provider=True,
        model="gemini-demo",
        api_key_env="MEDITHREAD_ACCEPTANCE_KEY",
        budget=api.RunnerBudget(max_cases=1, max_requests=1, max_seconds=120),
    )
    report = api.run_acceptance(config, factory=lambda *_: Broken())
    assert report.cases[0].real_requests == 1 and report.cases[0].wire_attempts == 1


def test_replay_cannot_claim_model_success(api):
    with pytest.raises(ValueError):
        api.CaseResult(
            case_id=api.SCENARIOS[0].id, status="passed", evidence_layer="recording_port", model_success=True
        )


def test_report_verifies_provider_claim_against_actual_runner_counters(api):
    class FalseEvidence:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def execute(self, case, _limiter):
            return api.CaseResult(
                case_id=case.id,
                status="passed",
                evidence_layer="provider_memory",
                model_success=True,
                model_requests=1,
                real_requests=1,
                wire_attempts=1,
                returned_model="gemini-demo",
            )

    config = api.RunnerConfig(
        mode="provider-memory",
        allow_provider=True,
        model="gemini-demo",
        api_key_env="MEDITHREAD_ACCEPTANCE_KEY",
        budget=api.RunnerBudget(max_cases=1, max_requests=1, max_seconds=120),
    )
    report = api.run_acceptance(config, factory=lambda *_: FalseEvidence())
    assert report.cases[0].status == "failed" and not report.cases[0].model_success
    assert report.real_requests == 0 and report.exit_code == 1


def test_cli_default_and_unverified_target_are_not_run_and_output_is_private(tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    script = root / "scripts/qa/run_assistant_acceptance.py"
    assert script.exists(), "Guarded acceptance CLI is missing"
    for mode in ("offline", "isolated-integration"):
        target = f"outputs/assistant-acceptance/test-{uuid4().hex}.json"
        completed = subprocess.run(
            [sys.executable, str(script), "--mode", mode, "--output", target], cwd=root, capture_output=True, text=True
        )
        assert completed.returncode == 2 and "Traceback" not in completed.stderr
        result = json.loads((root / target).read_text(encoding="utf-8"))
        assert result["report"]["real_requests"] == 0
        assert len(result["report"]["cases"]) == 6
    outside = tmp_path / "not-private.json"
    completed = subprocess.run(
        [sys.executable, str(script), "--output", str(outside)], cwd=root, capture_output=True, text=True
    )
    assert completed.returncode == 1 and not outside.exists()


def test_persistence_preflight_never_enables_provider_or_execution(monkeypatch,tmp_path):
    from scripts.qa import run_assistant_acceptance as cli
    output='outputs/assistant-acceptance/DEMO-persistence-preflight.json'
    monkeypatch.setattr(cli,'private_output',lambda value:tmp_path/'result.json')
    monkeypatch.setattr(cli,'run_acceptance',lambda *_:pytest.fail('Preflight executed acceptance'))
    monkeypatch.setattr('psycopg.connect',lambda *_a,**_k:pytest.fail('Preflight connected'))
    assert cli.main(['--persistence-preflight','--output',output])==2
    import json
    artifact=json.loads((tmp_path/'result.json').read_text(encoding='utf-8'))
    assert artifact['status']=='NOT_RUN' and artifact['reason']=='target_not_authorized'
    assert artifact['real_requests']==0 and artifact['provider_requests']==0


def test_persistence_preflight_cannot_combine_with_provider_flags(monkeypatch,tmp_path):
    from scripts.qa import run_assistant_acceptance as cli
    monkeypatch.setattr(cli,'private_output',lambda value:tmp_path/'result.json')
    monkeypatch.setattr(cli,'run_acceptance',lambda *_:pytest.fail('Mixed preflight ran provider'))
    assert cli.main(['--persistence-preflight','--allow-provider','--mode','provider-memory'])==2
