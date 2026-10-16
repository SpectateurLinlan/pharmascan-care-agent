"""Patient-owned stock, reported barriers and medication-related follow-ups.

Uses public regimen/observation/summary interfaces. No dose-event write port,
clinical advice, external notifications or model-created permanent facts.
"""

from datetime import timedelta
from uuid import UUID, uuid5

from ..contracts.long_term import (
    Barrier,
    BarrierInput,
    CareRepository,
    CareReview,
    CareTask,
    CareTaskInput,
    LabelQuantity,
    MedicationCareReport,
    StockInput,
    StockStatus,
    TaskUpdate,
)
from ..contracts.ports import Clock, DoseEventRepository, DoseRuleRepository
from ..domain.errors import NotFoundError, ValidationError
from ..domain.inventory import count_unit, scheduled_daily_requirement
from .enrollment import MedicationEnrollmentService
from .observations import ObservationService
from .review_summary import ReviewSummaryService


class LongTermCareService:
    def __init__(
        self,
        repository: CareRepository,
        enrollment: MedicationEnrollmentService,
        events: DoseEventRepository,
        observations: ObservationService,
        summaries: ReviewSummaryService,
        clock: Clock,
        rules: DoseRuleRepository | None = None,
    ):
        self._repo, self._enrollment, self._events = repository, enrollment, events
        self._observations, self._summaries, self._clock = observations, summaries, clock
        self._rules = rules

    def _medication(self, patient_id: UUID, medication_id: UUID):
        match = self._enrollment.get_medication(patient_id, medication_id)
        if match is None:
            raise NotFoundError("Medication not found for this patient")
        return match

    def _regimen(self, patient_id: UUID, regimen_id: UUID):
        row = self._enrollment.get_regimen(patient_id, regimen_id)
        if row is None:
            raise NotFoundError("Regimen not found for this patient")
        return row

    def inventory(self, patient_id: UUID, medication_id: UUID, timezone: str = "Asia/Singapore") -> StockStatus:
        self._medication(patient_id, medication_id)
        rows = self._repo.stock(patient_id, medication_id)
        regimens = self._enrollment.list_regimens(patient_id, medication_id)
        label_quantities = []
        seen_sources = set()
        for regimen in regimens:
            if not regimen.source_id or regimen.source_id in seen_sources:
                continue
            seen_sources.add(regimen.source_id)
            source = self._enrollment.get_source(patient_id, regimen.source_id)
            evidence = source.extraction_evidence if source else None
            # Multi-product documents require an explicit per-product mapping.
            if evidence and len(evidence.candidates) == 1:
                quantity = evidence.candidates[0].regimen_evidence.supplied_quantity
                if quantity:
                    label_quantities.append(
                        LabelQuantity(
                            source_document_id=source.id,
                            amount=quantity.amount,
                            unit=quantity.unit,
                            printed_line=quantity.line,
                            review_status=source.review_status.value,
                        )
                    )
        counts = [row for row in rows if row.kind == "count"]
        now = self._clock.now()
        note = "Stock is unknown until you confirm a physical count. Label quantity is not current stock."
        if not counts:
            return StockStatus(
                medication_id=medication_id, transactions=rows, estimate_note=note, label_quantities=label_quantities
            )
        count, latest = counts[-1], rows[-1]
        versions = {row.id: row for row in regimens}
        reports = self._events.list_for_patient(patient_id, count.recorded_at, now + timedelta(microseconds=1))
        used = sum(
            versions[event.regimen_id].dose_amount
            for event in reports
            if event.regimen_id in versions
            and event.intake_status.value == "reported_taken"
            and versions[event.regimen_id].dose_amount is not None
            and count_unit(versions[event.regimen_id].dose_unit) == count.unit
        )
        remaining = max(0, latest.stock_after - used)
        zones = {}
        if self._rules:
            for regimen in regimens:
                if regimen.state.value == "active":
                    stored = self._rules.list_for_regimen(patient_id, regimen.id)
                    if stored:
                        zones[regimen.id] = stored[0].timezone
        daily = scheduled_daily_requirement(regimens, count.unit, now, timezone, zones)
        return StockStatus(
            medication_id=medication_id,
            unit=count.unit,
            last_confirmed_stock=count.quantity,
            last_confirmed_at=count.recorded_at,
            estimated_remaining=remaining,
            daily_requirement=daily,
            estimated_days=remaining / daily if daily else None,
            low_stock=bool(daily and remaining <= latest.low_threshold),
            transactions=rows,
            label_quantities=label_quantities,
            estimate_note="Estimate from confirmed count, stock transactions and compatible "
            "patient-reported taken events; "
            "unreported consumption is unknown. Weekly demand is an average, not a run-out date. "
            "PRN, unsupported units or incomplete schedules have no daily estimate. Count again to correct it.",
        )

    def record_stock(self, patient_id: UUID, medication_id: UUID, values: StockInput, timezone: str) -> StockStatus:
        self._medication(patient_id, medication_id)
        if not values.confirmed:
            raise ValidationError("Confirm the stock change before saving")
        self._repo.append_stock(patient_id, medication_id, values, self._clock.now())
        status = self.inventory(patient_id, medication_id, timezone)
        self._reconcile_refill(patient_id, medication_id, status)
        return status

    def _reconcile_refill(self, patient_id: UUID, medication_id: UUID, stock: StockStatus):
        now = self._clock.now()
        open_rows = [
            row
            for row in self._repo.tasks(patient_id)
            if row.medication_id == medication_id
            and row.source == "stock_estimate"
            and row.status in ("open", "contacted", "deferred")
        ]
        if stock.low_stock and not open_rows:
            # One task per stock revision; cancelled tasks are not recreated on reads.
            key = uuid5(medication_id, "refill:" + str(stock.transactions[-1].id))
            self._repo.create_task(
                CareTask(
                    patient_id=patient_id,
                    id=key,
                    category="refill",
                    title="Review medication supply",
                    medication_id=medication_id,
                    due_at=now,
                    source="stock_estimate",
                    created_at=now,
                    updated_at=now,
                    notes="Low-stock estimate; contact your pharmacy to check supply. This is not an automatic refill.",
                )
            )
        if not stock.low_stock:
            for task in open_rows:
                self._repo.update_task(
                    patient_id,
                    task.id,
                    TaskUpdate(
                        id=uuid5(task.id, "stock:" + str(stock.transactions[-1].id)),
                        expected_version=task.version,
                        status="completed" if stock.daily_requirement else "cancelled",
                        confirmed=True,
                        notes="Supply rechecked" if stock.daily_requirement else "No applicable scheduled plan",
                    ),
                    now,
                )

    def tasks(self, patient_id: UUID) -> list[CareTask]:
        # No writes on query. Expired/stopped-plan stock tasks are suppressed from
        # actionable views but retained in storage and review history.
        rows = self._repo.tasks(patient_id)
        return rows

    def refresh_refill_tasks(self, patient_id: UUID, timezone: str) -> list[CareTask]:
        """Reconcile derived supply tasks on the shared reminder presentation tick.

        No stock/dose data changes. Idempotent task IDs derive from ledger revision.
        """
        for medication in self._enrollment.list_medications(patient_id):
            status = self.inventory(patient_id, medication.id, timezone)
            if status.transactions:
                self._reconcile_refill(patient_id, medication.id, status)
        return self.actionable_tasks(patient_id, timezone)

    def actionable_tasks(self, patient_id: UUID, timezone: str) -> list[CareTask]:
        rows = []
        for row in self.tasks(patient_id):
            if row.status not in ("open", "contacted", "deferred"):
                continue
            if row.source == "stock_estimate" and row.medication_id:
                if not self.inventory(patient_id, row.medication_id, timezone).low_stock:
                    continue
            rows.append(row)
        return rows

    def create_task(self, patient_id: UUID, values: CareTaskInput) -> CareTask:
        if not values.confirmed:
            raise ValidationError("Review and confirm the medication follow-up")
        if values.medication_id:
            self._medication(patient_id, values.medication_id)
        if values.regimen_id:
            regimen = self._regimen(patient_id, values.regimen_id)
            if values.medication_id and regimen.patient_medication_id != values.medication_id:
                raise ValidationError("Regimen and medication do not agree")
        now = self._clock.now()
        return self._repo.create_task(
            CareTask(
                **values.model_dump(exclude={"confirmed"}),
                patient_id=patient_id,
                created_at=now,
                updated_at=now,
            )
        )

    def update_task(self, patient_id: UUID, task_id: UUID, values: TaskUpdate) -> CareTask:
        if not values.confirmed:
            raise ValidationError("Confirm the follow-up change")
        if values.status == "deferred" and (values.due_at is None or values.due_at <= self._clock.now()):
            raise ValidationError("Choose a future follow-up time")
        return self._repo.update_task(patient_id, task_id, values, self._clock.now())

    def record_barrier(self, patient_id: UUID, values: BarrierInput) -> Barrier:
        if not values.confirmed:
            raise ValidationError("Confirm your own reported difficulty")
        if values.occurred_at > self._clock.now() + timedelta(minutes=5):
            raise ValidationError("A reported difficulty cannot be in the future")
        if values.regimen_id:
            self._regimen(patient_id, values.regimen_id)
        if values.follow_up_task_id and not any(row.id == values.follow_up_task_id for row in self.tasks(patient_id)):
            raise NotFoundError("Follow-up not found for this patient")
        return self._repo.add_barrier(
            Barrier(
                **values.model_dump(exclude={"confirmed"}),
                patient_id=patient_id,
                recorded_at=self._clock.now(),
            )
        )

    def barriers(self, patient_id: UUID) -> list[Barrier]:
        return self._repo.barriers(patient_id)

    def validate_proposal(self, patient_id: UUID, proposal: CareReview) -> None:
        """Validate model-proposed references without performing any write."""
        if proposal.medication_id:
            self._medication(patient_id, proposal.medication_id)
        values = proposal.barrier or proposal.task
        if values and values.regimen_id:
            regimen = self._regimen(patient_id, values.regimen_id)
            if (
                proposal.task
                and proposal.task.medication_id
                and regimen.patient_medication_id != proposal.task.medication_id
            ):
                raise ValidationError("Regimen and medication do not agree")
        if proposal.task and proposal.task.medication_id:
            self._medication(patient_id, proposal.task.medication_id)

    def review(self, patient_id: UUID, days: int, timezone: str) -> MedicationCareReport:
        if days not in (7, 30):
            raise ValidationError("Choose 7 or 30 days")
        now = self._clock.now()
        notes = self._observations.list(patient_id, now - timedelta(days=days), now + timedelta(microseconds=1))
        summary = self._summaries.generate(patient_id, "week" if days == 7 else "month", timezone=timezone)
        barriers = [row for row in self.barriers(patient_id) if row.occurred_at >= now - timedelta(days=days)]
        stocks = [self.inventory(patient_id, row.id, timezone) for row in self._enrollment.list_medications(patient_id)]
        tasks = self.actionable_tasks(patient_id, timezone)
        sources = []
        for medication in self._enrollment.list_medications(patient_id):
            for regimen in self._enrollment.list_regimens(patient_id, medication.id):
                source = self._enrollment.get_source(patient_id, regimen.source_id) if regimen.source_id else None
                sources.append(
                    {
                        "medication_id": str(medication.id),
                        "name": medication.display_name,
                        "regimen_id": str(regimen.id),
                        "version": regimen.version_no,
                        "state": regimen.state.value,
                        "source_document_id": str(source.id) if source else None,
                        "source_type": source.source_kind.value if source else None,
                        "review_status": source.review_status.value if source else None,
                        "patient_review_is_professional_verification": False,
                    }
                )
        questions = list(summary.questions)
        if barriers:
            questions.append("Discuss your reported medication difficulties and chosen support actions.")
        if any(row.low_stock for row in stocks):
            questions.append("Check medication supply and refill arrangements with your pharmacy.")
        return MedicationCareReport.model_validate(
            {
                "generated_at": now.isoformat(),
                "timezone": timezone,
                "observation_window_days": days,
                "summary": summary.model_dump(mode="json"),
                "trends": observation_trends(notes),
                "barriers": [row.model_dump(mode="json") for row in barriers],
                "inventory": [
                    row.model_dump(mode="json", exclude={"transactions", "label_quantities"}) for row in stocks
                ],
                "follow_ups": [row.model_dump(mode="json") for row in tasks],
                "questions": questions,
                "source_records": sources,
                "adherence_denominator": "No adherence percentage: stored reports and generated occurrences "
                "are distinct; "
                "unrecorded is not missed. Summary week/month is calendar-to-date; observations use rolling 7/30 days.",
                "source_note": "Patient-reported records; no diagnosis, drug causality "
                "or professional verification inferred.",
            }
        )


def observation_trends(rows) -> list[dict[str, object]]:
    """Group compatible units; show observed differences, never causal interpretation."""
    groups: dict[tuple[str, str], list] = {}
    for row in rows:
        if row.value is not None and row.unit and row.kind != "note":
            groups.setdefault((row.kind, row.unit), []).append(row)
    output = []
    for (kind, unit), values in sorted(groups.items()):
        values.sort(key=lambda row: row.occurred_at)
        output.append(
            {
                "kind": kind,
                "unit": unit,
                "count": len(values),
                "start": values[0].occurred_at.isoformat(),
                "end": values[-1].occurred_at.isoformat(),
                "change": values[-1].value - values[0].value if len(values) >= 2 else None,
                "points": [
                    {"at": row.occurred_at.isoformat(), "value": row.value, "secondary_value": row.secondary_value}
                    for row in values
                ],
                "note": "Irregular patient sampling; missing measurements are unknown. "
                "Fewer than two records cannot establish change. No drug-cause inference.",
            }
        )
    return output
