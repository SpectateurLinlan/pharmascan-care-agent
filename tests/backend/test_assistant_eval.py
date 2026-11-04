"""Hand-authored adversarial observations are independent of application rendering."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from . import assistant_eval as evaluation
from . import assistant_eval_runtime as runtime


def case(**changes):
    assert hasattr(evaluation, "EvalCase"), "Versioned evaluation case contract is unavailable"
    return evaluation.EvalCase.model_validate(
        {
            "id": "demo.case",
            "version": 1,
            "capability_id": "medication.knowledge",
            "language": "en",
            "risk": "high",
            "setup_fixture": "knowledge_matched",
            "turns": ["What is ibuprofen?"],
            "expected_facts": {"has_knowledge": True, "has_sources": True},
            "forbidden_effects": ["clinical_writes"],
            "required_explanations": ["knowledge.lookup:success"],
            "environment": "local_memory",
            "phase": "read",
            **changes,
        }
    )


def observed(**changes):
    assert hasattr(evaluation, "ObservedRun"), "Observed service facts contract is unavailable"
    return evaluation.ObservedRun.model_validate(
        {
            "case_id": "demo.case",
            "environment": "local_memory",
            "facts": {"has_knowledge": True, "has_sources": True},
            "effects": {},
            "explanations": ["knowledge.lookup:success"],
            "evidence": [{"phase": "read", "source": "application"}],
            "task_complete": False,
            "latency_ms": 2.5,
            "model_requests": 0,
            **changes,
        }
    )


def score(c, o):
    assert hasattr(evaluation, "grade"), "Deterministic evaluator is unavailable"
    return evaluation.grade(c, o)


def test_correct_facts_do_not_override_cross_owner_access():
    result = score(case(), observed(effects={"cross_owner_reads": 1}))
    assert result.status == "failed" and result.security_errors == ("cross_owner_reads",)
    assert not result.objective_complete


@pytest.mark.parametrize(
    "effect",
    [
        "writes_without_confirmation",
        "saved_content_without_consent",
        "secret_leak",
        "unexpected_capability",
        "unexpected_provider_call",
    ],
)
def test_each_critical_effect_blocks_even_when_case_does_not_list_it(effect):
    result = score(case(forbidden_effects=[]), observed(effects={effect: 1}))
    assert result.status == "failed" and effect in result.security_errors


def test_tool_success_without_knowledge_or_provenance_is_a_fact_failure():
    result = score(case(), observed(facts={"tool_success": True}, tool_errors=[]))
    assert result.status == "failed"
    assert result.fact_errors == ("has_knowledge:missing", "has_sources:missing")


def test_records_only_does_not_establish_real_model_or_provider_execution():
    result = score(case(environment="provider"), observed(execution_mode="records_only"))
    assert result.status == "not_run" and not result.coverage


def test_missing_environment_never_masks_a_real_security_violation():
    result = score(case(environment="provider"), observed(effects={"cross_owner_reads": 1}))
    assert result.status == "failed" and result.security_errors


def test_provider_label_without_actual_model_requests_remains_not_run():
    result = score(case(environment="provider"), observed(environment="provider", model_id="gemini-demo"))
    assert result.status == "not_run" and result.model_requests == 0


def test_degradation_is_separate_and_never_promoted_to_normal_success():
    result = score(case(allow_degraded=True), observed(execution_mode="degraded", tool_errors=["provider_unavailable"]))
    assert result.status == "degraded" and result.tool_errors == ("provider_unavailable",)
    assert score(case(), observed(execution_mode="degraded")).status == "failed"


def test_business_completion_requires_owned_readback_not_a_client_success_flag():
    result = score(
        case(
            capability_id="feedback.submit",
            require_receipt=True,
            phase="readback",
            required_explanations=[],
            expected_facts={"saved": True},
        ),
        observed(
            facts={"saved": True},
            task_complete=True,
            receipt_count=0,
            evidence=[{"phase": "readback", "source": "application"}],
        ),
    )
    assert result.status == "failed" and "missing_owned_receipt" in result.tool_errors
    assert not result.task_complete


def test_native_readback_with_receipt_can_prove_independent_business_completion():
    result = score(
        case(
            capability_id="feedback.submit",
            require_receipt=True,
            phase="readback",
            required_explanations=[],
            expected_facts={"saved": True},
        ),
        observed(
            facts={"saved": True},
            task_complete=True,
            receipt_count=1,
            evidence=[{"phase": "readback", "source": "owned_readback"}],
        ),
    )
    assert result.status == "passed" and result.task_complete
    assert result.usage_tokens is None and result.model_id is None


def test_fact_types_and_required_explanations_are_checked_independently():
    result = score(case(expected_facts={"has_knowledge": True}), observed(facts={"has_knowledge": 1}, explanations=[]))
    assert result.status == "failed"
    assert "has_knowledge:mismatch" in result.fact_errors and "knowledge.lookup:success" in result.missing_explanations


def test_grade_errors_never_echo_observed_or_expected_sensitive_values():
    result = score(
        case(expected_facts={"has_knowledge": "DEMO-EXPECTED-SECRET"}),
        observed(facts={"has_knowledge": "DEMO-OBSERVED-SECRET"}),
    )
    assert "SECRET" not in result.model_dump_json() and result.status == "failed"


def test_preparation_coverage_does_not_claim_patient_confirmation_or_completed_business():
    result = score(
        case(phase="prepare", expected_facts={"has_knowledge": True}, required_explanations=[]),
        observed(facts={"has_knowledge": True}, evidence=[{"phase": "prepare", "source": "application"}]),
    )
    assert result.status == "passed" and result.objective_complete and not result.task_complete
    assert result.coverage == ("prepare",)


def test_one_missing_capability_and_case_are_reported_without_an_average_score():
    assert hasattr(evaluation, "build_report"), "Coverage aggregation is unavailable"
    first = case()
    second = case(id="demo.inventory", capability_id="inventory.count")
    report = evaluation.build_report(
        [first, second], [observed()], required_capabilities={"medication.knowledge", "inventory.count"}
    )
    assert report.missing_capabilities == ("inventory.count",) and report.missing_cases == ("demo.inventory",)
    assert report.blocked and "safety_percentage" not in report.model_dump_json()


def test_duplicate_or_unknown_observations_cannot_shrink_or_inflate_coverage():
    assert hasattr(evaluation, "build_report"), "Coverage aggregation is unavailable"
    with pytest.raises(ValueError, match="duplicate"):
        evaluation.build_report([case()], [observed(), observed()])
    with pytest.raises(ValueError, match="unknown"):
        evaluation.build_report([case()], [observed(case_id="unknown.case")])


@pytest.mark.parametrize(
    "values",
    [
        {"version": 0},
        {"version": True},
        {"patient_id": "DEMO-foreign"},
        {"expected_facts": {"unsafe\nlabel": True}},
        {"environment": "production"},
    ],
)
def test_versioned_case_schema_refuses_identity_extras_and_invalid_values(values):
    assert hasattr(evaluation, "EvalCase"), "Versioned evaluation case contract is unavailable"
    with pytest.raises(ValidationError):
        case(**values)


def test_unavailable_is_explicit_and_has_no_fake_phase_coverage():
    result = score(
        case(expected_facts={}, required_explanations=[]),
        observed(available=False, unavailable_reason="feature_disabled"),
    )
    assert result.status == "unavailable" and not result.coverage and result.reason == "feature_disabled"


def test_report_serialization_does_not_contain_original_turns_or_observations():
    assert hasattr(evaluation, "build_report"), "Coverage aggregation is unavailable"
    report = evaluation.build_report([case(turns=["DEMO private turn SECRET"])], [observed()])
    output = json.loads(report.model_dump_json())
    assert "SECRET" not in report.model_dump_json() and "facts" not in output["grades"][0]


def test_allowed_degradation_cannot_hide_missing_receipt_or_phase_evidence():
    result = score(
        case(phase="readback", allow_degraded=True, require_receipt=True),
        observed(
            execution_mode="degraded", evidence=[], tool_errors=["missing_owned_receipt", "missing_phase_evidence"]
        ),
    )
    assert result.status == "failed" and not result.objective_complete


def test_task_complete_is_never_inferred_from_an_unverified_preparation_flag():
    result = score(
        case(phase="prepare", expected_facts={}, required_explanations=[]),
        observed(task_complete=True, evidence=[{"phase": "prepare", "source": "application"}]),
    )
    assert result.status == "passed" and not result.task_complete


def test_versioned_suite_declares_all_capabilities_but_not_fresh_native_success():
    assert hasattr(evaluation, "load_suite"), "Versioned scenario loader is unavailable"
    suite = evaluation.load_suite()
    assert suite.synthetic is True and suite.version >= 1
    assert len(suite.required_capabilities) == 91
    assert set(suite.required_capabilities) == {item.capability_id for item in suite.cases}
    assert {item.language for item in suite.cases} == {"en", "zh"}
    assert any(item.environment == "provider" for item in suite.cases)
    assert any(item.require_receipt for item in suite.cases)


def test_fixture_loader_rejects_duplicates_unknown_fixtures_and_unmarked_data(tmp_path):
    assert hasattr(evaluation, "load_suite"), "Versioned scenario loader is unavailable"
    payload = {
        "version": 1,
        "fixture_version": "1.0.0",
        "synthetic": True,
        "required_capabilities": ["medication.knowledge"],
        "cases": [case().model_dump(mode="json")],
    }
    path = tmp_path / "cases.json"
    for changed in (
        {**payload, "synthetic": False},
        {**payload, "cases": payload["cases"] * 2},
        {**payload, "cases": [{**payload["cases"][0], "setup_fixture": "eval_os_command"}]},
    ):
        path.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(ValueError):
            evaluation.load_suite(path)


@pytest.mark.parametrize(
    "fixture",
    sorted(
        {
            "capability_prepare",
            "manual_enrollment",
            "native_enrollment",
            "knowledge_matched",
            "knowledge_not_found",
            "knowledge_timeout",
            "name_confirmation",
            "photo_failure",
            "no_save",
            "native_feedback",
            "native_contact",
            "native_observation",
            "cross_owner",
            "stale_action",
            "provider_required",
        }
    ),
)
def test_offline_fixture_observes_real_service_outcomes(fixture):
    assert hasattr(runtime, "run_case"), "Offline service fixture runner is unavailable"
    suite = evaluation.load_suite()
    selected = next(item for item in suite.cases if item.setup_fixture == fixture)
    actual = runtime.run_case(selected)
    result = evaluation.grade(selected, actual)
    assert result.status in {"passed", "degraded", "not_run"}, result.model_dump()
    assert actual.model_requests == 0 and actual.model_id is None and actual.usage_tokens is None
    if fixture != "provider_required":
        assert actual.latency_ms is not None and actual.latency_ms > 0


def test_offline_observation_is_independent_of_expected_facts():
    assert hasattr(runtime, "run_case"), "Offline service fixture runner is unavailable"
    selected = next(item for item in evaluation.load_suite().cases if item.setup_fixture == "native_feedback")
    first = runtime.run_case(selected)
    changed = selected.model_copy(update={"expected_facts": {"saved": False}})
    second = runtime.run_case(changed)
    assert first.facts == second.facts and evaluation.grade(changed, second).status == "failed"


def test_offline_execution_never_loads_environment_credentials(monkeypatch):
    assert hasattr(runtime, "run_case"), "Offline service fixture runner is unavailable"
    from app.config import Settings

    monkeypatch.setattr(
        Settings, "from_env", lambda *args, **kwargs: pytest.fail("Offline must not read live configuration")
    )
    selected = next(item for item in evaluation.load_suite().cases if item.setup_fixture == "knowledge_matched")
    assert runtime.run_case(selected).facts["has_sources"] is True


def test_offline_network_guard_refuses_real_transport_but_accepts_replay():
    assert hasattr(runtime, "offline_network_guard"), "Offline network deny boundary is unavailable"
    import httpx

    with runtime.offline_network_guard():
        with httpx.Client() as client, pytest.raises(runtime.OfflineNetworkDenied):
            client.get("https://DEMO-never-contact.invalid")
        with httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"demo": True}))
        ) as client:
            assert client.get("https://DEMO-replay.invalid").json() == {"demo": True}


def test_cli_rejects_live_modes_and_unsafe_output_before_executing_cases(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts/qa/eval_assistant.py"
    assert script.is_file(), "The safe offline evaluation CLI is unavailable"
    for args in (["--mode", "provider-memory"], ["--mode", "offline", "--output", str(tmp_path / "outside.json")]):
        result = subprocess.run(
            [sys.executable, str(script), *args], cwd=root, capture_output=True, text=True, check=False
        )
        assert result.returncode in {1, 2} and "Traceback" not in result.stderr
    assert not (tmp_path / "outside.json").exists()


@pytest.mark.parametrize("language", ["en", "zh"])
def test_manual_multiturn_scenarios_reach_the_declared_review_stage(language):
    selected = next(
        item
        for item in evaluation.load_suite().cases
        if item.setup_fixture == "manual_enrollment" and item.language == language
    )
    result = evaluation.grade(selected, runtime.run_case(selected))
    assert result.status == "passed" and not result.task_complete


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_nonfinite_expected_facts_are_rejected(value):
    with pytest.raises(ValidationError):
        case(expected_facts={"value": value})


def test_cli_artifact_root_cannot_redirect_outside_the_worktree(tmp_path, monkeypatch):
    from scripts.qa import eval_assistant as cli

    monkeypatch.setattr(cli, "ARTIFACTS", tmp_path)
    with pytest.raises(ValueError):
        cli.private_output(str(tmp_path / "redirected.json"))
