"""Authenticated, consented read-only label preview. No activation side effects."""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from starlette.concurrency import run_in_threadpool

from ...contracts.source_extraction import ImageRoute, MedicationSourceExtractionDTO
from ...domain.errors import ProviderUnavailableError, ValidationError
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal

router = APIRouter(prefix="/api/sources", tags=["source-preview"])


@router.post("/check-input", response_model=ImageRoute)
async def check_input(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
) -> ImageRoute:
    from .evidence import image_content

    content = await image_content(request)
    if not container.source_preview:
        raise ProviderUnavailableError("Image routing unavailable")
    return await run_in_threadpool(
        container.source_preview.route,
        content=content,
        consent=request.headers.get("x-stage2-consent") == "true",
        demo_only=request.headers.get("x-demo-only") == "true",
    )


@router.post("/preview", response_model=MedicationSourceExtractionDTO)
async def preview(
    request: Request,
    source_kind: Literal["package", "pharmacy_label"] = Query(),
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
) -> MedicationSourceExtractionDTO:
    mime = request.headers.get("content-type", "").split(";")[0]
    if mime not in ("image/png", "image/jpeg"):
        raise ValidationError("Synthetic PNG/JPEG images only; use manual entry for PDF/prescription")
    if container.source_preview is None:
        raise ProviderUnavailableError("Label extraction is unavailable; use manual enrollment")
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 8_000_000:
            raise ValidationError("Image exceeds upload limit")
    expected = b"\x89PNG\r\n\x1a\n" if mime == "image/png" else b"\xff\xd8"
    if not content.startswith(expected):
        raise ValidationError("Image MIME does not match its content signature")
    return await run_in_threadpool(
        container.source_preview.preview,
        content=bytes(content),
        source_kind=source_kind,
        consent=request.headers.get("x-stage2-consent") == "true",
        demo_only=request.headers.get("x-demo-only") == "true",
    )
