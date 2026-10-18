"""Authenticated patient records; owner identity is never a payload field."""

from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ...application.record_history import HistoryRange
from ...contracts.observations import Observation, ObservationInput
from ...contracts.record_history import HistoryCatalogue, MedicationHistoryPage
from ...contracts.review_summary import ReviewSummary
from ...domain.errors import ProviderUnavailableError
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal

router = APIRouter(prefix="/api/me", tags=["patient-records"])


@router.get("/medication-history/catalogue", response_model=HistoryCatalogue)
def history_catalogue(
    principal: AuthenticatedPrincipal = Depends(get_principal), container: ApplicationContainer = Depends(get_container)
):
    if container.record_history is None:
        raise ProviderUnavailableError("Medication history unavailable")
    return container.record_history.catalogue(principal.patient_id)


@router.get("/medication-history", response_model=MedicationHistoryPage)
def medication_history(
    medication_id: UUID | None = None,
    medication_name: str | None = Query(default=None, min_length=1, max_length=160),
    regimen_id: UUID | None = None,
    range_kind: HistoryRange = "30",
    start: date | None = None,
    end: date | None = None,
    cursor: str | None = Query(default=None, max_length=4096),
    limit: int = Query(default=5, ge=1, le=50),
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    if container.record_history is None:
        raise ProviderUnavailableError("Medication history unavailable")
    return container.record_history.page(
        principal.patient_id,
        medication_id=medication_id,
        medication_name=medication_name,
        regimen_id=regimen_id,
        range_kind=range_kind,
        start=start,
        end=end,
        cursor=cursor,
        limit=limit,
    )


@router.get("/health-observations", response_model=list[Observation])
def list_observations(
    principal: AuthenticatedPrincipal = Depends(get_principal), container: ApplicationContainer = Depends(get_container)
):
    if not container.observations:
        raise ProviderUnavailableError("Health records unavailable")
    now = container.clock.now()
    return container.observations.list(principal.patient_id, now - timedelta(days=366), now + timedelta(minutes=5))


@router.put("/health-observations", response_model=Observation)
def save_observation(
    payload: ObservationInput,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    if not container.observations:
        raise ProviderUnavailableError("Health records unavailable")
    return container.observations.save(principal.patient_id, payload)


@router.delete("/health-observations/{observation_id}")
def delete_observation(
    observation_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    if not container.observations:
        raise ProviderUnavailableError("Health records unavailable")
    container.observations.delete(principal.patient_id, observation_id)
    return {"deleted": True}


@router.get("/review-summary", response_model=ReviewSummary)
def review_summary(
    period: Literal["week", "month", "course"] = "week",
    regimen_id: UUID | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    if not container.review_summary:
        raise ProviderUnavailableError("Summaries unavailable")
    timezone = container.preferences.get(principal.patient_id).timezone if container.preferences else "Asia/Singapore"
    return container.review_summary.generate(principal.patient_id, period, regimen_id, timezone)
