"""Read-only selected-regimen visual check. No unsafe catalogue-to-reference promotion."""

from uuid import UUID

from ..contracts.enums import RegimenState
from ..contracts.reference_eligibility import ReferenceContext
from ..contracts.visual_check import VisualCheckRequest, VisualCheckResult, VisualEvidencePort
from ..domain.errors import NotFoundError, ValidationError
from ..domain.reference_policy import reference_eligibility
from .enrollment import MedicationEnrollmentService


class VisualCheckService:
    def __init__(self, *, provider: VisualEvidencePort):
        self._provider = provider

    def prepare_upload(
        self, *, patient_id: UUID, regimen_id: UUID | None, enrollment: MedicationEnrollmentService
    ) -> VisualCheckRequest:
        if regimen_id:
            row = enrollment.get_regimen(patient_id, regimen_id)
            if row is None or row.state != RegimenState.ACTIVE:
                raise NotFoundError("Select an owned reviewed active medication")
        return VisualCheckRequest(regimen_id=str(regimen_id) if regimen_id else None)

    def check(
        self,
        *,
        patient_id: UUID,
        regimen_id: UUID | None,
        image: bytes,
        consent: bool,
        demo_only: bool,
        enrollment: MedicationEnrollmentService,
    ) -> VisualCheckResult:
        if not consent:
            raise ValidationError("Agree to image processing before comparing this photo")
        name = None
        if regimen_id is not None:
            regimen = enrollment.get_regimen(patient_id, regimen_id)
            if regimen is None:
                raise NotFoundError("Selected regimen not found")
            if regimen.state != RegimenState.ACTIVE:
                raise ValidationError("Select a reviewed active regimen")
            medication = enrollment.get_medication(patient_id, regimen.patient_medication_id)
            name = medication.display_name if medication else None
        evidence = self._provider.inspect(image)
        if regimen_id is not None:
            eligibility = reference_eligibility(
                ReferenceContext(
                    patient_id=patient_id,
                    medication_id=regimen.patient_medication_id,
                    reference_kind="catalogue_seeded_candidate",
                    regimen_state="active",
                ),
                patient_id=patient_id,
                medication_id=regimen.patient_medication_id,
                model=evidence.model,
            )
            # Catalogues cannot become patient references without reviewed
            # product mapping and usage permission, neither available here.
            if eligibility.eligible_for_current_match or eligibility.can_seed_candidate:
                raise ValidationError("Catalogue mapping must be reviewed before use")
        unclear = (
            evidence.detection.input_abstained
            or evidence.detection.overlapping_boxes
            or evidence.detection.pill_count != 1
        )
        # This slice has no stored reviewed loose-pill references or confirmed
        # catalogue product mapping. Eligibility is unavailable, never fabricated.
        return VisualCheckResult(
            decision="ambiguous" if unclear else "unknown",
            selected_medication=name,
            reason="Image needs review"
            if unclear
            else "No eligible reviewed personal reference is available for comparison",
            candidates=evidence.candidates,
            count_reliable=evidence.detection.provider_count_reliable,
        )
