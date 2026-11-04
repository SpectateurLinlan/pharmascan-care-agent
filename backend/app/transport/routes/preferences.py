"""Identity comes exclusively from the verified principal."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from ...contracts.preferences import Preferences, PreferenceUpdate
from ...domain.errors import ProviderUnavailableError, ValidationError
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal

router = APIRouter(prefix="/api/me/preferences", tags=["preferences"])


@router.get("", response_model=Preferences)
def get_preferences(
    principal: AuthenticatedPrincipal = Depends(get_principal), container: ApplicationContainer = Depends(get_container)
):
    if container.preferences is None:
        raise ProviderUnavailableError("Preferences unavailable")
    return container.preferences.get(principal.patient_id)


@router.put("", response_model=Preferences)
def update_preferences(
    payload: PreferenceUpdate,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
    assistant_task: Annotated[UUID | None, Header(alias="X-Assistant-Task")] = None,
    assistant_revision: Annotated[int | None, Header(alias="X-Assistant-Revision", ge=1)] = None,
    patient_confirmed: Annotated[bool, Header(alias="X-Patient-Confirmed")] = False,
):
    if container.preferences is None:
        raise ProviderUnavailableError("Preferences unavailable")
    def write():
        return container.preferences.save(principal.patient_id, payload)

    service = container.assistant_reminder_writes
    if assistant_task is not None or assistant_revision is not None:
        if assistant_task is not None and assistant_revision is not None and container.assistant_settings is not None:
            view = container.assistant_settings.workflows.view(principal.patient_id, assistant_task)
            if view.capability_id in container.assistant_settings.adapters:
                return container.assistant_settings.run(principal.patient_id, assistant_task, assistant_revision,
                    view.capability_id, None, payload, patient_confirmed, write)
        if service is None or assistant_task is None or assistant_revision is None:
            raise ValidationError("Use a complete current reminder task binding")
        return service.run(principal.patient_id, assistant_task, assistant_revision, "reminder.settings",
                           payload, patient_confirmed, write)
    return service.run_unbound(principal.patient_id, write) if service else write()
