"""No image/class/model score can independently authorize a dose."""

from uuid import UUID

from ..contracts.reference_eligibility import ReferenceContext, ReferenceEligibility
from ..contracts.vision import ModelMetadata


def reference_eligibility(
    reference: ReferenceContext,
    *,
    patient_id: UUID,
    medication_id: UUID,
    model: ModelMetadata,
) -> ReferenceEligibility:
    reason = "eligible_visual_reference_only"
    if reference.patient_id != patient_id or reference.medication_id != medication_id:
        reason = "different_owner_or_product"
    elif reference.regimen_state != "active":
        reason = "historical_or_unreviewed_regimen"
    elif reference.reference_kind == "package":
        reason = "package_outside_loose_pill_space"
    elif reference.reference_kind == "catalogue_seeded_candidate":
        return ReferenceEligibility(
            eligible_for_current_match=False,
            can_seed_candidate=reference.product_mapping_confirmed and reference.usage_permitted,
            reason="catalogue_candidate_is_not_patient_verified",
        )
    elif not reference.reviewed:
        reason = "patient_reference_not_reviewed"
    elif (
        reference.model_version,
        reference.embedding_space_id,
        reference.preprocessing_version,
        reference.dimension,
        reference.normalized,
    ) != (
        model.model_version,
        model.embedding_space_id,
        model.preprocessing_version,
        model.dimension,
        model.normalized,
    ):
        reason = "incompatible_embedding_metadata"
    return ReferenceEligibility(eligible_for_current_match=reason == "eligible_visual_reference_only", reason=reason)
