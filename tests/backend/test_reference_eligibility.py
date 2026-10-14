"""Pure policy tests; high similarity never upgrades eligibility or authority."""

from uuid import UUID

import pytest
from app.contracts.reference_eligibility import ReferenceContext
from app.contracts.vision import ModelMetadata
from app.domain.reference_policy import reference_eligibility

MODEL = ModelMetadata(
    api_version="0.8.0",
    model_version="DEMO-model",
    embedding_space_id="DEMO-space",
    preprocessing_version="DEMO-preprocess",
    dimension=256,
    normalized=True,
    crop_window=0.8,
    threshold=0.9,
    margin=0.1,
    calibration_json="SIMULATED only",
    training_coverage="DEMO",
    known_limits=[],
)
REF = ReferenceContext(
    patient_id=UUID(int=1),
    medication_id=UUID(int=2),
    reference_kind="patient_loose_pill",
    regimen_state="active",
    reviewed=True,
    model_version=MODEL.model_version,
    embedding_space_id=MODEL.embedding_space_id,
    preprocessing_version=MODEL.preprocessing_version,
    dimension=MODEL.dimension,
    normalized=MODEL.normalized,
)


@pytest.mark.parametrize(
    "change",
    [
        {"regimen_state": "ended"},
        {"regimen_state": "superseded"},
        {"regimen_state": "draft"},
        {"reference_kind": "package"},
        {"reviewed": False},
        {"model_version": "old"},
        {"embedding_space_id": "old"},
        {"preprocessing_version": "old"},
        {"dimension": 128},
        {"normalized": False},
        {"patient_id": UUID(int=3)},
        {"medication_id": UUID(int=3)},
    ],
)
def test_ineligible_reference_cannot_become_current_dose_evidence(change):
    result = reference_eligibility(
        REF.model_copy(update=change), patient_id=REF.patient_id, medication_id=REF.medication_id, model=MODEL
    )
    assert not result.eligible_for_current_match and not result.proves_identity and not result.proves_ingestion


@pytest.mark.parametrize("mapped,licensed,can_seed", [(False, False, False), (True, False, False), (True, True, True)])
def test_catalogue_requires_mapping_and_permitted_use_and_remains_candidate(mapped, licensed, can_seed):
    ref = REF.model_copy(
        update={
            "reference_kind": "catalogue_seeded_candidate",
            "product_mapping_confirmed": mapped,
            "usage_permitted": licensed,
        }
    )
    result = reference_eligibility(ref, patient_id=REF.patient_id, medication_id=REF.medication_id, model=MODEL)
    assert result.can_seed_candidate is can_seed and not result.eligible_for_current_match


def test_current_compatible_reference_is_visual_only():
    result = reference_eligibility(REF, patient_id=REF.patient_id, medication_id=REF.medication_id, model=MODEL)
    assert result.eligible_for_current_match and not result.proves_identity and not result.proves_ingestion
