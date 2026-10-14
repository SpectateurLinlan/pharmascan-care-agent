"""Authenticated image evidence request through application service."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from starlette.concurrency import run_in_threadpool

from ...contracts.visual_check import VisualCheckResult
from ...domain.errors import ProviderUnavailableError, ValidationError
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal

router = APIRouter(prefix="/api/visual-check", tags=["visual-check"])


@router.post("", response_model=VisualCheckResult)
async def check(
    request: Request,
    regimen_id: UUID | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    mime = request.headers.get("content-type", "").split(";")[0]
    if mime not in {"image/png", "image/jpeg"}:
        raise ValidationError("Use PNG/JPEG")
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 8_000_000:
            raise ValidationError("Image exceeds size limit")
    if container.visual_check is None:
        raise ProviderUnavailableError("Visual evidence unavailable; review your instructions")
    signature = bytes(content[:8])
    if (mime == "image/png" and signature != b"\x89PNG\r\n\x1a\n") or (
        mime == "image/jpeg" and not signature.startswith(b"\xff\xd8\xff")
    ):
        raise ValidationError("Image content does not match its type")
    return await run_in_threadpool(
        container.visual_check.check,
        patient_id=principal.patient_id,
        regimen_id=regimen_id,
        image=bytes(content),
        consent=request.headers.get("x-stage2-consent") == "true",
        demo_only=request.headers.get("x-demo-only") == "true",
        enrollment=container.enrollment,
    )
