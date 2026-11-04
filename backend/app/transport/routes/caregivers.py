"""Authenticated private contact CRUD, without delivery or access delegation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from ...application.caregivers import CaregiverService
from ...contracts.caregivers import CaregiverContact, CaregiverCreate, CaregiverDetails
from ...domain.errors import ProviderUnavailableError, ValidationError
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
    container: ApplicationContainer = Depends(get_container),
    assistant_task: Annotated[UUID | None, Header(alias="X-Assistant-Task")] = None,
    assistant_revision: Annotated[int | None, Header(alias="X-Assistant-Revision", ge=1)] = None,
    patient_confirmed: Annotated[bool, Header(alias="X-Patient-Confirmed")] = False,
):
    return _bound(container, principal, assistant_task, assistant_revision, "caregiver.add", payload.id,
                  payload, patient_confirmed, lambda: application.create(principal.patient_id, payload))


@router.put("/{contact_id}", response_model=CaregiverContact)
def update_contact(
    contact_id: UUID,
    payload: CaregiverDetails,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    application: CaregiverService = Depends(service),
    container: ApplicationContainer = Depends(get_container),
    assistant_task: Annotated[UUID | None, Header(alias="X-Assistant-Task")] = None,
    assistant_revision: Annotated[int | None, Header(alias="X-Assistant-Revision", ge=1)] = None,
    patient_confirmed: Annotated[bool, Header(alias="X-Patient-Confirmed")] = False,
):
    return _bound(container, principal, assistant_task, assistant_revision, "caregiver.edit", contact_id,
                  payload, patient_confirmed, lambda: application.update(principal.patient_id, contact_id, payload))


@router.delete("/{contact_id}")
def delete_contact(
    contact_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    application: CaregiverService = Depends(service),
    container: ApplicationContainer = Depends(get_container),
    assistant_task: Annotated[UUID | None, Header(alias="X-Assistant-Task")] = None,
    assistant_revision: Annotated[int | None, Header(alias="X-Assistant-Revision", ge=1)] = None,
    patient_confirmed: Annotated[bool, Header(alias="X-Patient-Confirmed")] = False,
):
    def write():
        application.delete(principal.patient_id, contact_id)
        return {"deleted": True}
    return _bound(container, principal, assistant_task, assistant_revision, "caregiver.delete", contact_id,
                  None, patient_confirmed, write)


def _bound(container, principal, task_id, revision, capability, target, payload, confirmed, write):
    adapter = container.assistant_settings
    if task_id is None and revision is None:
        return adapter.run_unbound(principal.patient_id, write) if adapter else write()
    if task_id is None or revision is None or adapter is None:
        raise ValidationError("Use a complete current contact workflow binding")
    return adapter.run(principal.patient_id, task_id, revision, capability, target, payload, confirmed, write)
