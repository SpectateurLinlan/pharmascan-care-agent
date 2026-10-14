"""Owned feedback submissions; no external contact or medical advice delivery."""

from fastapi import APIRouter, Depends

from ...contracts.patient_feedback import FeedbackInput
from ...domain.errors import ProviderUnavailableError
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


@router.post("")
def submit(
    payload: FeedbackInput,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    if container.feedback is None:
        raise ProviderUnavailableError("Feedback is unavailable")
    row = container.feedback.submit(principal.patient_id, payload)
    return {"id": row.id, "created_at": row.created_at, "status": "received"}
