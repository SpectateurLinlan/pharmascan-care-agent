"""Authenticated public long-term care API; confirmations are human UI actions."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ...application.long_term import LongTermCareService
from ...contracts.long_term import (
    Barrier,
    BarrierInput,
    CareTask,
    CareTaskInput,
    MedicationCareReport,
    StockInput,
    StockStatus,
    TaskUpdate,
)
from ...domain.errors import ProviderUnavailableError
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal

router = APIRouter(prefix="/api/me", tags=["long-term-care"])
Owner = Annotated[AuthenticatedPrincipal, Depends(get_principal)]
Container = Annotated[ApplicationContainer, Depends(get_container)]


def care(container: ApplicationContainer) -> LongTermCareService:
    if container.long_term is None:
        raise ProviderUnavailableError("Long-term care unavailable")
    return container.long_term


def zone(container: ApplicationContainer, principal: AuthenticatedPrincipal) -> str:
    return container.preferences.get(principal.patient_id).timezone if container.preferences else "Asia/Singapore"


@router.get("/inventory/{medication_id}", response_model=StockStatus)
def inventory(medication_id: UUID, principal: Owner, container: Container):
    return care(container).inventory(principal.patient_id, medication_id, zone(container, principal))


@router.post("/inventory/{medication_id}", response_model=StockStatus)
def record_stock(medication_id: UUID, values: StockInput, principal: Owner, container: Container):
    return care(container).record_stock(principal.patient_id, medication_id, values, zone(container, principal))


@router.get("/care-tasks", response_model=list[CareTask])
def tasks(principal: Owner, container: Container, actionable: bool = Query(default=False)):
    service = care(container)
    return (
        service.actionable_tasks(principal.patient_id, zone(container, principal))
        if actionable
        else service.tasks(principal.patient_id)
    )


@router.post("/care-tasks", response_model=CareTask)
def create_task(values: CareTaskInput, principal: Owner, container: Container):
    return care(container).create_task(principal.patient_id, values)


@router.post("/care-tasks/refresh", response_model=list[CareTask])
def refresh_followups(principal: Owner, container: Container):
    return care(container).refresh_refill_tasks(principal.patient_id, zone(container, principal))


@router.post("/care-tasks/{task_id}", response_model=CareTask)
def update_task(task_id: UUID, values: TaskUpdate, principal: Owner, container: Container):
    return care(container).update_task(principal.patient_id, task_id, values)


@router.get("/adherence-barriers", response_model=list[Barrier])
def barriers(principal: Owner, container: Container):
    return care(container).barriers(principal.patient_id)


@router.post("/adherence-barriers", response_model=Barrier)
def record_barrier(values: BarrierInput, principal: Owner, container: Container):
    return care(container).record_barrier(principal.patient_id, values)


@router.get("/medication-review", response_model=MedicationCareReport)
def review(principal: Owner, container: Container, days: int = Query(default=30, ge=7, le=30)):
    return care(container).review(principal.patient_id, days, zone(container, principal))
