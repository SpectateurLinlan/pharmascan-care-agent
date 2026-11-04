"""Independent enrollment APIs respect the current task and no-save fence."""

from collections.abc import Callable, Mapping
from typing import TypeVar
from uuid import UUID

from ..contracts.assistant_workflows import (
    ActionRepository,
    BusinessRef,
    ControlRepository,
    WorkflowContext,
    WorkflowRepository,
)
from ..contracts.dto import RegimenVersionDTO
from ..contracts.enrollment_operations import EnrollmentReviewTransaction, EnrollmentWritePort
from ..domain.errors import NotFoundError, StaleVersionError

T = TypeVar("T")


class WorkflowEnrollmentGuard:
    def __init__(
        self,
        *,
        bindings: EnrollmentWritePort,
        tasks: WorkflowRepository,
        controls: ControlRepository,
        actions: ActionRepository,
        transactions: Mapping[str, EnrollmentReviewTransaction] | None = None,
    ):
        self._bindings, self._tasks, self._controls = bindings, tasks, controls
        self._actions = actions
        self._transactions = dict(transactions or {})

    def _context(self, owner: UUID, regimen: RegimenVersionDTO):
        binding = self._bindings.for_regimen(owner, regimen.id)
        if binding is None or binding.workflow_task_id is None:
            return None
        task = self._tasks.get(owner, binding.workflow_task_id)
        return WorkflowContext(owner=owner, task_id=task.id, capability_id=task.capability_id, revision=task.revision)

    def bind_challenge(self, owner: UUID, regimen: RegimenVersionDTO, challenge_id: UUID) -> None:
        context = self._context(owner, regimen)
        if context is None:
            return
        receipt = self._actions.reserve(context, challenge_id)
        self._actions.complete(
            context,
            receipt.model_copy(
                update={
                    "business_ref": BusinessRef(kind="regimen", id=regimen.id, version=regimen.version_no),
                }
            ),
        )

    def run_challenge(self, owner: UUID, regimen: RegimenVersionDTO, challenge_id: UUID, write: Callable[[], T]) -> T:
        def checked():
            context = self._context(owner, regimen)
            if context is not None:
                try:
                    receipt = self._actions.read(owner, challenge_id)
                except NotFoundError:
                    raise StaleVersionError(
                        "This confirmation predates the current review. Request a new summary"
                    ) from None
                if (
                    receipt.task_id != context.task_id
                    or receipt.binding_revision != context.revision
                    or receipt.capability_id != context.capability_id
                    or receipt.business_ref != BusinessRef(kind="regimen", id=regimen.id, version=regimen.version_no)
                ):
                    raise StaleVersionError("This confirmation predates the current review. Request a new summary")
            return write()

        return self.run(owner, regimen, checked)

    def run(self, owner: UUID, regimen: RegimenVersionDTO, write: Callable[[], T]) -> T:
        binding = self._bindings.for_regimen(owner, regimen.id)
        if binding is None or binding.workflow_task_id is None:
            return write()
        task_id = binding.workflow_task_id
        control = self._controls.get(owner, task_id)
        results = []

        def guarded():
            task = self._tasks.get(owner, task_id)
            if (
                task.state != "awaiting_confirmation"
                or control.status in {"processing", "interrupted"}
                or not any(
                    row.kind == "regimen"
                    and row.id == regimen.id
                    and row.version == regimen.version_no == binding.version_no
                    for row in task.business_refs
                )
            ):
                raise StaleVersionError(
                    "The enrollment review changed. Reopen the current saved draft before confirming"
                )
            transaction = self._transactions.get(task.capability_id)
            results.append(transaction.run(owner, regimen, write) if transaction else write())

        if not self._controls.guarded_write(owner, task_id, control.revision, guarded):
            raise StaleVersionError("Enrollment saving permission changed. Old review requests cannot continue")
        return results[0]
