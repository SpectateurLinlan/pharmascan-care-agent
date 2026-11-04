"""Capability discovery is truthful; this does not prove business execution."""

import json
import re
from pathlib import Path

import pytest
from app.agent.capabilities import build_capability_registry
from app.contracts.assistant_capabilities import CapabilityAvailability
from app.domain.errors import ValidationError


def test_catalog_covers_existing_user_operations_without_enabling_unimplemented_adapters():
    registry = build_capability_registry()
    views = {row.id: row for row in registry.list(CapabilityAvailability(workflows_enabled=True))}
    assert {"medication.enroll", "followup.contacted", "library.pdf.delete", "account.link"} <= views.keys()
    assert all(not row.available and row.reason == "not_implemented" for row in views.values())


def test_capability_unavailable_without_required_service():
    availability = CapabilityAvailability(workflows_enabled=True, adapters=frozenset({"media"}))
    views = {row.id: row for row in build_capability_registry().list(availability)}
    assert views["gallery.photo.add"].available is False
    assert views["gallery.photo.add"].reason == "service_unavailable"


def test_disabled_workflows_do_not_claim_executable_support():
    availability = CapabilityAvailability(adapters=frozenset({"care"}), services=frozenset({"care"}))
    views = {row.id: row for row in build_capability_registry().list(availability)}
    assert views["inventory.count"].reason == "feature_disabled"


def test_registered_adapter_and_required_service_enable_only_its_own_operations():
    availability = CapabilityAvailability(
        workflows_enabled=True, adapters=frozenset({"care"}), services=frozenset({"care"})
    )
    views = {row.id: row for row in build_capability_registry().list(availability)}
    assert views["inventory.count"].available
    assert not views["observation.add"].available
    assert not views["medication.enroll"].available


def test_model_catalog_never_offers_late_report_execution_or_account_secrets():
    availability = CapabilityAvailability(
        workflows_enabled=True,
        adapters=frozenset({"records", "account_ui"}),
        services=frozenset({"records", "self_report", "late_reports", "account"}),
    )
    registry = build_capability_registry()
    assert registry.get("dose.late.review").mode == "patient_ui"
    offered = {row.id for row in registry.model_catalog(availability)}
    assert "dose.late.review" not in offered
    assert "dose.correction.review" not in offered
    assert "account.password" not in offered


def test_notification_send_is_a_separate_permission():
    availability = CapabilityAvailability(
        workflows_enabled=True, adapters=frozenset({"reminders"}), services=frozenset({"push"})
    )
    views = {row.id: row for row in build_capability_registry().list(availability)}
    assert views["notification.status"].available
    assert not views["notification.test"].available
    assert views["notification.test"].reason == "notification_send_not_authorized"


@pytest.mark.parametrize("value", ["https://example.test/delete", "execute_sql", "dose.backfill", ""])
def test_unknown_capability_is_rejected_without_dynamic_endpoint_fallback(value):
    with pytest.raises(ValidationError):
        build_capability_registry().get(value)


def test_every_user_entry_has_capability_or_internal_substep():
    root = Path(__file__).resolve().parents[2]
    fixture = json.loads((root / "tests/fixtures/assistant/capability_coverage.json").read_text(encoding="utf-8"))
    source = (root / "frontend/src/api/client.ts").read_text(encoding="utf-8").split("export const api = {", 1)[1]
    actual = set(re.findall(r"^  ([A-Za-z][A-Za-z0-9]*)\s*:", source, re.M))
    assert actual == fixture["api_methods"].keys()
    known = {row.id for row in build_capability_registry().list(CapabilityAvailability())}
    for entry in fixture["api_methods"].values():
        assert entry["capabilities"] and set(entry["capabilities"]) <= known
        if entry["internal"]:
            assert entry["reason"]
    assert {row["capability_id"] for row in fixture["capabilities"]} == known
    mapped = set()
    for entry in fixture["api_methods"].values():
        mapped.update(entry["capabilities"])
    for entries in fixture["account_operations"].values():
        mapped.update(entries)
    for entries in fixture.get("ui_operations", {}).values():
        mapped.update(entries)
    mapped.update(fixture["navigation_routes"].values())
    assert known <= mapped, f"Capabilities without entry-point evidence: {known - mapped}"
    for row in fixture["capabilities"]:
        assert row["entry_points"]
        assert row["implementation_task"].startswith(("P01-", "P03-", "P05-", "P06-"))


def test_model_catalog_excludes_every_patient_and_device_only_operation():
    registry = build_capability_registry()
    definitions = registry.list(CapabilityAvailability())
    availability = CapabilityAvailability(
        workflows_enabled=True, notification_send_allowed=True,
        adapters=frozenset(row.adapter_key for row in definitions),
        services=frozenset(service for row in definitions for service in row.required_services),
    )
    offered = {row.id for row in registry.model_catalog(availability)}
    assert offered
    assert all(row.mode in {"read", "workflow"} for row in definitions if row.id in offered)


def test_account_and_navigation_entries_are_accounted_for():
    root = Path(__file__).resolve().parents[2]
    fixture = json.loads((root / "tests/fixtures/assistant/capability_coverage.json").read_text(encoding="utf-8"))
    auth = (root / "frontend/src/api/auth.ts").read_text(encoding="utf-8")
    interface = auth.split("export interface AccountPort {", 1)[1].split("\n}", 1)[0]
    methods = set(re.findall(r"\b([a-zA-Z][A-Za-z0-9]*)\([^)]*\):Promise", interface))
    assert methods == fixture.get("account_operations", {}).keys()
    navigation = (root / "frontend/src/navigation.ts").read_text(encoding="utf-8")
    section = navigation.split("const parents: Record<string,string> = {", 1)[1].split("};", 1)[0]
    routes = set(re.findall(r"(?:'([^']+)'|\b([a-z][a-z-]*))\s*:", section))
    actual_routes = {first or second for first, second in routes} | {"today", "medicines", "records", "me"}
    assert actual_routes == fixture.get("navigation_routes", {}).keys()
