"""Typed patient evidence APIs. All identity comes from verified AuthContext."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

from ...contracts.dto import RegimenDraftInput
from ...contracts.medication_evidence import EnrollmentTask, MedicationImage, RecognitionRun, SourceEvidenceView
from ...domain.errors import ProviderUnavailableError, ValidationError
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal

router = APIRouter(prefix="/api/evidence", tags=["patient-evidence"])


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft: RegimenDraftInput
    patient_reviewed: bool
    distinct_product_confirmed: bool = False
    product_category: Literal["unknown", "POM", "P", "GSL", "supplement"] = "unknown"
    replace_active_plan: bool = False


async def image_content(request: Request) -> bytes:
    mime = request.headers.get("content-type", "").split(";")[0]
    if mime not in {"image/png", "image/jpeg"}:
        raise ValidationError("Use a PNG/JPEG label or package photo. PDF parsing is not available.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 8_000_000:
            raise ValidationError("Image exceeds size limit")
    if (mime == "image/png" and not body.startswith(b"\x89PNG\r\n\x1a\n")) or (
        mime == "image/jpeg" and not body.startswith(b"\xff\xd8\xff")
    ):
        raise ValidationError("Image content does not match its type")
    return bytes(body)


@router.get("/tasks", response_model=list[EnrollmentTask])
def tasks(
    principal: AuthenticatedPrincipal = Depends(get_principal), container: ApplicationContainer = Depends(get_container)
):
    if not container.evidence_enrollment:
        raise ProviderUnavailableError("Evidence registration unavailable")
    return container.evidence_enrollment.list(principal.patient_id)


@router.get("/tasks/{task_id}", response_model=EnrollmentTask)
def task(
    task_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    return container.evidence_enrollment.get(principal.patient_id, task_id)


@router.get("/tasks/{task_id}/sources", response_model=list[SourceEvidenceView])
def sources(
    task_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    return container.evidence_enrollment.sources(principal.patient_id, task_id)


@router.post("/tasks/{task_id}/sources", response_model=EnrollmentTask)
async def attach(
    task_id: UUID,
    request: Request,
    source_kind: Literal["package", "pharmacy_label", "prescription"] = Query(),
    medication_id: UUID | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    content = await image_content(request)
    return await run_in_threadpool(
        container.evidence_enrollment.attach,
        patient_id=principal.patient_id,
        task_id=task_id,
        image=content,
        source_kind=source_kind,
        medication_id=medication_id,
        consent=request.headers.get("x-stage2-consent") == "true",
        demo_only=request.headers.get("x-demo-only") == "true",
    )


@router.post("/tasks/{task_id}/review", response_model=EnrollmentTask)
def review(
    task_id: UUID,
    payload: ReviewRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    return container.evidence_enrollment.prepare_review(
        patient_id=principal.patient_id,
        task_id=task_id,
        draft=payload.draft,
        patient_reviewed=payload.patient_reviewed,
        distinct_product_confirmed=payload.distinct_product_confirmed,
        product_category=payload.product_category,
        replace_active_plan=payload.replace_active_plan,
    )


@router.get("/gallery")
def gallery(
    principal: AuthenticatedPrincipal = Depends(get_principal), container: ApplicationContainer = Depends(get_container)
):
    return container.gallery.list(principal.patient_id)


@router.get("/images/{image_id}")
def image(
    image_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    return Response(
        container.gallery.image(principal.patient_id, image_id),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/gallery/{medication_id}/images", response_model=MedicationImage)
async def upload(
    medication_id: UUID,
    request: Request,
    image_kind: Literal["loose_pill", "package", "blister"] = Query(),
    source_description: str = Query(min_length=1, max_length=200),
    reviewed: bool = Query(default=False),
    for_comparison: bool = Query(default=False),
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    content = await image_content(request)
    return await run_in_threadpool(
        container.gallery.upload,
        patient_id=principal.patient_id,
        medication_id=medication_id,
        image=content,
        image_kind=image_kind,
        source_description=source_description,
        reviewed=reviewed,
        for_comparison=for_comparison,
        consent=request.headers.get("x-stage2-consent") == "true",
        demo_only=request.headers.get("x-demo-only") == "true",
    )


@router.post("/check-dose", response_model=RecognitionRun)
async def check(
    request: Request,
    regimen_id: UUID | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    content = await image_content(request)
    return await run_in_threadpool(
        container.gallery.check,
        patient_id=principal.patient_id,
        regimen_id=regimen_id,
        image=content,
        consent=request.headers.get("x-stage2-consent") == "true",
        demo_only=request.headers.get("x-demo-only") == "true",
    )


@router.post("/images/{image_id}/retire", response_model=MedicationImage)
def retire_reference(
    image_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    return container.gallery.retire(principal.patient_id, image_id)
