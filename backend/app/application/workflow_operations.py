"""Operation receipts and owned observation. This service has no write executor."""

import re
from collections.abc import Mapping
from typing import Protocol
from uuid import UUID, uuid5

from ..contracts.assistant_workflows import (
    ActionReceipt,
    ActionRepository,
    BusinessRef,
    OperationResult,
    WorkflowContext,
)
from ..contracts.ports import Clock
from ..domain.errors import DomainError, DuplicateEventError, StaleVersionError, ValidationError
from .preferences import PreferenceService


class OperationObserver(Protocol):
    def observe(self, context: WorkflowContext, result_ref: BusinessRef) -> OperationResult: ...


class WorkflowOperationService:
    def __init__(
        self, *, repository: ActionRepository, observers: Mapping[str, OperationObserver], clock: Clock,
        preferences: PreferenceService | None = None,
    ):
        self._repository, self._observers, self._clock = repository, dict(observers), clock
        self._preferences = preferences

    def read(self, owner: UUID, action_key: UUID) -> ActionReceipt:
        return self._repository.read(owner, action_key)

    @staticmethod
    def _bound(context: WorkflowContext, receipt: ActionReceipt):
        if (receipt.owner != context.owner or receipt.task_id != context.task_id
                or receipt.capability_id != context.capability_id):
            raise ValidationError("Operation belongs to another workflow")
        if receipt.binding_revision != context.revision:
            raise StaleVersionError("Operation belongs to another workflow revision")

    def reserve(
        self, context: WorkflowContext, action_key: UUID | None = None, *, target: BusinessRef | None = None,
    ) -> ActionReceipt:
        if context.save_mode != "allowed":
            raise ValidationError("Enable saving before preparing a business change")
        key = action_key or uuid5(context.task_id, f"{context.capability_id}:revision:{context.revision}")
        receipt = self._repository.reserve(context, key)
        if target is not None:
            if receipt.business_ref is not None and receipt.business_ref != target:
                raise DuplicateEventError("Operation target cannot change")
            if receipt.business_ref is None:
                receipt = receipt.model_copy(update={"business_ref": target})
                self._repository.complete(context, receipt)
        return receipt

    def reconcile(self, owner: UUID, action_key: UUID) -> OperationResult:
        receipt = self._repository.read(owner, action_key)
        preferences = self._preferences.get(owner) if self._preferences else None
        context = WorkflowContext(
            owner=owner, task_id=receipt.task_id, capability_id=receipt.capability_id,
            revision=receipt.binding_revision,
            **({"language": preferences.preferred_language, "timezone": preferences.timezone} if preferences else {}),
        )
        return self.reconcile_context(context, action_key)

    def reconcile_context(self, context: WorkflowContext, action_key: UUID) -> OperationResult:
        receipt = self._repository.read(context.owner, action_key)
        self._bound(context, receipt)
        if receipt.state in {"succeeded", "failed"}:
            return OperationResult(state=receipt.state, business_ref=receipt.business_ref, reason=receipt.safe_reason)
        observer = self._observers.get(receipt.capability_id)
        result = OperationResult(state="outcome_unknown", reason="observation_unavailable")
        if observer is not None and receipt.business_ref is not None:
            try:
                result = observer.observe(context, receipt.business_ref)
            except DomainError:
                pass
        if result.state == "succeeded" and result.business_ref is None:
            result = OperationResult(state="outcome_unknown", reason="missing_business_reference")
        if result.state == "pending" and receipt.state == "outcome_unknown":
            result = result.model_copy(update={"state": "outcome_unknown"})
        safe_reason = result.reason if result.reason and re.fullmatch(r"[a-z_]{1,80}", result.reason) else None
        updated = receipt.model_copy(update={
            "state": result.state, "business_ref": result.business_ref or receipt.business_ref,
            "safe_reason": safe_reason, "updated_at": self._clock.now(),
        })
        self._repository.complete(context, updated)
        return result
