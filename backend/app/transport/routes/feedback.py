"""Owned feedback submissions; no external contact or medical advice delivery."""

from fastapi import APIRouter, Depends

from ...contracts.patient_feedback import FeedbackInput
from ...domain.errors import ProviderUnavailableError
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal
from ..workflow_binding import native_binding

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


@router.post("")
def submit(
    payload: FeedbackInput,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
    binding=Depends(native_binding),
):
    if container.feedback is None:
        raise ProviderUnavailableError("Feedback is unavailable")
    def write():
        row = container.feedback.submit(principal.patient_id, payload)
        return {"id": row.id, "created_at": row.created_at, "status": "received"}
    if binding:
        if container.assistant_feedback is None:
            raise ProviderUnavailableError("Feedback workflows are unavailable")
        return container.assistant_feedback.run(principal.patient_id, *binding[:2], "feedback.submit",
            payload.id, payload, binding[2], write)
    return write()
