"""A domain transaction owns task advancement; orchestration never repeats it."""

from typing import Protocol
from uuid import UUID

from .assistant_workflows import Preparation, WorkflowTask
from .workflow_persistence import BusinessWriteReceipt, RunWriteBinding


class BusinessReceiptReader(Protocol):
    def read_receipt(self, owner: UUID, action_key: UUID) -> BusinessWriteReceipt | None: ...
    def task_receipts(self, owner: UUID, task_id: UUID) -> tuple[BusinessWriteReceipt, ...]: ...


class WorkflowBusinessTransactions(Protocol):
    capability_ids: frozenset[str]

    def prepare(
        self, task: WorkflowTask, expected_revision: int, action_key: UUID, run_binding: RunWriteBinding | None = None
    ) -> BusinessWriteReceipt: ...
    def project(self, task: WorkflowTask) -> Preparation | None: ...
