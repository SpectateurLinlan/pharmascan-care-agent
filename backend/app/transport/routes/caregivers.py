"""Authenticated private contact CRUD, without delivery or access delegation."""

from uuid import UUID

from fastapi import APIRouter, Depends

from ...application.caregivers import CaregiverService
from ...contracts.caregivers import CaregiverContact, CaregiverCreate, CaregiverDetails
from ...domain.errors import ProviderUnavailableError
from ...timing import timed_stage
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal

router = APIRouter(prefix="/api/me/caregivers", tags=["caregivers"])


def service(container: ApplicationContainer = Depends(get_container)) -> CaregiverService:
    if container.caregivers is None:
        raise ProviderUnavailableError("Caregiver contacts are unavailable.")
    return container.caregivers


@router.get("", response_model=list[CaregiverContact])
def list_contacts(
    principal: AuthenticatedPrincipal = Depends(get_principal), application: CaregiverService = Depends(service)
):
    with timed_stage("business"):
        return application.list(principal.patient_id)


@router.post("", response_model=CaregiverContact)
def create_contact(
    payload: CaregiverCreate,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    application: CaregiverService = Depends(service),
):
    return application.create(principal.patient_id, payload)


@router.put("/{contact_id}", response_model=CaregiverContact)
def update_contact(
    contact_id: UUID,
    payload: CaregiverDetails,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    application: CaregiverService = Depends(service),
):
    return application.update(principal.patient_id, contact_id, payload)


@router.delete("/{contact_id}")
def delete_contact(
    contact_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    application: CaregiverService = Depends(service),
):
    application.delete(principal.patient_id, contact_id)
    return {"deleted": True}
