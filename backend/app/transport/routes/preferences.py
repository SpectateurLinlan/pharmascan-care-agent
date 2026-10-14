"""Identity comes exclusively from the verified principal."""

from fastapi import APIRouter, Depends

from ...contracts.preferences import Preferences, PreferenceUpdate
from ...domain.errors import ProviderUnavailableError
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
):
    if container.preferences is None:
        raise ProviderUnavailableError("Preferences unavailable")
    return container.preferences.save(principal.patient_id, payload)
