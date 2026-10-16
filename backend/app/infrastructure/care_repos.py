"""Long-term persistence through same-user JWT or explicit local test adapter."""

from datetime import datetime
from threading import RLock
from uuid import UUID

from ..contracts.long_term import Barrier, CareTask, StockInput, StockTransaction, TaskHistory, TaskUpdate
from ..domain.errors import NotFoundError, ValidationError
from ..domain.inventory import ledger_balance
from .supabase_data import SupabaseDataClient


class MemoryCareRepository:
    """SIMULATED process-local adapter; lock mirrors atomic database operations."""

    def __init__(self):
        self._stocks: dict[tuple[UUID, UUID], list[StockTransaction]] = {}
        self._tasks: dict[tuple[UUID, UUID], CareTask] = {}
        self._barriers: dict[tuple[UUID, UUID], Barrier] = {}
        self._lock = RLock()

    def stock(self, patient_id: UUID, medication_id: UUID) -> list[StockTransaction]:
        with self._lock:
            return list(self._stocks.get((patient_id, medication_id), []))

    def append_stock(
        self, patient_id: UUID, medication_id: UUID, values: StockInput, now: datetime
    ) -> StockTransaction:
        with self._lock:
            rows = self._stocks.setdefault((patient_id, medication_id), [])
            for collection in self._stocks.values():
                for row in collection:
                    if row.patient_id == patient_id and row.id == values.id:
                        if row.medication_id != medication_id or row.model_dump(
                            include=set(StockInput.model_fields) - {"confirmed"}
                        ) != values.model_dump(exclude={"confirmed"}):
                            raise ValidationError("Idempotency key was already used for different stock details")
                        return row
            balance = ledger_balance(rows[-1].stock_after if rows else None, rows[-1].unit if rows else None, values)
            row = StockTransaction(
                **values.model_dump(exclude={"confirmed"}),
                patient_id=patient_id,
                medication_id=medication_id,
                stock_after=balance,
                recorded_at=now,
            )
            rows.append(row)
            return row

    def tasks(self, patient_id: UUID) -> list[CareTask]:
        with self._lock:
            return sorted(
                [row for (owner, _), row in self._tasks.items() if owner == patient_id], key=lambda row: row.due_at
            )

    def create_task(self, task: CareTask) -> CareTask:
        with self._lock:
            previous = self._tasks.get((task.patient_id, task.id))
            if previous:
                fields = {"category", "title", "medication_id", "regimen_id", "source"}
                if previous.model_dump(include=fields) != task.model_dump(include=fields):
                    raise ValidationError("Task key was already used for different details")
                original = previous.history[0]
                if task.source != "stock_estimate" and (original.due_at != task.due_at or original.notes != task.notes):
                    raise ValidationError("Task key was already used for different date or notes")
                return previous
            task = task.model_copy(
                update={
                    "history": [
                        TaskHistory(
                            id=task.id,
                            status=task.status,
                            due_at=task.due_at,
                            notes=task.notes,
                            recorded_at=task.created_at,
                        )
                    ]
                }
            )
            self._tasks[task.patient_id, task.id] = task
            return task

    def update_task(self, patient_id: UUID, task_id: UUID, change: TaskUpdate, now: datetime) -> CareTask:
        with self._lock:
            previous = self._tasks.get((patient_id, task_id))
            if previous is None:
                raise NotFoundError("Follow-up not found for this patient")
            for event in previous.history:
                if event.id == change.id:
                    if (
                        event.status != change.status
                        or event.notes != change.notes
                        or (change.due_at and event.due_at != change.due_at)
                    ):
                        raise ValidationError("Update key already used for different details")
                    return previous
            if previous.version != change.expected_version:
                raise ValidationError("Follow-up changed; reload before confirming")
            if previous.status in ("completed", "cancelled"):
                raise ValidationError("This follow-up is already closed")
            if len(previous.history) >= 100:
                raise ValidationError("Follow-up history limit reached")
            due = change.due_at or previous.due_at
            row = previous.model_copy(
                update={
                    "status": change.status,
                    "due_at": due,
                    "notes": change.notes,
                    "version": previous.version + 1,
                    "updated_at": now,
                    "history": [
                        *previous.history,
                        TaskHistory(
                            id=change.id, status=change.status, due_at=due, notes=change.notes, recorded_at=now
                        ),
                    ],
                }
            )
            self._tasks[patient_id, task_id] = row
            return row

    def barriers(self, patient_id: UUID) -> list[Barrier]:
        with self._lock:
            return sorted(
                [row for (owner, _), row in self._barriers.items() if owner == patient_id],
                key=lambda row: row.occurred_at,
            )

    def add_barrier(self, row: Barrier) -> Barrier:
        with self._lock:
            previous = self._barriers.get((row.patient_id, row.id))
            if previous:
                if previous.model_dump(exclude={"recorded_at"}) != row.model_dump(exclude={"recorded_at"}):
                    raise ValidationError("Barrier key already used for different details")
                return previous
            self._barriers[row.patient_id, row.id] = row
            return row


class SupabaseCareRepository:
    def __init__(self, client: SupabaseDataClient):
        self._client = client

    def stock(self, patient_id: UUID, medication_id: UUID) -> list[StockTransaction]:
        self._client.check_patient(patient_id)
        return [
            StockTransaction.model_validate(row)
            for row in self._client.all_rows(
                "inventory_transactions", medication_id=f"eq.{medication_id}", order="recorded_at.asc,id.asc"
            )
        ]

    def append_stock(
        self, patient_id: UUID, medication_id: UUID, values: StockInput, now: datetime
    ) -> StockTransaction:
        self._client.check_patient(patient_id)
        row = self._client.request(
            "POST",
            "/rest/v1/rpc/record_inventory_transaction",
            body={
                "p_medication_id": str(medication_id),
                "p_values": values.model_dump(mode="json", exclude={"confirmed"}),
            },
        )
        return StockTransaction.model_validate(row)

    def tasks(self, patient_id: UUID) -> list[CareTask]:
        self._client.check_patient(patient_id)
        return [
            CareTask.model_validate(row)
            for row in self._client.all_rows("medication_care_tasks", order="due_at.asc,id.asc")
        ]

    def create_task(self, task: CareTask) -> CareTask:
        self._client.check_patient(task.patient_id)
        row = self._client.request(
            "POST",
            "/rest/v1/rpc/create_medication_care_task",
            body={
                "p_task": task.model_dump(
                    mode="json",
                    exclude={"patient_id", "history", "version", "status", "demo_only", "created_at", "updated_at"},
                )
            },
        )
        return CareTask.model_validate(row)

    def update_task(self, patient_id: UUID, task_id: UUID, change: TaskUpdate, now: datetime) -> CareTask:
        self._client.check_patient(patient_id)
        row = self._client.request(
            "POST",
            "/rest/v1/rpc/update_medication_care_task",
            body={"p_task_id": str(task_id), "p_change": change.model_dump(mode="json", exclude={"confirmed"})},
        )
        return CareTask.model_validate(row)

    def barriers(self, patient_id: UUID) -> list[Barrier]:
        self._client.check_patient(patient_id)
        return [
            Barrier.model_validate(row)
            for row in self._client.all_rows("adherence_barriers", order="occurred_at.asc,id.asc")
        ]

    def add_barrier(self, row: Barrier) -> Barrier:
        self._client.check_patient(row.patient_id)
        values = self._client.request(
            "POST",
            "/rest/v1/adherence_barriers",
            params={"on_conflict": "patient_id,id"},
            body=row.model_dump(mode="json"),
            prefer="resolution=ignore-duplicates,return=representation",
        )
        if values:
            return Barrier.model_validate(values[0])
        previous = next((value for value in self.barriers(row.patient_id) if value.id == row.id), None)
        if previous is None or previous.model_dump(exclude={"recorded_at"}) != row.model_dump(exclude={"recorded_at"}):
            raise ValidationError("Barrier key already used for different details")
        return previous
