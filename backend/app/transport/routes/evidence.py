"""Typed patient evidence APIs. All identity comes from verified AuthContext."""

from typing import Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

from ...contracts.dto import RegimenDraftInput
from ...contracts.medication_evidence import (
    EnrollmentTask,
    GalleryUploadResult,
    MedicationImage,
    RecognitionRun,
    SourceEvidenceView,
)
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


class PhotoManagementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["edit", "remove", "delete"]
    expected_version: int
    image_kind: Literal["loose_pill", "package", "blister", "source"] | None = None
    source_description: str | None = None
    confirmed: bool = False


class PdfMetadataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int
    title: str
    category: Literal["prescription", "pharmacy_document", "medication_instructions", "other"]
    description: str = ""


async def pdf_content(request: Request) -> bytes:
    mime = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if mime != "application/pdf":
        raise ValidationError("Choose a PDF file")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 10 * 1024 * 1024:
            raise ValidationError("PDF must be no larger than 10 MB")
    return bytes(body)


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
    automatically_routed: bool = Query(default=False),
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    content = await image_content(request)
    return await run_in_threadpool(
        container.evidence_enrollment.attach,
        patient_id=principal.patient_id,
        task_id=task_id,
        automatically_routed=automatically_routed,
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
    rows = container.gallery.list(principal.patient_id)
    if container.library_files:
        for row in rows:
            row["pdf_file_count"] = len(container.library_files.list(principal.patient_id, row["medication"].id))
    return rows


@router.get("/gallery/{medication_id}/files")
def medication_files(
    medication_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    """Read-only owner-scoped view over linked source records and private images."""
    result = container.gallery.files(principal.patient_id, medication_id)
    result["file_management_available"] = container.library_files is not None
    if container.library_files:
        result["files"].extend(
            {
                "id": str(file.id),
                "file_id": str(file.id),
                "image_id": None,
                "image_ids": [],
                "name": file.display_title,
                "original_filename": file.original_filename,
                "format": "PDF",
                "content_type": "pdf",
                "photo_description": None,
                "purpose_tags": ["source_document"],
                "created_at": file.uploaded_at.isoformat(),
                "eligibility": "ineligible",
                "eligibility_reason": "not_an_image",
                "sources": [],
                "category": file.category,
                "description": file.description,
                "version": file.version,
                "byte_size": file.byte_size,
            }
            for file in container.library_files.list(principal.patient_id, medication_id)
        )
    return result


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


@router.post("/gallery/{medication_id}/images", response_model=GalleryUploadResult)
async def upload(
    medication_id: UUID,
    request: Request,
    image_kind: Literal["loose_pill", "package", "blister", "source"] = Query(),
    source_description: str = Query(min_length=1, max_length=200),
    reviewed: bool = Query(default=False),
    for_comparison: bool = Query(default=False),
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    content = await image_content(request)
    return await run_in_threadpool(
        container.gallery.upload_with_status,
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


@router.patch("/images/{image_id}", response_model=MedicationImage)
def manage_reference_photo(
    image_id: UUID,
    body: PhotoManagementRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    if container.library_files is None:
        raise ProviderUnavailableError("File management is not enabled for this database release.")
    result = container.gallery.manage_image(principal.patient_id, image_id, **body.model_dump())
    return result


@router.post("/gallery/{medication_id}/pdfs")
async def upload_library_pdf(
    medication_id: UUID,
    request: Request,
    filename: str = Query(min_length=1, max_length=240),
    category: Literal["prescription", "pharmacy_document", "medication_instructions", "other"] = Query(default="other"),
    description: str = Query(default="", max_length=500),
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    if container.library_files is None:
        raise ProviderUnavailableError("PDF files are not enabled for this database release.")
    content = await pdf_content(request)
    file, duplicate = await run_in_threadpool(
        container.library_files.upload,
        patient_id=principal.patient_id,
        medication_id=medication_id,
        filename=filename,
        content_type=request.headers.get("content-type", "").split(";")[0].strip().lower(),
        data=content,
        category=category,
        description=description,
    )
    return {"file": file, "duplicate": duplicate}


@router.get("/library-files/{file_id}")
def library_pdf_content(
    file_id: UUID,
    disposition: Literal["inline", "attachment"] = Query(default="inline"),
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    if container.library_files is None:
        raise ProviderUnavailableError("PDF files are not enabled for this database release.")
    file, content = container.library_files.content(principal.patient_id, file_id)
    safe_name = quote(file.original_filename, safe="")
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'; frame-ancestors 'self'",
            "Cross-Origin-Resource-Policy": "same-origin",
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{safe_name}",
        },
    )


@router.patch("/library-files/{file_id}")
def update_library_pdf(
    file_id: UUID,
    body: PdfMetadataRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    if container.library_files is None:
        raise ProviderUnavailableError("PDF files are not enabled for this database release.")
    return container.library_files.update(principal.patient_id, file_id, **body.model_dump())


@router.delete("/library-files/{file_id}")
def delete_library_pdf(
    file_id: UUID,
    confirmed: bool = Query(default=False),
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    if container.library_files is None:
        raise ProviderUnavailableError("PDF files are not enabled for this database release.")
    container.library_files.delete(principal.patient_id, file_id, confirmed=confirmed)
    return {"deleted": True}
