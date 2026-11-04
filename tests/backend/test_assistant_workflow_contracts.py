"""Workflow boundaries reject identity, confirmation and unbounded client state."""

from uuid import UUID, uuid4

import pytest
from app.contracts.assistant_workflows import EphemeralPayload, UIAction, WorkflowEvent, validate_workflow_values
from app.domain.errors import ValidationError as DomainValidationError
from pydantic import TypeAdapter, ValidationError


def test_inventory_fields_are_validated_without_identity_or_confirmation_authority():
    parsed = validate_workflow_values("inventory.count", {"quantity": 12, "unit": "tablet", "kind": "count"})
    assert parsed.model_dump()["quantity"] == 12
    assert "confirmed" not in parsed.model_dump()
    assert "patient_id" not in parsed.model_dump()


@pytest.mark.parametrize("values", [
    {"quantity": 12, "unit": "mg"},
    {"dose_amount": 500},
    {"quantity": -1, "unit": "tablet", "kind": "count"},
    {"quantity": 12, "unit": "tablet", "confirmed": True},
    {"quantity": 12, "unit": "tablet", "patient_id": str(UUID(int=200))},
    {"quantity": 12, "unit": "tablet", "storage_path": "other-owner/private"},
])
def test_invalid_inventory_or_authority_fields_are_rejected(values):
    with pytest.raises((ValidationError, DomainValidationError)):
        validate_workflow_values("inventory.count", values)


def test_unknown_capability_does_not_accept_generic_arguments():
    with pytest.raises(DomainValidationError):
        validate_workflow_values("execute_sql", {"sql": "delete"})


def test_workflow_event_cannot_claim_confirmation_or_select_owner():
    with pytest.raises(ValidationError):
        WorkflowEvent(event_id=uuid4(), expected_revision=1, kind="provide_fields", confirmed=True)
    with pytest.raises(ValidationError):
        WorkflowEvent(event_id=uuid4(), expected_revision=1, kind="confirm", values={})


def test_ephemeral_payload_budget_counts_utf8_not_characters():
    with pytest.raises(ValidationError):
        EphemeralPayload(capability_id="medication.enroll", fields={"note": "药" * 6000})
    assert EphemeralPayload(capability_id="medication.enroll", fields={"note": "药" * 100}).fields


def test_begin_enrollment_accepts_method_without_inventing_medication_fields():
    values = validate_workflow_values("medication.enroll", {"method": "manual"})
    assert values.model_dump(exclude_none=True) == {"method": "manual"}


@pytest.mark.parametrize("action", [
    {"kind": "navigate", "route": "https://example.test/unsafe"},
    {"kind": "navigate", "route": "today", "url": "https://example.test"},
    {"kind": "existing_review", "component_key": "arbitrary_component",
     "owned_ref": {"kind": "medication", "id": str(UUID(int=1))}, "expected_version": 1},
])
def test_ui_actions_reject_arbitrary_routes_components_and_urls(action):
    with pytest.raises(ValidationError):
        TypeAdapter(UIAction).validate_python(action)


def test_ephemeral_budget_accepts_exact_boundary_and_rejects_one_extra_byte():
    empty = EphemeralPayload(capability_id="medication.enroll", fields={"note": ""})
    length = 16384 - len(empty.model_dump_json().encode("utf-8"))
    assert len(empty.model_copy(update={"fields": {"note": "x" * length}}).model_dump_json()) == 16384
    assert EphemeralPayload(capability_id="medication.enroll", fields={"note": "x" * length})
    with pytest.raises(ValidationError):
        EphemeralPayload(capability_id="medication.enroll", fields={"note": "x" * (length + 1)})


@pytest.mark.parametrize("values", [
    {"quantity": 100001}, {"quantity": 0, "low_threshold": 10001},
    {"quantity": 0, "kind": "refill"}, {"quantity": 0, "kind": "lost"},
    {"quantity": 1, "note": "x" * 501}, {"quantity": float("inf")},
])
def test_inventory_reuses_existing_quantity_threshold_note_and_finite_bounds(values):
    with pytest.raises(ValidationError):
        validate_workflow_values("inventory.count", {"unit": "tablet", **values})
