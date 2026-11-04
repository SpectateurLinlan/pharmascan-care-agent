"""Synthetic contracts: proof metadata must never become patient-write authority."""

import importlib
import importlib.util
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.contracts.assistant_workflows import BusinessRef
from app.contracts.workflow_attachments import OriginalAttachment
from pydantic import ValidationError


def contract(module, name):
    path = f"app.contracts.{module}"
    assert importlib.util.find_spec(path), f"Missing approved persistence contract: {module}"
    return getattr(importlib.import_module(path), name)


def observation(**change):
    return {
        "ticket_id": uuid4(),
        "nonce": uuid4(),
        "generation": 1,
        "result": "bytes_verified",
        "checksum": "a" * 64,
        "byte_size": 42,
        "observed_at": datetime(2026, 10, 28, tzinfo=UTC),
        **change,
    }


@pytest.mark.parametrize(
    "extra", [{"owner": uuid4()}, {"object_ref": "DEMO/path"}, {"success": True}, {"content": "DEMO-private-body"}]
)
def test_observation_rejects_owner_key_and_success_claim(extra):
    cls = contract("workflow_verification", "StorageObservation")
    with pytest.raises(ValidationError):
        cls.model_validate(observation(**extra))


@pytest.mark.parametrize(
    "changes",
    [
        {"checksum": None},
        {"byte_size": None},
        {"byte_size": True},
        {"byte_size": 0},
        {"generation": True},
        {"generation": "1"},
        {"generation": 0},
        {"observed_at": datetime(2026, 10, 28)},
        {"checksum": "not-a-digest"},
    ],
)
def test_byte_observation_requires_actual_strict_metadata(changes):
    cls = contract("workflow_verification", "StorageObservation")
    with pytest.raises(ValidationError):
        cls.model_validate(observation(**changes))


@pytest.mark.parametrize("result", ["absent_after_delete", "definitely_not_started", "outcome_unknown"])
def test_nonbyte_observation_cannot_smuggle_a_saved_checksum(result):
    cls = contract("workflow_verification", "StorageObservation")
    with pytest.raises(ValidationError):
        cls.model_validate(observation(result=result))
    parsed = cls.model_validate(observation(result=result, checksum=None, byte_size=None))
    assert parsed.result == result


def test_proof_metadata_has_aware_time_is_frozen_and_hides_nonce():
    cls = contract("workflow_verification", "StorageObservation")
    row = cls.model_validate(observation())
    assert row.observed_at.utcoffset().total_seconds() == 0
    assert str(row.nonce) not in repr(row)
    with pytest.raises(ValidationError):
        row.generation = 2


KINDS = ("package", "pharmacy_label", "prescription", "reference_photo", "comparison_photo", "source_preview_photo")


@pytest.mark.parametrize("kind", KINDS)
def test_every_image_purpose_has_the_native_eight_million_byte_limit(kind):
    validate = contract("workflow_attachments", "validate_original_metadata")
    assert validate(kind, "image/png", 8_000_000) is None
    with pytest.raises(ValueError):
        validate(kind, "image/png", 8_000_001)
    with pytest.raises(ValueError):
        validate(kind, "application/pdf", 42)


def test_pdf_has_its_own_native_limit_and_mime():
    validate = contract("workflow_attachments", "validate_original_metadata")
    assert validate("library_pdf", "application/pdf", 10 * 1024 * 1024) is None
    for mime, size in [
        ("application/pdf", 10 * 1024 * 1024 + 1),
        ("image/jpeg", 42),
        ("application/pdf", 0),
        ("application/pdf", True),
    ]:
        with pytest.raises(ValueError):
            validate("library_pdf", mime, size)


def test_existing_attachment_dto_rejects_oversized_photo_before_persistence():
    owner, task, attachment = uuid4(), uuid4(), uuid4()
    values = dict(
        id=attachment,
        owner=owner,
        task_id=task,
        upload_id=uuid4(),
        binding_revision=1,
        object_ref=f"{owner}/workflow-originals/{task}/{attachment}",
        original_checksum="a" * 64,
        content_type="image/png",
        source_kind="reference_photo",
        byte_size=8_000_001,
    )
    with pytest.raises(ValidationError):
        OriginalAttachment(**values)


def test_write_binding_is_not_confirmation_or_patient_identity():
    cls = contract("workflow_persistence", "WorkflowWriteBinding")
    values = dict(
        task_id=uuid4(),
        task_revision=1,
        capability_id="observation.add",
        action_key=uuid4(),
        prepared_ref=BusinessRef(kind="care_review", id=uuid4()),
        expected_domain_revision=0,
    )
    parsed = cls(**values)
    assert parsed.run_binding is None
    for extra in [
        {"owner": uuid4()},
        {"confirmed": True},
        {"task_revision": True},
        {"task_revision": "1"},
        {"expected_domain_revision": -1},
    ]:
        with pytest.raises(ValidationError):
            cls(**(values | extra))


def test_native_result_preserves_original_typed_response_separate_from_receipt():
    receipt_cls = contract("workflow_persistence", "BusinessWriteReceipt")
    result_cls = contract("workflow_persistence", "NativeWriteResult")
    receipt = receipt_cls(
        owner=uuid4(),
        task_id=uuid4(),
        action_key=uuid4(),
        capability_id="medication.enroll",
        binding_revision=1,
        business_ref=BusinessRef(kind="regimen", id=uuid4()),
        domain_revision=0,
        outcome="prepared",
        recorded_at=datetime(2026, 10, 28, tzinfo=UTC),
    )
    result = result_cls[BusinessRef](receipt=receipt, result=receipt.business_ref)
    assert result.result == receipt.business_ref and result.receipt.outcome == "prepared"
    assert "result" not in receipt.model_dump()
    with pytest.raises(ValidationError):
        receipt_cls(**(receipt.model_dump() | {"body": "DEMO-private-body"}))


def test_ticket_is_bound_to_canonical_task_attachment_and_one_writer():
    cls = contract("workflow_verification", "StorageOperationTicket")
    owner, task, attachment = uuid4(), uuid4(), uuid4()
    values = dict(
        ticket_id=uuid4(),
        nonce=uuid4(),
        task_id=task,
        attachment_id=attachment,
        writer_id=uuid4(),
        operation="upload",
        generation=1,
        object_ref=f"{owner}/workflow-originals/{task}/{attachment}",
        expected_checksum="a" * 64,
        content_type="image/png",
        byte_size=42,
        expires_at=datetime(2026, 10, 28, tzinfo=UTC),
    )
    parsed = cls(**values)
    assert parsed.task_id == task and str(parsed.nonce) not in repr(parsed)
    for extra in [
        {"object_ref": f"{owner}/workflow-originals/{uuid4()}/{attachment}"},
        {"writer_id": None},
        {"generation": True},
        {"byte_size": 8_000_001},
        {"operation": "delete"},
    ]:
        with pytest.raises(ValidationError):
            cls(**(values | extra))
    assert cls(**(values | {"operation": "delete", "writer_id": None})).operation == "delete"


def test_run_binding_epoch_is_positive_and_does_not_embed_mutable_run_state():
    cls = contract("workflow_persistence", "RunWriteBinding")
    for epoch in [0, -1, True, "1"]:
        with pytest.raises(ValidationError):
            cls(run_id=uuid4(), epoch=epoch)
    assert set(cls(run_id=uuid4(), epoch=1).model_dump()) == {"run_id", "epoch"}
