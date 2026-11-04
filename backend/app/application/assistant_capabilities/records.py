"""Actual patient record projections; no occurrence/report/challenge publication."""

from datetime import date
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from ...contracts.assistant_workflows import (
    AttachmentRef,
    BusinessRef,
    ChoiceAction,
    ChoiceOption,
    OperationResult,
    Preparation,
    WorkflowContext,
)
from ...contracts.medication_records import (
    RECORD_READ_SCHEMAS,
    HistoryRecordFields,
    SourceRecordFields,
    StatusRecordFields,
    SummaryRecordFields,
)
from ...contracts.ports import Clock
from ...contracts.temporal import local_day_window
from ...domain.errors import NotFoundError, ValidationError
from ..dosing import DoseScheduleService, SelfReportService
from ..enrollment import MedicationEnrollmentService
from ..medication_understanding import MedicationUnderstandingService
from ..preferences import PreferenceService
from ..record_history import RecordHistoryService
from ..review_summary import ReviewSummaryService
from ..today_attention import read_today_attention


class RecordAdapter:
    capability_ids = frozenset(RECORD_READ_SCHEMAS)

    def __init__(
        self,
        *,
        enrollment: MedicationEnrollmentService,
        schedule: DoseScheduleService,
        reports: SelfReportService,
        history: RecordHistoryService,
        summary: ReviewSummaryService,
        understanding: MedicationUnderstandingService,
        clock: Clock,
        preferences: PreferenceService,
    ):
        self._enrollment, self._schedule, self._reports = enrollment, schedule, reports
        self._history, self._summary, self._understanding = history, summary, understanding
        self._clock, self._preferences = clock, preferences

    @staticmethod
    def _pages(page: int, pages: int):
        options = tuple(
            ChoiceOption(value=f"page:{number}", label_key=key)
            for number, key in ((page - 1, "assistant.medication.previous"), (page + 1, "assistant.medication.next"))
            if 0 <= number < pages
        )
        return (ChoiceAction(action_id="record.page", options=options),) if options else ()

    def _picker(self, context: WorkflowContext, values, medications):
        pages = max(1, (len(medications) + 9) // 10)
        page = values.page if values.page < pages else 0
        rows = medications[page * 10 : page * 10 + 10]
        actions = (
            (
                ChoiceAction(
                    action_id="record.medication",
                    options=tuple(
                        ChoiceOption(
                            value=str(row.id),
                            label_key="assistant.medication.select",
                            label_text=row.display_name[:200],
                        )
                        for row in rows
                    ),
                ),
            )
            if rows
            else ()
        )
        return Preparation(
            input_fields={**values.model_dump(mode="json", exclude_none=True), "page": page},
            prompt_key="assistant.records.choose" if rows else "assistant.records.empty",
            missing_fields=("medication_id",),
            view_fields={"page": page, "page_count": pages},
            actions=(*actions, *self._pages(page, pages)),
        )

    def prepare(
        self,
        context: WorkflowContext,
        values: BaseModel,
        assets: tuple[AttachmentRef, ...],
        results: tuple[BusinessRef, ...] = (),
    ) -> Preparation:
        if assets or results or context.capability_id not in self.capability_ids:
            raise ValidationError("A record query does not accept attachments or business results")
        expected = RECORD_READ_SCHEMAS[context.capability_id]
        if not isinstance(values, expected):
            raise ValidationError("Use the closed input schema for this record query")
        inputs = values.model_dump(mode="json", exclude_none=True)
        visible = dict(inputs)
        medication_id = getattr(values, "medication_id", None)
        regimen_id = getattr(values, "regimen_id", None)
        med = self._enrollment.get_medication(context.owner, medication_id) if medication_id else None
        if medication_id and med is None:
            raise NotFoundError("Medication not found for this patient")
        regimen = self._enrollment.get_regimen(context.owner, regimen_id) if regimen_id else None
        if regimen_id and regimen is None:
            raise NotFoundError("Plan not found for this patient")
        if regimen and medication_id and regimen.patient_medication_id != medication_id:
            raise ValidationError("The plan does not belong to this medicine")
        if regimen and med is None:
            med = self._enrollment.get_medication(context.owner, regimen.patient_medication_id)
        if med:
            visible["medication_name"] = med.display_name
        preferences = self._preferences.get(context.owner)
        timezone = preferences.timezone
        today = self._clock.now().astimezone(ZoneInfo(timezone)).date()
        visible.update(timezone=timezone, as_of=self._clock.now().isoformat())
        capability = context.capability_id
        actions = ()
        if capability in {"medication.status", "medication.source.view", "medication.instructions"} and med is None:
            return self._picker(context, values, self._enrollment.list_medications(context.owner))
        if capability in {"medication.today", "medication.due"}:
            attention = read_today_attention(
                owner=context.owner,
                enrollment=self._enrollment,
                schedule=self._schedule,
                reports=self._reports,
                clock=self._clock,
            )
            medications = self._enrollment.list_medications(context.owner)
            lookup = {row.id: row for row in medications}
            rows = []
            for state in attention.plans:
                plan = self._enrollment.get_regimen(context.owner, state.regimen_id)
                if plan is None or medication_id and plan.patient_medication_id != medication_id:
                    continue
                product = lookup.get(plan.patient_medication_id)
                if product is None:
                    continue
                if capability == "medication.due" and state.state not in {"pending", "as_needed", "unrecorded"}:
                    continue
                rows.append(
                    {
                        **state.model_dump(mode="json"),
                        "medication_id": str(product.id),
                        "medication_name": product.display_name,
                        "version": plan.version_no,
                        "dose_amount": plan.dose_amount,
                        "dose_unit": plan.dose_unit,
                        "frequency_rule": plan.frequency_rule,
                        "is_prn": plan.is_prn,
                        "scheduled_times": [
                            value.isoformat().replace("+00:00", "Z")
                            for value in self._schedule.planned_windows_for_plan(
                                patient_id=context.owner,
                                regimen=plan,
                                windows=[local_day_window(date.fromisoformat(attention.local_date), timezone)],
                            )[0]
                        ],
                        "course_start_date": str(plan.course_start_date) if plan.course_start_date else None,
                        "course_end_date": str(plan.course_end_date) if plan.course_end_date else None,
                    }
                )
            pages = max(1, (len(rows) + 9) // 10)
            page = values.page if values.page < pages else 0
            inputs["page"] = page
            visible.update(
                today={"local_date": attention.local_date, "plans": rows[page * 10 : page * 10 + 10]},
                page=page,
                page_count=pages,
                coverage="planned_times_and_stored_reports",
            )
            actions = self._pages(page, pages)
        elif capability == "medication.status":
            if not isinstance(values, StatusRecordFields):
                raise ValidationError("Choose a valid status date")
            day = values.day or today
            if day > today:
                raise ValidationError("A future date is not dose history")
            inputs["day"] = day.isoformat()
            page = self._history.page(
                context.owner,
                medication_id=med.id,
                range_kind="custom",
                start=day,
                end=day,
                limit=50,
                cursor=values.cursor,
            )
            visible.update(day=day.isoformat(), history=page.model_dump(mode="json"))
        elif capability in {"medication.history", "record.history"}:
            if not isinstance(values, HistoryRecordFields):
                raise ValidationError("Choose valid history filters")
            page = self._history.page(context.owner, **values.model_dump())
            visible["history"] = page.model_dump(mode="json")
            catalogue = self._history.catalogue(context.owner)
            names = {row.id: row.display_name for row in catalogue.medications}
            visible["history_filters"] = {
                "medications": [{"id": str(row.id), "display_name": row.display_name} for row in catalogue.medications],
                "plans": [
                    {
                        "id": str(row.id),
                        "medication_id": str(row.medication_id),
                        "display_name": names[row.medication_id],
                        "state": row.state,
                    }
                    for row in catalogue.plans
                ],
            }
        elif capability == "record.catalogue":
            catalogue = self._history.catalogue(context.owner)
            pages = max(1, (len(catalogue.medications) + 9) // 10)
            page = values.page if values.page < pages else 0
            meds = catalogue.medications[page * 10 : page * 10 + 10]
            ids = {row.id for row in meds}
            visible.update(
                catalogue={
                    "medications": [row.model_dump(mode="json") for row in meds],
                    "plans": [row.model_dump(mode="json") for row in catalogue.plans if row.medication_id in ids],
                },
                page=page,
                page_count=pages,
            )
            inputs["page"] = page
            actions = self._pages(page, pages)
        elif capability in {"record.summary", "record.visit.prepare"}:
            if not isinstance(values, SummaryRecordFields):
                raise ValidationError("Choose a valid summary period")
            if values.period == "course" and regimen is None:
                catalogue = self._history.catalogue(context.owner)
                names = {row.id: row.display_name for row in catalogue.medications}
                plans = catalogue.plans
                pages = max(1, (len(plans) + 9) // 10)
                page = values.page if values.page < pages else 0
                rows = plans[page * 10 : page * 10 + 10]
                actions = (
                    (
                        ChoiceAction(
                            action_id="record.course",
                            options=tuple(
                                ChoiceOption(
                                    value=str(row.id),
                                    label_key="assistant.medication.select_plan",
                                    label_text=f"{names[row.medication_id][:160]} / {row.state}",
                                )
                                for row in rows
                            ),
                        ),
                    )
                    if rows
                    else ()
                )
                return Preparation(
                    input_fields={**inputs, "page": page},
                    prompt_key="assistant.records.course",
                    missing_fields=("regimen_id",),
                    actions=(*actions, *self._pages(page, pages)),
                    view_fields={"page": page, "page_count": pages},
                )
            if values.period != "course" and regimen is not None:
                raise ValidationError("A plan filter requires the course summary period")
            summary = self._summary.generate(context.owner, values.period, values.regimen_id, timezone)
            visible["summary"] = summary.model_dump(mode="json")
        elif capability == "medication.source.view":
            if not isinstance(values, SourceRecordFields):
                raise ValidationError("Choose an owned source")
            plans = [regimen] if regimen else self._enrollment.list_regimens(context.owner, med.id)
            source_ids = list(
                dict.fromkeys(
                    [row.source_id for row in plans if row.source_id]
                    + ([med.source_id] if not regimen and med.source_id else [])
                )
            )
            rows = []
            pages = max(1, (len(source_ids) + 9) // 10)
            page = values.page if values.page < pages else 0
            inputs["page"] = page
            visible.update(page=page, page_count=pages)
            actions = self._pages(page, pages)
            for source in self._enrollment.get_sources(context.owner, source_ids[page * 10 : page * 10 + 10]):
                rows.append(
                    {
                        "source_id": str(source.id),
                        "source_kind": source.source_kind.value,
                        "review_status": source.review_status.value,
                        "reviewed_at": source.reviewed_at.isoformat() if source.reviewed_at else None,
                        "fields": [
                            {
                                "field_name": field.field_name.value,
                                "field_value": field.model_dump(mode="json")["field_value"],
                                "review_status": field.review_status.value,
                            }
                            for field in self._enrollment.list_source_fields(context.owner, source.id)
                        ],
                    }
                )
            visible["sources"] = rows
        elif capability == "medication.instructions":
            explained = self._understanding.explain(
                patient_id=context.owner,
                medication_id=med.id,
                question="personal_instructions",
                language=context.language,
                timezone=timezone,
            )
            visible["understanding"] = explained.model_dump(mode="json")
        return Preparation(
            input_fields=inputs, view_fields=visible, actions=actions, prompt_key="assistant.records.read"
        )

    def observe(self, context: WorkflowContext, result_ref: BusinessRef) -> OperationResult:
        raise ValidationError("Read-only record queries have no business result to confirm")
