"""Independent source review must not partially write or silently accept changed inputs."""

import pytest
from app.contracts.dto import FrequencyRuleDTO, RegimenDraftInput
from app.domain.errors import ValidationError

from .test_workflow_sources import inputs, provider


def review(h, task, amount=1, **changes):
    return h.container.evidence_enrollment.prepare_review(
        patient_id=h.owner_ids["A"],
        task_id=task.id,
        patient_reviewed=True,
        distinct_product_confirmed=False,
        draft=RegimenDraftInput(
            medication_name=task.product.name,
            dose_amount=amount,
            dose_unit="tablet",
            frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["08:00"]),
        ),
        **changes,
    )


def test_incomplete_source_review_leaves_original_evidence_and_clinical_records_unchanged(workflow, monkeypatch):
    h = workflow
    provider(h, monkeypatch)
    task = h.container.evidence_enrollment.attach(**inputs(h))
    before = h.snapshot()
    with pytest.raises(ValidationError):
        h.container.evidence_enrollment.prepare_review(
            patient_id=h.owner_ids["A"],
            task_id=task.id,
            patient_reviewed=True,
            distinct_product_confirmed=False,
            draft=RegimenDraftInput(medication_name=task.product.name, dose_amount=1, dose_unit="tablet"),
        )
    after = h.snapshot()
    assert after["sources"] == before["sources"] and after["source_fields"] == before["source_fields"]
    assert after["regimens"] == before["regimens"] and after["medications"] == before["medications"]


def test_source_review_replay_cannot_silently_acknowledge_a_different_dose(workflow, monkeypatch):
    h = workflow
    provider(h, monkeypatch)
    task = h.container.evidence_enrollment.attach(**inputs(h))
    saved = review(h, task)
    before = h.snapshot()
    with pytest.raises(ValidationError):
        review(h, task, amount=2)
    assert h.snapshot()["regimens"] == before["regimens"]
    assert review(h, task).draft_regimen_id == saved.draft_regimen_id
    assert len(h.snapshot()["regimens"]) == 1 and h.snapshot()["regimens"][0]["state"] == "draft"
    assert not h.snapshot()["dose_events"]


def test_failed_source_review_task_update_rolls_back_the_clinical_draft_and_review_flags(workflow, monkeypatch):
    h = workflow
    provider(h, monkeypatch)
    task = h.container.evidence_enrollment.attach(**inputs(h))
    before = h.snapshot()

    def failed(*args):
        raise OSError("DEMO evidence persistence unavailable")

    monkeypatch.setattr(h.container.evidence_enrollment._repo, "update_task", failed)
    with pytest.raises(OSError, match="DEMO evidence persistence unavailable"):
        review(h, task)
    after = h.snapshot()
    assert after["sources"] == before["sources"] and after["source_fields"] == before["source_fields"]
    assert after["regimens"] == before["regimens"] and after["medications"] == before["medications"]


def test_an_orphaned_source_draft_bound_to_another_workflow_requires_its_original_review(workflow, monkeypatch):
    from uuid import uuid4

    from app.contracts.assistant_workflows import BusinessRef, WorkflowTask
    from app.domain.errors import StaleVersionError

    from .test_workflow_enrollment_operations import services

    h = workflow
    provider(h, monkeypatch)
    task = h.container.evidence_enrollment.attach(**inputs(h))
    draft = RegimenDraftInput(
        medication_name=task.product.name,
        dose_amount=1,
        dose_unit="tablet",
        frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["08:00"]),
    )
    result = h.container.enrollment.enroll_draft(
        patient_id=h.owner_ids["A"], draft=draft, existing_medication_id=task.medication_id, evidence_task_id=task.id
    )
    original = h.container.assistant_workflows._repository.create(
        WorkflowTask(
            id=uuid4(),
            owner=h.owner_ids["A"],
            workspace_id=uuid4(),
            capability_id="medication.enroll",
            state="awaiting_confirmation",
            save_mode="allowed",
            storage_state="saved",
            updated_at=h.clock.now(),
            business_refs=(BusinessRef(kind="regimen", id=result.regimen.id, version=result.regimen.version_no),),
        )
    )
    operation, _ = services(h)
    operation.bind_existing_once(
        h.owner_ids["A"],
        result.regimen.id,
        result.regimen.version_no,
        action_key=uuid4(),
        workflow_task_id=original.id,
        workflow_revision=original.revision,
    )
    before = h.snapshot()
    with pytest.raises(StaleVersionError):
        review(h, task)
    assert h.snapshot()["sources"] == before["sources"]


@pytest.mark.parametrize("strength", ["500mg", "500.0MG", "0.5g"])
def test_cosmetic_or_different_unit_strength_cannot_establish_a_distinct_duplicate_product(
    workflow, monkeypatch, strength
):
    h = workflow
    replay = provider(h, monkeypatch)
    first = h.container.evidence_enrollment.attach(**inputs(h))
    replay.strength = strength
    second = h.container.evidence_enrollment.attach(**inputs(h))
    assert first.medication_id in second.possible_duplicate_ids
    before = h.snapshot()
    with pytest.raises(ValidationError):
        h.container.evidence_enrollment.prepare_review(
            patient_id=h.owner_ids["A"],
            task_id=second.id,
            patient_reviewed=True,
            distinct_product_confirmed=True,
            draft=RegimenDraftInput(
                medication_name=second.product.name,
                dose_amount=1,
                dose_unit="tablet",
                frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["08:00"]),
            ),
        )
    assert h.snapshot()["regimens"] == before["regimens"]
    assert h.snapshot()["source_fields"] == before["source_fields"]
