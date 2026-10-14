"""Own demo allowance only; no public counter mutation endpoint."""

from fastapi import APIRouter, Depends

from ...contracts.quota import Usage
from ...domain.errors import ProviderUnavailableError
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/usage", response_model=Usage)
def usage(
    principal: AuthenticatedPrincipal = Depends(get_principal), container: ApplicationContainer = Depends(get_container)
):
    if container.ai_agent is None:
        raise ProviderUnavailableError("AI demo allowance unavailable")
    return container.ai_agent.usage(principal.patient_id)
