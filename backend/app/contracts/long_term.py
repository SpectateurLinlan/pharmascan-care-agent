"""Public long-term care DTOs. Patient identity is never a request argument."""

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .review_summary import ReviewSummary

CountUnit = Literal["tablet", "capsule"]
StockKind = Literal["count", "refill", "adjustment", "lost", "discarded", "damaged"]
TaskCategory = Literal[
    "medication_review",
    "medication_follow_up",
    "refill",
    "monitoring",
    "adherence",
    "symptom_follow_up",
    "expiry_storage",
]
TaskStatus = Literal["open", "contacted", "deferred", "completed", "cancelled"]
BarrierKind = Literal[
    "forgetfulness",
    "running_out",
    "side_effect_concern",
    "scheduling",
    "unclear_instructions",
    "complexity",
    "unsure_taken",
    "other",
    "prefer_not_to_say",
]


class CareDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True, allow_inf_nan=False)


class StockInput(CareDTO):
    id: UUID
    kind: StockKind
    quantity: float = Field(ge=-100000, le=100000)
    unit: CountUnit
    low_threshold: float = Field(default=7, ge=0, le=10000)
    note: str = Field(default="", max_length=500)
    confirmed: bool = False

    @model_validator(mode="after")
    def valid_quantity(self):
        if self.kind in ("count", "refill") and self.quantity < 0:
            raise ValueError("Count and refill quantities must be non-negative")
        if self.kind in ("refill", "lost", "discarded", "damaged") and self.quantity <= 0:
            raise ValueError("Enter a positive number of units")
        return self


class StockTransaction(CareDTO):
    patient_id: UUID
    medication_id: UUID
    id: UUID
    kind: StockKind
    quantity: float
    unit: CountUnit
    low_threshold: float
    note: str
    stock_after: float
    recorded_at: datetime
    source: Literal["patient_confirmed"] = "patient_confirmed"
    demo_only: Literal[True] = True


class LabelQuantity(CareDTO):
    source_document_id: UUID
    amount: float | None
    unit: str | None
    printed_line: str
    review_status: str


class StockStatus(CareDTO):
    medication_id: UUID
    unit: CountUnit | None = None
    last_confirmed_stock: float | None = None
    last_confirmed_at: datetime | None = None
    estimated_remaining: float | None = None
    daily_requirement: float | None = None
    estimated_days: float | None = None
    low_stock: bool = False
    estimate_note: str
    transactions: list[StockTransaction]
    label_quantities: list[LabelQuantity] = Field(default_factory=list)


class CareTaskInput(CareDTO):
    id: UUID
    category: TaskCategory
    title: str = Field(min_length=1, max_length=160)
    due_at: AwareDatetime
    medication_id: UUID | None = None
    regimen_id: UUID | None = None
    notes: str = Field(default="", max_length=1000)
    confirmed: bool = False


class TaskUpdate(CareDTO):
    id: UUID
    expected_version: int = Field(ge=1)
    status: TaskStatus
    due_at: AwareDatetime | None = None
    notes: str = Field(default="", max_length=1000)
    confirmed: bool = False


class TaskHistory(CareDTO):
    id: UUID
    status: TaskStatus
    due_at: datetime
    notes: str
    recorded_at: datetime


class CareTask(CareDTO):
    patient_id: UUID
    id: UUID
    category: TaskCategory
    title: str
    due_at: datetime
    medication_id: UUID | None = None
    regimen_id: UUID | None = None
    status: TaskStatus = "open"
    notes: str = ""
    source: Literal["patient_reported", "stock_estimate"] = "patient_reported"
    version: int = 1
    history: list[TaskHistory] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    demo_only: Literal[True] = True


class BarrierInput(CareDTO):
    id: UUID
    category: BarrierKind
    occurred_at: AwareDatetime
    regimen_id: UUID | None = None
    description: str = Field(default="", max_length=1000)
    chosen_action: str = Field(default="", max_length=500)
    follow_up_task_id: UUID | None = None
    confirmed: bool = False


class Barrier(CareDTO):
    patient_id: UUID
    id: UUID
    category: BarrierKind
    occurred_at: datetime
    regimen_id: UUID | None = None
    description: str
    chosen_action: str
    follow_up_task_id: UUID | None = None
    source: Literal["patient_reported"] = "patient_reported"
    recorded_at: datetime
    demo_only: Literal[True] = True


class CareReview(CareDTO):
    """An editable proposal only. Confirmation flags are always false here."""

    action: Literal["stock", "barrier", "task", "task_update"]
    medication_id: UUID | None = None
    task_id: UUID | None = None
    stock: StockInput | None = None
    barrier: BarrierInput | None = None
    task: CareTaskInput | None = None
    task_update: TaskUpdate | None = None


class CareRepository(Protocol):
    def stock(self, patient_id: UUID, medication_id: UUID) -> list[StockTransaction]: ...
    def append_stock(
        self, patient_id: UUID, medication_id: UUID, values: StockInput, now: datetime
    ) -> StockTransaction: ...
    def tasks(self, patient_id: UUID) -> list[CareTask]: ...
    def create_task(self, task: CareTask) -> CareTask: ...
    def update_task(self, patient_id: UUID, task_id: UUID, change: TaskUpdate, now: datetime) -> CareTask: ...
    def barriers(self, patient_id: UUID) -> list[Barrier]: ...
    def add_barrier(self, row: Barrier) -> Barrier: ...


class TrendPoint(CareDTO):
    at: datetime
    value: float
    secondary_value: float | None


class ObservationTrend(CareDTO):
    kind: str
    unit: str
    count: int
    start: datetime
    end: datetime
    change: float | None
    points: list[TrendPoint]
    note: str


class StockOverview(CareDTO):
    medication_id: UUID
    unit: CountUnit | None
    last_confirmed_stock: float | None
    last_confirmed_at: datetime | None
    estimated_remaining: float | None
    daily_requirement: float | None
    estimated_days: float | None
    low_stock: bool
    estimate_note: str


class SourceRecord(CareDTO):
    medication_id: UUID
    name: str
    regimen_id: UUID
    version: int
    state: str
    source_document_id: UUID | None
    source_type: str | None
    review_status: str | None
    patient_review_is_professional_verification: Literal[False] = False


class MedicationCareReport(CareDTO):
    generated_at: datetime
    timezone: str
    observation_window_days: Literal[7, 30]
    summary: ReviewSummary
    trends: list[ObservationTrend]
    barriers: list[Barrier]
    inventory: list[StockOverview]
    follow_ups: list[CareTask]
    questions: list[str]
    source_records: list[SourceRecord]
    adherence_denominator: str
    source_note: str
