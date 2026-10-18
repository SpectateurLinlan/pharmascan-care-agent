"""Resolve navigation references through the enrollment public service."""

from ..contracts.navigation_context import NavigationContext, NavigationInput
from ..domain.errors import NotFoundError


def resolve_navigation(enrollment, owner, source: NavigationInput) -> NavigationContext:
    medication_id = source.medication_id
    if source.regimen_id:
        regimen = enrollment.get_regimen(owner, source.regimen_id)
        if regimen is None or (medication_id is not None and regimen.patient_medication_id != medication_id):
            raise NotFoundError("Navigation record unavailable for this patient")
        medication_id = regimen.patient_medication_id
    medication = enrollment.get_medication(owner, medication_id) if medication_id else None
    if medication_id and medication is None:
        raise NotFoundError("Navigation record unavailable for this patient")
    return NavigationContext(
        page=source.page,
        medication_id=medication_id,
        regimen_id=source.regimen_id,
        display_name=medication.display_name if medication else None,
    )
