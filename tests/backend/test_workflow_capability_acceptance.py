"""P06-T8 cross-capability gates; native action evidence is distinct from preparation.

These are new composition checks, not a replay of already accepted domain suites.
The public manifest points to executable tests, never private run logs or patient data.
"""

import ast
import json
from pathlib import Path

import pytest
from app.agent.capabilities import build_capability_registry
from app.contracts import assistant_capabilities as coverage_contracts
from app.contracts.assistant_capabilities import CapabilityAvailability

from .test_workflow_records import clinical

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads((ROOT / "tests/fixtures/assistant/capability_coverage.json").read_text(encoding="utf-8"))
ROWS = MANIFEST["capabilities"]


def required_phases(row):
    if row["capability_id"].startswith("conversation.") and row["mode"] == "workflow":
        return {"prepare", "patient_action", "readback"}
    if row["mode"] == "workflow":
        return {"prepare", "patient_confirmation", "readback"}
    if row["mode"] in {"patient_ui", "device_ui", "navigation"}:
        return {"prepare", "patient_action"}
    return {"prepare", "read"}


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["capability_id"])
def test_every_capability_has_executable_phase_evidence(row):
    assert row["implementation"] == "implemented"
    cases = row.get("acceptance_cases", [])
    assert {case["phase"] for case in cases} >= required_phases(row)
    assert len({case["case_id"] for case in cases}) == len(cases)
    for case in cases:
        assert case["case_id"].startswith(row["case_id"] + ".")
        assert case["environment"] in {"local_memory", "local_browser", "recording_port"}
        assert case["test_refs"]
        for ref in case["test_refs"]:
            path, _, name = ref.partition("::")
            source = ROOT / path
            assert source.is_file(), ref
            assert source.resolve().is_relative_to(ROOT)
            assert not path.startswith(("internal/", "outputs/"))
            if path.endswith(".py"):
                functions = {node.name for node in ast.walk(ast.parse(source.read_text(encoding="utf-8-sig")))
                             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
                assert name in functions, ref
            else:
                assert name and name in source.read_text(encoding="utf-8"), ref


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["capability_id"])
def test_every_available_capability_prepares_through_actual_http_composition(workflow, row):
    h = workflow
    catalog = h._request("GET", "/api/agent/workflows/capabilities")
    capability = next(item for item in catalog["capabilities"] if item["id"] == row["capability_id"])
    before = clinical(h)
    if not capability["available"]:
        expected = {"notification.test": "notification_send_not_authorized", "medication.knowledge": "feature_disabled"}
        assert capability["reason"] == expected.get(row["capability_id"]), capability
        return
    task = h.start(row["capability_id"])
    assert task["capability_id"] == row["capability_id"]
    assert task["prompt_key"] and task["state"] != "completed"
    assert task["result_ref"] is None, "Preparation alone cannot establish a native operation result"
    assert clinical(h) == before


def test_manifest_and_model_catalog_have_no_missing_or_extra_capabilities(workflow):
    catalog = workflow._request("GET", "/api/agent/workflows/capabilities")
    known = {row["id"] for row in catalog["capabilities"]}
    assert known == {row["capability_id"] for row in ROWS}
    registry = build_capability_registry()
    definitions = registry.list(CapabilityAvailability())
    availability = CapabilityAvailability(workflows_enabled=True, notification_send_allowed=True,
        adapters=frozenset(row.adapter_key for row in definitions),
        services=frozenset(service for row in definitions for service in row.required_services))
    assert all(row.mode in {"read", "workflow"} for row in registry.model_catalog(availability))
    assert all(not row.available for row in registry.list(CapabilityAvailability()))


def test_coverage_result_never_promotes_an_unavailable_or_unrun_case_to_pass():
    assert hasattr(coverage_contracts, "CoverageResult"), "Results must distinguish every evidence environment"
    from pydantic import ValidationError

    result = coverage_contracts.CoverageResult
    base = {"capability_id": "notification.test", "case_id": "notification.test.acceptance.device",
            "environment": "physical_device", "evidence_path": None}
    with pytest.raises(ValidationError):
        result(**base, status="PASS", reason=None)
    with pytest.raises(ValidationError):
        result(**base, status="UNAVAILABLE", reason=None)
    assert result(**base, status="UNAVAILABLE", reason="not_authorized").status == "UNAVAILABLE"
    assert result(**base, status="NOT_RUN", reason="device_permission_not_requested").status == "NOT_RUN"


def test_configured_knowledge_is_available_and_prepares_without_provider_access():
    from .workflow_support import WorkflowHarness

    with WorkflowHarness(knowledge_v2_enabled=True) as h:
        catalog = h._request("GET", "/api/agent/workflows/capabilities")
        row = next(row for row in catalog["capabilities"] if row["id"] == "medication.knowledge")
        assert row["available"] and row["reason"] is None
        task = h.start("medication.knowledge", {"medication_name": "ibuprofen"})
        assert task["visible_fields"]["name_resolution"]["status"] == "resolved"
        assert not h.knowledge_requests


def test_help_and_guide_index_their_actual_native_entry_points():
    rows = {row["capability_id"]: row for row in ROWS}
    assert MANIFEST["navigation_routes"]["help"] == "help.open"
    assert rows["help.open"]["entry_points"] == ["navigation.help"]
    assert "ui.onboarding.replay" in rows["guide.start"]["entry_points"]
    assert MANIFEST["ui_operations"]["onboarding.replay"] == ["guide.start"]
