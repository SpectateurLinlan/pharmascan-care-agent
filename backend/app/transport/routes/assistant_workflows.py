"""Authenticated workflow HTTP boundary over public application services."""

from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import ValidationError as SchemaValidationError
from starlette.concurrency import run_in_threadpool

from ...agent.capabilities import build_capability_registry
from ...contracts.agent_execution import RunSnapshot
from ...contracts.assistant_capabilities import CapabilityAvailability
from ...contracts.assistant_workflows import EphemeralPayload, WorkflowEvent, WorkflowMessageInput, WorkflowView
from ...contracts.image_comparison import CompareQuery, ComparisonResult
from ...contracts.knowledge_workflow import KnowledgeQueryRequest
from ...contracts.medication_knowledge import MedicationUnderstanding
from ...contracts.source_preview_workflow import SourcePreviewQuery, SourcePreviewResult
from ...contracts.workflow_attachments import AttachmentView, CleanupItem, EphemeralImagePreview
from ...domain.errors import ProviderUnavailableError, ValidationError
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal
from ..workflow_schemas import (
    AttachmentUploadResponse,
    CleanupRetryRequest,
    EphemeralPreviewRequest,
    RecoverOriginalRequest,
    ResumeDraftRequest,
    StartWorkflowRequest,
    WorkflowCapabilitiesResponse,
    WorkflowEventRequest,
    WorkflowMessageRequest,
    WorkflowMessageResponse,
    WorkflowStreamRequest,
)
from ..workflow_stream import WorkflowStreamResponse
from .agent import message_response
from .evidence import image_content, pdf_content


def _no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/api/agent/workflows", tags=["assistant-workflows"], dependencies=[Depends(_no_store)])


def _service(container):
    if container.assistant_workflows is None:
        raise ProviderUnavailableError("Assistant workflows are unavailable for this environment")
    return container.assistant_workflows


@router.get("/capabilities", response_model=WorkflowCapabilitiesResponse)
def capabilities(
    principal: AuthenticatedPrincipal = Depends(get_principal), container: ApplicationContainer = Depends(get_container)
):
    enabled = container.assistant_workflows is not None
    records_ready = enabled and container.record_history is not None and container.review_summary is not None
    report_services = {"self_report"} if enabled and container.assistant_reports is not None else set()
    care_services = {"care", "observations"} if enabled and container.assistant_care is not None else set()
    media_services = {
        key
        for key, service in (("gallery", container.gallery), ("library_files", container.library_files))
        if enabled and service is not None
    }
    if enabled and container.assistant_late_reports is not None:
        report_services.add("late_reports")
    if enabled and container.assistant_image_compare is not None:
        media_services.add("vision")
    if enabled and container.assistant_source_preview is not None:
        media_services.add("source_preview")
    if enabled and container.assistant_reminder_reads is not None:
        media_services.update({"reminders", "push"})
    if enabled and container.assistant_settings is not None:
        media_services.update({"preferences", "caregivers", "account"})
    if enabled and container.assistant_conversations is not None:
        media_services.update({"conversations", "quota", "speech", "navigation", "feedback"})
    availability = CapabilityAvailability(
        workflows_enabled=enabled,
        workflow_unavailable_reason="persistence_not_ready"
        if not enabled and container.assistant_transactions is not None else "feature_disabled",
        disabled_capabilities=frozenset({"medication.knowledge"})
        if enabled and container.assistant_knowledge is None
        else frozenset(),
        notification_send_allowed=bool(
            container.assistant_notification_test_allowed
            and container.push_test is not None
            and principal.authenticated
        ),
        services=frozenset(
            {
                "enrollment",
                *({"records", "medication_understanding"} if records_ready else set()),
                *report_services,
                *care_services,
                *media_services,
            }
        )
        if enabled
        else frozenset(),
        adapters=frozenset(
            {
                "enrollment",
                "medication_management",
                *(
                    {"conversations", "device_ui", "navigation", "feedback"}
                    if container.assistant_conversations
                    else set()
                ),
                *({"preferences", "contacts", "account_ui"} if container.assistant_settings else set()),
                *({"reminders"} if container.assistant_reminder_reads else set()),
                *({"media"} if media_services else set()),
                *({"care"} if care_services else set()),
                *({"records", "knowledge"} if records_ready else set()),
                *({"records"} if report_services else set()),
            }
        )
        if enabled
        else frozenset(),
        implemented_capabilities=container.assistant_workflows.implemented_capabilities() if enabled else frozenset(),
    )
    return WorkflowCapabilitiesResponse(
        admission=container.assistant_admission,
        enabled=enabled,
        progress_enabled=container.assistant_execution is not None,
        capabilities=build_capability_registry().list(availability),
    )


@router.post("/tasks", response_model=WorkflowView)
def start(
    payload: StartWorkflowRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return _service(container).start(
            principal.patient_id,
            payload.capability_id,
            payload.workspace_id,
            payload.conversation_id,
            payload.values,
            payload.save_mode,
            client_event_id=payload.client_event_id,
        )
    except SchemaValidationError:
        raise ValidationError("Workflow fields are invalid; review the input") from None


@router.get("/tasks", response_model=tuple[WorkflowView, ...])
def list_tasks(
    workspace_id: UUID | None = None,
    include_ephemeral: bool = False,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    service = _service(container)
    return service.list_views(principal.patient_id, workspace_id, include_ephemeral=include_ephemeral)


@router.get("/tasks/{task_id}", response_model=WorkflowView)
def read(
    task_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    return _service(container).view(principal.patient_id, task_id)


@router.post("/tasks/{task_id}/knowledge", response_model=MedicationUnderstanding)
def query_knowledge(
    task_id: UUID,
    payload: KnowledgeQueryRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    if container.assistant_knowledge is None:
        raise ProviderUnavailableError("General medication knowledge query is unavailable")
    return container.assistant_knowledge.query(principal.patient_id, task_id, payload)


@router.post("/tasks/{task_id}/compare", response_model=ComparisonResult)
async def compare_image(
    task_id: UUID,
    request: Request,
    expected_revision: int = Query(ge=1),
    ephemeral_intent: Literal["personal", "identify"] | None = None,
    ephemeral_regimen_id: UUID | None = None,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    if container.assistant_image_compare is None:
        raise ProviderUnavailableError("Assistant photo comparison is unavailable")
    if ephemeral_regimen_id is not None and ephemeral_intent is None:
        raise ValidationError("Provide the current no-save photo check inputs")
    ephemeral = (
        EphemeralPayload(
            capability_id="image.compare",
            fields={
                "intent": ephemeral_intent,
                "regimen_id": str(ephemeral_regimen_id) if ephemeral_regimen_id else None,
            },
        )
        if ephemeral_intent
        else None
    )
    content = await image_content(request)
    return await run_in_threadpool(
        container.assistant_image_compare.query,
        principal.patient_id,
        task_id,
        CompareQuery(expected_revision=expected_revision, ephemeral=ephemeral),
        content,
        request.headers.get("content-type", "").split(";")[0],
        request.headers.get("X-Stage2-Consent") == "true",
    )


@router.post("/tasks/{task_id}/source-preview", response_model=SourcePreviewResult)
async def preview_source_image(
    task_id: UUID,
    request: Request,
    expected_revision: int = Query(ge=1),
    ephemeral_source_kind: Literal["package", "pharmacy_label", "prescription"] | None = None,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    if container.assistant_source_preview is None:
        raise ProviderUnavailableError("Assistant source preview is unavailable")
    ephemeral = (
        EphemeralPayload(
            capability_id="source.preview",
            fields={
                "source_kind": ephemeral_source_kind,
            },
        )
        if ephemeral_source_kind
        else None
    )
    content = await image_content(request)
    return await run_in_threadpool(
        container.assistant_source_preview.query,
        principal.patient_id,
        task_id,
        SourcePreviewQuery(expected_revision=expected_revision, ephemeral=ephemeral),
        content,
        request.headers.get("content-type", "").split(";")[0],
        request.headers.get("X-Stage2-Consent") == "true",
    )


@router.post("/tasks/{task_id}/events", response_model=WorkflowView)
def event(
    task_id: UUID,
    payload: WorkflowEventRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return _service(container).advance(
            principal.patient_id,
            task_id,
            WorkflowEvent.model_validate(payload.model_dump(exclude={"ephemeral"})),
            ephemeral=payload.ephemeral.model_dump(mode="json") if payload.ephemeral else None,
        )
    except SchemaValidationError:
        raise ValidationError("Workflow fields are invalid; review the input") from None


@router.post("/tasks/{task_id}/resume-draft", response_model=WorkflowView)
def resume_draft(
    task_id: UUID,
    payload: ResumeDraftRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    return _service(container).resume_draft(principal.patient_id, task_id, payload.expected_revision)


def _message_result(payload, principal, container):
    _service(container)
    result = container.messages().handle(
        principal.patient_id,
        WorkflowMessageInput(
            **payload.model_dump(exclude={"client_id", "run_id"}),
            threaded="conversation_id" in payload.model_fields_set,
        ),
    )
    return WorkflowMessageResponse(
        reply=message_response(result), workflow=result.workflow, explanations=result.explanations
    )


def _execution(container):
    if container.assistant_execution is None:
        raise ProviderUnavailableError("Assistant progress is unavailable")
    return container.assistant_execution


@router.post("/messages", response_model=WorkflowMessageResponse)
def message(
    payload: WorkflowMessageRequest,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    def work():
        return _message_result(payload, principal, container)

    if container.assistant_execution is None:
        return work()
    service, run_id = _execution(container), uuid4()
    service.start(principal.patient_id, run_id)
    response.headers["X-Agent-Run-ID"] = str(run_id)
    return service.execute(principal.patient_id, run_id, work)


@router.get("/runs/{run_id}", response_model=RunSnapshot)
def read_run(
    run_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    return _execution(container).read(principal.patient_id, run_id)


@router.post("/runs/{run_id}/cancel", response_model=RunSnapshot)
def cancel_run(
    run_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    return _execution(container).cancel(principal.patient_id, run_id)


@router.post("/messages/stream")
async def stream_message(
    payload: WorkflowStreamRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    _service(container)
    service = _execution(container)
    service.start(principal.patient_id, payload.run_id)
    scoped = getattr(request.state, "patient_container", None)
    response = WorkflowStreamResponse(
        service=service,
        owner=principal.patient_id,
        run_id=payload.run_id,
        work=lambda: _message_result(payload, principal, container),
        close_request=scoped.close_request if scoped is not None else None,
    )
    request.state.stream_owns_resources = True
    return response


@router.put("/tasks/{task_id}/attachments/{upload_id}", response_model=AttachmentUploadResponse)
async def upload_original(
    task_id: UUID,
    upload_id: UUID,
    request: Request,
    expected_revision: int = Query(ge=1),
    source_kind: Literal[
        "package",
        "pharmacy_label",
        "prescription",
        "reference_photo",
        "library_pdf",
        "comparison_photo",
        "source_preview_photo",
    ] = "pharmacy_label",
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    _service(container)
    if container.assistant_attachments is None:
        raise ProviderUnavailableError("Original image storage is unavailable")
    service = container.assistant_attachments
    context = service.context(principal.patient_id, task_id, expected_revision)
    content = await pdf_content(request) if source_kind == "library_pdf" else await image_content(request)
    mime = request.headers.get("content-type", "").split(";")[0]
    attachment = await run_in_threadpool(
        service.accept,
        context,
        upload_id,
        content,
        mime,
        request.headers.get("X-Stage2-Consent", "").lower() == "true",
        source_kind,
    )
    return AttachmentUploadResponse(
        attachment=attachment, workflow=_service(container).view(principal.patient_id, task_id)
    )


@router.get("/tasks/{task_id}/attachments/{attachment_id}")
def original(
    task_id: UUID,
    attachment_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    _service(container)
    if container.assistant_attachments is None:
        raise ProviderUnavailableError("Original image storage is unavailable")
    content, mime = container.assistant_attachments.read(principal.patient_id, task_id, attachment_id)
    return Response(
        content, media_type=mime, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    )


@router.put("/tasks/{task_id}/attachments/{attachment_id}/retry", response_model=AttachmentUploadResponse)
async def retry_original(
    task_id: UUID,
    attachment_id: UUID,
    request: Request,
    expected_revision: int = Query(ge=1),
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    _service(container)
    if container.assistant_attachments is None:
        raise ProviderUnavailableError("Original image storage is unavailable")
    service = container.assistant_attachments
    context = service.context(principal.patient_id, task_id, expected_revision)
    mime = request.headers.get("content-type", "").split(";")[0].strip().lower()
    content = await pdf_content(request) if mime == "application/pdf" else await image_content(request)
    attachment = await run_in_threadpool(
        service.retry_upload,
        context,
        attachment_id,
        content,
        request.headers.get("content-type", "").split(";")[0],
        request.headers.get("X-Stage2-Consent", "").lower() == "true",
    )
    return AttachmentUploadResponse(
        attachment=attachment, workflow=_service(container).view(principal.patient_id, task_id)
    )


@router.post("/tasks/{task_id}/attachments/{attachment_id}/recover", response_model=AttachmentUploadResponse)
def recover_original(
    task_id: UUID,
    attachment_id: UUID,
    payload: RecoverOriginalRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    _service(container)
    if container.assistant_attachments is None:
        raise ProviderUnavailableError("Original image storage is unavailable")
    service = container.assistant_attachments
    context = service.context(principal.patient_id, task_id, payload.expected_revision)
    attachment = service.recover(context, attachment_id, payload.event_id)
    return AttachmentUploadResponse(
        attachment=attachment, workflow=_service(container).view(principal.patient_id, task_id)
    )


@router.post("/tasks/{task_id}/cleanup", response_model=tuple[CleanupItem, ...])
def retry_cleanup(
    task_id: UUID,
    payload: CleanupRetryRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    _service(container)
    if container.assistant_cleanup is None:
        raise ProviderUnavailableError("Original cleanup is unavailable")
    return tuple(
        CleanupItem(attachment_id=row.id, state=row.state, reason=row.reason, writer_pending=row.writer_pending)
        for row in container.assistant_cleanup.retry_cleanup(principal.patient_id, task_id)
    )


@router.post("/tasks/{task_id}/attachments/{attachment_id}/preview", response_model=AttachmentUploadResponse)
def recognize_original(
    task_id: UUID,
    attachment_id: UUID,
    payload: RecoverOriginalRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    _service(container)
    if container.assistant_attachments is None:
        raise ProviderUnavailableError("Photo processing is unavailable")
    service = container.assistant_attachments
    context = service.context(principal.patient_id, task_id, payload.expected_revision)
    attachment = service.recognize(
        context,
        attachment_id,
        payload.event_id,
        processing_consent=request.headers.get("X-Stage2-Consent", "").lower() == "true",
    )
    return AttachmentUploadResponse(
        attachment=attachment, workflow=_service(container).view(principal.patient_id, task_id)
    )


@router.post("/tasks/{task_id}/preview", response_model=WorkflowView)
def ephemeral_preview(
    task_id: UUID,
    payload: EphemeralPreviewRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return _service(container).preview(principal.patient_id, task_id, payload.ephemeral)
    except SchemaValidationError:
        raise ValidationError("Workflow fields are invalid; review the page input") from None


@router.get("/tasks/{task_id}/attachments", response_model=tuple[AttachmentView, ...])
def original_list(
    task_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    _service(container)
    if container.assistant_attachments is None:
        raise ProviderUnavailableError("Original image storage is unavailable")
    return container.assistant_attachments.list_views(principal.patient_id, task_id)


@router.post("/tasks/{task_id}/preview-image/{event_id}", response_model=EphemeralImagePreview)
async def ephemeral_image(
    task_id: UUID,
    event_id: UUID,
    request: Request,
    expected_revision: int = Query(ge=1),
    source_kind: Literal["package", "pharmacy_label", "prescription"] = "pharmacy_label",
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    _service(container)
    if container.assistant_attachments is None:
        raise ProviderUnavailableError("Photo processing is unavailable")
    service = container.assistant_attachments
    context = service.context(principal.patient_id, task_id, expected_revision)
    content = await image_content(request)
    mime = request.headers.get("content-type", "").split(";")[0]
    return await run_in_threadpool(
        service.preview_ephemeral,
        context,
        event_id,
        content,
        mime,
        request.headers.get("X-Stage2-Consent", "").lower() == "true",
        source_kind,
    )
