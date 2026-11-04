"""Source preparation/publication over real owned services; synthetic extraction only."""

from dataclasses import replace
from uuid import uuid4

import pytest
from app.application.source_preview import SourcePreviewService
from app.contracts.enums import IdentityStatus, SourceKind
from app.domain.errors import NotFoundError, StaleVersionError, ValidationError

from .test_medication_evidence import Label
from .test_workflow_originals import original_png


def provider(h, monkeypatch):
    replay = Label()
    monkeypatch.setattr(
        h.container.evidence_enrollment, "_preview", SourcePreviewService(provider=replay, ids=h.container.ids)
    )
    return replay


def inputs(h, **changes):
    return dict(
        patient_id=h.owner_ids["A"],
        task_id=uuid4(),
        image=original_png(),
        source_kind="pharmacy_label",
        medication_id=None,
        consent=True,
        demo_only=True,
        **changes,
    )


def test_foreign_or_missing_medication_is_rejected_before_any_source_or_field_is_written(workflow, monkeypatch):
    h = workflow
    provider(h, monkeypatch)
    before = h.snapshot()
    values = inputs(h)
    values["medication_id"] = uuid4()
    with pytest.raises(NotFoundError):
        h.container.evidence_enrollment.attach(**values)
    after = h.snapshot()
    assert after["sources"] == before["sources"] and after["source_fields"] == before["source_fields"]
    assert after["medications"] == before["medications"]


def test_source_preparation_retains_typed_evidence_without_publishing_clinical_or_image_records(workflow, monkeypatch):
    h = workflow
    provider(h, monkeypatch)
    before = h.snapshot()
    prepared = h.container.evidence_enrollment.prepare_attachment(**inputs(h))
    assert prepared.source.extraction_evidence is not None and prepared.task.version == 2
    assert prepared.source.id in prepared.task.source_ids
    after = h.snapshot()
    assert after["sources"] == before["sources"] and after["medications"] == before["medications"]
    assert after["source_fields"] == before["source_fields"] and not h.container.evidence_enrollment.list(
        h.owner_ids["A"]
    )


def test_source_publication_checks_every_row_owner_before_any_rows_are_visible(workflow, monkeypatch):
    h = workflow
    provider(h, monkeypatch)
    prepared = h.container.evidence_enrollment.prepare_attachment(**inputs(h))
    foreign = prepared.fields[0].model_copy(update={"patient_id": h.owner_ids["B"]})
    with pytest.raises(ValidationError):
        h.container.evidence_enrollment.publish_attachment(h.owner_ids["A"], replace(prepared, fields=(foreign,)))
    assert not h.snapshot()["sources"] and not h.snapshot()["medications"]
    assert not h.snapshot()["source_fields"]


def test_source_publication_refuses_a_stale_clinical_snapshot_without_partial_writes(workflow, monkeypatch):
    h = workflow
    provider(h, monkeypatch)
    prepared = h.container.evidence_enrollment.prepare_attachment(**inputs(h))
    h.seed_reviewed_medication()
    before = h.snapshot()
    with pytest.raises(StaleVersionError):
        h.container.evidence_enrollment.publish_attachment(h.owner_ids["A"], prepared)
    assert h.snapshot()["sources"] == before["sources"]
    assert h.snapshot()["medications"] == before["medications"]


def test_response_loss_replay_reads_the_same_real_source_and_never_republishes_it(workflow, monkeypatch):
    h = workflow
    provider(h, monkeypatch)
    prepared = h.container.evidence_enrollment.prepare_attachment(**inputs(h))
    key = uuid4()
    saved = h.container.evidence_enrollment.publish_attachment(h.owner_ids["A"], prepared, action_key=key)
    before = h.snapshot()
    replay = h.container.evidence_enrollment.publish_attachment(h.owner_ids["A"], prepared, action_key=key)
    assert replay == saved
    assert h.snapshot()["sources"] == before["sources"] and len(h.snapshot()["medications"]) == 1
    assert len(h.container.evidence_enrollment.sources(h.owner_ids["A"], saved.id)) == 1


def test_derived_image_content_must_match_the_source_checksum_before_publication(workflow, monkeypatch):
    h = workflow
    provider(h, monkeypatch)
    prepared = h.container.evidence_enrollment.prepare_attachment(**inputs(h))
    with pytest.raises(ValidationError):
        h.container.evidence_enrollment.publish_attachment(
            h.owner_ids["A"], replace(prepared, derived_image=b"DEMO changed bytes")
        )
    assert not h.snapshot()["sources"] and not h.snapshot()["medications"]


def test_reusing_a_saved_photo_cannot_silently_change_its_source_authority(workflow, monkeypatch):
    h = workflow
    provider(h, monkeypatch)
    values = inputs(h)
    saved = h.container.evidence_enrollment.attach(**values)
    before = h.snapshot()
    with pytest.raises(ValidationError):
        h.container.evidence_enrollment.attach(**{**values, "task_id": saved.id, "source_kind": "package"})
    assert h.snapshot()["sources"] == before["sources"]


def test_failed_private_image_staging_leaves_no_visible_source_medication_or_task(workflow, monkeypatch):
    h = workflow
    provider(h, monkeypatch)
    service = h.container.evidence_enrollment
    prepared = service.prepare_attachment(**inputs(h))

    def unavailable(*args):
        raise OSError("DEMO private image storage unavailable")

    monkeypatch.setattr(service._storage, "stage_put", unavailable)
    with pytest.raises(OSError, match="DEMO private image"):
        service.publish_attachment(h.owner_ids["A"], prepared)
    assert not h.snapshot()["sources"] and not h.snapshot()["medications"] and not service.list(h.owner_ids["A"])
    with pytest.raises(KeyError):
        service._storage.get(prepared.image.storage_path)


def test_simultaneous_publications_of_the_same_source_return_one_real_owned_registration(workflow, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    h = workflow
    provider(h, monkeypatch)
    service = h.container.evidence_enrollment
    values = inputs(h)
    first, second = service.prepare_attachment(**values), service.prepare_attachment(**values)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda prepared: service.publish_attachment(h.owner_ids["A"], prepared), (first, second))
        )
    assert results[0] == results[1]
    assert len(h.snapshot()["medications"]) == len(h.snapshot()["sources"]) == 1


@pytest.mark.parametrize("corruption", ["field_source", "image_path", "reviewed_identity", "unexpected_version"])
def test_forged_typed_aggregate_cannot_publish_unrelated_or_reviewed_records(workflow, monkeypatch, corruption):
    h = workflow
    provider(h, monkeypatch)
    prepared = h.container.evidence_enrollment.prepare_attachment(**inputs(h))
    if corruption == "field_source":
        prepared = replace(prepared, fields=(prepared.fields[0].model_copy(update={"source_id": uuid4()}),))
    elif corruption == "image_path":
        prepared = replace(prepared, image=prepared.image.model_copy(update={"storage_path": "DEMO/foreign/path.png"}))
    elif corruption == "reviewed_identity":
        prepared = replace(
            prepared,
            medication=prepared.medication.model_copy(update={"identity_status": IdentityStatus.PROFESSIONAL_VERIFIED}),
        )
    else:
        prepared = replace(prepared, task=prepared.task.model_copy(update={"version": 99}))
    with pytest.raises(ValidationError):
        h.container.evidence_enrollment.publish_attachment(h.owner_ids["A"], prepared)
    assert not h.snapshot()["sources"] and not h.snapshot()["medications"]


def test_prepared_source_kind_cannot_disagree_with_its_actual_extraction(workflow, monkeypatch):
    from uuid import uuid5

    h = workflow
    provider(h, monkeypatch)
    prepared = h.container.evidence_enrollment.prepare_attachment(**inputs(h))
    changed_source = prepared.source.model_copy(update={"source_kind": SourceKind.PACKAGE})
    changed_image = prepared.image.model_copy(
        update={
            "id": uuid5(prepared.medication.id, prepared.image.checksum + "package"),
            "image_kind": "package",
            "source_description": "package",
        }
    )
    with pytest.raises(ValidationError):
        h.container.evidence_enrollment.publish_attachment(
            h.owner_ids["A"], replace(prepared, source=changed_source, image=changed_image)
        )
    assert not h.snapshot()["sources"]


def test_another_patients_source_task_id_cannot_be_claimed_as_a_new_owned_registration(workflow, monkeypatch):
    h = workflow
    provider(h, monkeypatch)
    values = inputs(h)
    first = h.container.evidence_enrollment.attach(**values)
    before = h.snapshot()
    with pytest.raises((NotFoundError, ValidationError)):
        h.container.evidence_enrollment.attach(**{**values, "patient_id": h.owner_ids["B"]})
    assert h.container.evidence_enrollment.get(h.owner_ids["A"], first.id) == first
    assert h.snapshot()["sources"] == before["sources"]
    assert not h.container.evidence_enrollment.list(h.owner_ids["B"])


def test_supplementing_a_manual_medication_with_a_different_recorded_strength_remains_a_conflict(workflow, monkeypatch):
    from uuid import UUID

    h = workflow
    task = h.start(
        "medication.enroll",
        {
            "method": "manual",
            "medication_name": "DEMO strength identity",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_rule": {"kind": "daily", "local_times": ["08:00"]},
            "dose_basis": {"strength_text": "500mg"},
        },
    )
    prepared = h.event(task["task_id"], "prepare_confirmation")
    regimen = h.container.enrollment.get_regimen(h.owner_ids["A"], UUID(prepared["result_ref"]["id"]))
    replay = provider(h, monkeypatch)
    replay.name, replay.strength = "DEMO strength identity", "250mg"
    saved = h.container.evidence_enrollment.attach(**{**inputs(h), "medication_id": regimen.patient_medication_id})
    assert saved.status == "conflict" and any(row.startswith("strength:") for row in saved.conflicts)
    original = h.container.enrollment.get_source(h.owner_ids["A"], regimen.source_id)
    assert original.dose_basis.strength_text == "500mg" and original.reviewed_at is None


def manual_identity(h):
    from uuid import UUID

    task = h.start(
        "medication.enroll",
        {
            "method": "manual",
            "medication_name": "DEMO normalized source",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_rule": {"kind": "daily", "local_times": ["08:00"]},
            "dose_basis": {"strength_text": "500mg", "form": "tablet"},
        },
    )
    prepared = h.event(task["task_id"], "prepare_confirmation")
    return h.container.enrollment.get_regimen(h.owner_ids["A"], UUID(prepared["result_ref"]["id"]))


@pytest.mark.parametrize("strength", ["500 mg", "500.0MG", "５００ｍｇ"])
def test_cosmetic_strength_formatting_does_not_create_a_conflict_or_rewrite_original_evidence(
    workflow, monkeypatch, strength
):
    h = workflow
    regimen = manual_identity(h)
    replay = provider(h, monkeypatch)
    replay.name, replay.strength = "DEMO normalized source", strength
    saved = h.container.evidence_enrollment.attach(**{**inputs(h), "medication_id": regimen.patient_medication_id})
    assert not saved.conflicts
    assert h.container.enrollment.get_source(h.owner_ids["A"], regimen.source_id).dose_basis.strength_text == "500mg"


def test_source_form_difference_against_a_manual_identity_requires_reconciliation(workflow, monkeypatch):
    from app.contracts.source_extraction import PrintedEvidence

    class Capsule(Label):
        name, strength = "DEMO normalized source", "500mg"

        def extract_medication_source(self, **kwargs):
            result = super().extract_medication_source(**kwargs)
            candidate = result.candidates[0]
            return result.model_copy(
                update={
                    "candidates": [
                        candidate.model_copy(
                            update={
                                "product": candidate.product.model_copy(
                                    update={"dose_form": PrintedEvidence(value="capsule", line="DEMO capsule")}
                                ),
                            }
                        )
                    ]
                }
            )

    h = workflow
    regimen = manual_identity(h)
    monkeypatch.setattr(
        h.container.evidence_enrollment, "_preview", SourcePreviewService(provider=Capsule(), ids=h.container.ids)
    )
    saved = h.container.evidence_enrollment.attach(**{**inputs(h), "medication_id": regimen.patient_medication_id})
    assert saved.status == "conflict" and any(row.startswith("dose_form:") for row in saved.conflicts)
