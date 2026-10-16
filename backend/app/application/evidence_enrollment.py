"""Progressive source reconciliation; OCR supplies evidence, patients review plans."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import date, timedelta
from uuid import UUID, uuid5

from ..contracts.dto import FrequencyRuleDTO, PatientMedicationDTO, RegimenDraftInput, SourceDocumentDTO, SourceFieldDTO
from ..contracts.enums import FieldName, SourceKind, SourceReviewStatus
from ..contracts.medication_evidence import (
    EnrollmentTask,
    EvidenceRepository,
    MedicationImage,
    PrivateImageStore,
    ProductEvidence,
    SourceEvidenceView,
    SourceLink,
)
from ..contracts.ports import (
    Clock,
    IdGenerator,
    PatientMedicationRepository,
    SourceDocumentRepository,
    SourceFieldRepository,
)
from ..contracts.source_extraction import ListedMedication
from ..domain.errors import NotFoundError, ProviderUnavailableError, RegimenOverlapError, ValidationError
from .enrollment import MedicationEnrollmentService
from .printed_instructions import apply_printed_parts, validate_printed_review
from .source_preview import SourcePreviewService


def evidence_name(name: str, strength: str | None) -> str:
    """Text-only alias comparison; strength/form remain independently reconciled."""
    if strength:
        suffix = r"\s*".join(re.escape(char) for char in re.sub(r"\s+", "", strength))
        name = re.sub(r"\s*" + suffix + r"\s*$", "", name, flags=re.I)
    return " ".join(name.casefold().split())


def product_name(product: ProductEvidence) -> str:
    name = product.name
    if product.formulation:
        # Only remove a documented release marker; formulation is compared separately.
        name = re.sub(r"\b(extended release|delayed release|ER|XR|SR|MR|DR)\b", "", name, flags=re.I)
    return evidence_name(name, product.strength)


def printed_regimen(name: str, directions: str | None) -> RegimenDraftInput:
    """Extract only explicit quantity/unit/clock times; never derive from strength or supply."""
    text = directions or ""
    amount = re.search(r"\b(?:take|use)\s+(\d+(?:\.\d+)?)\s+(tablets?|capsules?)\b", text, re.I)
    times = re.findall(r"\b(?:[01]\d|2[0-3]):[0-5]\d\b", text)
    start = re.search(r"\bstart(?: date)?\s*:?\s*(\d{4}-\d{2}-\d{2})\b", text, re.I)
    end = re.search(r"\bend(?: date)?\s*:?\s*(\d{4}-\d{2}-\d{2})\b", text, re.I)
    duration = re.search(r"\bfor\s+(\d{1,3})\s+days?\b", text, re.I)
    start_date = end_date = None
    try:
        start_date = date.fromisoformat(start[1]) if start else None
        end_date = date.fromisoformat(end[1]) if end else None
    except ValueError:
        start_date = end_date = None
    if start_date and not end_date and duration and 1 <= int(duration[1]) <= 365:
        end_date = start_date + timedelta(days=int(duration[1]) - 1)
    food = re.search(r"\b(with|before|after) food\b", text, re.I)
    return RegimenDraftInput(
        medication_name=name,
        dose_amount=float(amount[1]) if amount else None,
        dose_unit=amount[2].lower().rstrip("s") if amount else None,
        frequency_rule=FrequencyRuleDTO(kind="daily", local_times=sorted(set(times)))
        if times and re.search(r"\b(daily|every day)\b", text, re.I)
        else None,
        food_instruction=food[0].lower() if food else None,
        course_start_date=start_date,
        course_end_date=end_date,
    )


class EvidenceEnrollmentService:
    def __init__(
        self,
        *,
        repository: EvidenceRepository,
        medications: PatientMedicationRepository,
        sources: SourceDocumentRepository,
        fields: SourceFieldRepository,
        enrollment: MedicationEnrollmentService,
        preview: SourcePreviewService | None,
        storage: PrivateImageStore,
        normalize: Callable[[bytes], bytes],
        clock: Clock,
        ids: IdGenerator,
    ):
        self._repo, self._medications, self._sources, self._fields = repository, medications, sources, fields
        self._enrollment, self._preview, self._storage = enrollment, preview, storage
        self._normalize, self._clock, self._ids = normalize, clock, ids

    def list(self, patient_id: UUID) -> list[EnrollmentTask]:
        return [row for row in self._repo.list(patient_id, "tasks") if isinstance(row, EnrollmentTask)]

    def get(self, patient_id: UUID, task_id: UUID) -> EnrollmentTask:
        row = self._repo.get(patient_id, "tasks", task_id)
        if not isinstance(row, EnrollmentTask):
            raise NotFoundError("Enrollment task not found")
        return row

    def sources(self, patient_id: UUID, task_id: UUID) -> list[SourceEvidenceView]:
        task = self.get(patient_id, task_id)
        links = {row.source_id: row for row in self._repo.list(patient_id, "sources") if isinstance(row, SourceLink)}
        return [
            SourceEvidenceView(**row.model_dump(), recorded_at=links[key].recorded_at if key in links else None)
            for key in task.source_ids
            if (row := self._sources.get(patient_id, key)) is not None
        ]

    def attach(
        self,
        *,
        patient_id: UUID,
        task_id: UUID,
        image: bytes,
        source_kind: str,
        medication_id: UUID | None,
        consent: bool,
        demo_only: bool,
        automatically_routed: bool = False,
    ) -> EnrollmentTask:
        if not consent or not demo_only:
            raise ValidationError("Consented synthetic source files only")
        if source_kind not in {"package", "pharmacy_label", "prescription"}:
            raise ValidationError("PDF extraction is not available; upload a label image or enter instructions")
        existing = self._repo.get(patient_id, "tasks", task_id)
        task = existing if isinstance(existing, EnrollmentTask) else None
        if task and (task.status == "draft_created" or len(task.source_ids) >= 10):
            raise ValidationError("Start a new evidence task for a new course")
        clean = self._normalize(image)
        digest = hashlib.sha256(clean).hexdigest()
        if task:
            if medication_id and medication_id != task.medication_id:
                raise ValidationError("Supplement must belong to the same selected medication")
            for row in self._repo.list(patient_id, "images"):
                if (
                    isinstance(row, MedicationImage)
                    and row.medication_id == task.medication_id
                    and row.checksum == digest
                ):
                    return task
        if self._preview is None:
            raise ProviderUnavailableError("Source extraction unavailable")
        own_tasks = self.list(patient_id)
        listed = tuple(
            ListedMedication(
                id=str(medication.id),
                name=medication.display_name,
                strength=next((row.product.strength for row in own_tasks if row.medication_id == medication.id), None),
            )
            for medication in self._repo.medications(patient_id)[:20]
        )
        extraction = self._preview.preview(
            content=clean, source_kind=source_kind, consent=True, demo_only=True, medications=listed
        )
        if extraction.label_kind == "none" or len(extraction.candidates) != 1:
            raise ValidationError("Choose a source with one clearly named medication, or use manual entry")
        candidate = extraction.candidates[0]
        if automatically_routed:
            # check-input identifies text vs pills, not a dispensing document's
            # authority. Use read-label evidence for source kind, then require review.
            if extraction.label_kind not in {"package", "dispensing"}:
                raise ValidationError("Please choose the source type after checking the original document")
            source_kind = "pharmacy_label" if extraction.label_kind == "dispensing" else "package"
        product = ProductEvidence(
            name=candidate.product.name[:160],
            strength=candidate.product.strength,
            dose_form=candidate.product.dose_form.value if candidate.product.dose_form else None,
            formulation={"ER": "extended release", "DR": "delayed release"}.get(candidate.product.release)
            or (
                "extended release"
                if any("extended release" in line.lower() for line in candidate.product.source_lines)
                else None
            ),
            brand=candidate.product.brand,
            ingredients=[row.name for row in candidate.product.ingredients],
            external_identifiers={"rxcui": candidate.product.rxcui} if candidate.product.rxcui else {},
        )
        source_id = extraction.source_document_id
        self._sources.add(
            SourceDocumentDTO(
                id=source_id,
                patient_id=patient_id,
                source_kind=SourceKind(source_kind),
                review_status=SourceReviewStatus.EXTRACTED,
                reviewed_at=None,
                extraction_evidence=extraction,
            )
        )
        for field, value in [
            (FieldName.MEDICATION_NAME, product.name),
            (FieldName.STRENGTH, product.strength),
            (FieldName.FORM, product.dose_form),
        ]:
            if value is not None:
                self._fields.add(
                    SourceFieldDTO(
                        id=self._ids.new_id(),
                        patient_id=patient_id,
                        source_id=source_id,
                        field_name=field,
                        field_value=value,
                        review_status=SourceReviewStatus.EXTRACTED,
                        reviewed_at=None,
                    )
                )
        if task is None:
            medication = self._medications.get(patient_id, medication_id) if medication_id else None
            if medication_id and medication is None:
                raise NotFoundError("Owned medication not found")
            existing_tasks = self.list(patient_id)
            if medication is None:
                duplicates = [
                    row.id
                    for row in self._repo.medications(patient_id)
                    if evidence_name(
                        row.display_name,
                        next(
                            (task.product.strength for task in existing_tasks if task.medication_id == row.id),
                            None,
                        ),
                    )
                    == evidence_name(product.name, product.strength)
                ][:10]
                medication = PatientMedicationDTO(
                    id=self._ids.new_id(), patient_id=patient_id, display_name=product.name, source_id=source_id
                )
                self._medications.add(medication)
            else:
                duplicates = []
            prior = next((row for row in existing_tasks if row.medication_id == medication.id), None)
            base_product = prior.product if prior else ProductEvidence(name=medication.display_name)
            task = EnrollmentTask(
                id=task_id,
                patient_id=patient_id,
                medication_id=medication.id,
                product=base_product if medication_id else product,
                possible_duplicate_ids=duplicates,
                updated_at=self._clock.now(),
            )
            self._repo.add("tasks", task)
        conflicts = list(task.conflicts)
        values = task.product.model_dump()
        for field in ("name", "strength", "dose_form", "formulation", "brand"):
            old, new = getattr(task.product, field), getattr(product, field)
            differs = (
                product_name(task.product) != product_name(product)
                if field == "name" and old and new
                else bool(old and new and old.casefold().strip() != new.casefold().strip())
            )
            if old and new and differs:
                conflicts.append(f"{field}: {old} / {new} (source {source_id})")
            elif not old and new:
                values[field] = new
        if (
            values["ingredients"]
            and product.ingredients
            and {value.casefold().strip() for value in values["ingredients"]}
            != {value.casefold().strip() for value in product.ingredients}
        ):
            conflicts.append(f"ingredients: conflicting product ingredients (source {source_id})")
        old_code, new_code = values["external_identifiers"].get("rxcui"), product.external_identifiers.get("rxcui")
        if old_code and new_code and old_code != new_code:
            conflicts.append(f"product_code: conflicting source product identifiers (source {source_id})")
        elif not old_code and new_code:
            values["external_identifiers"] = product.external_identifiers
        if not values["ingredients"]:
            values["ingredients"] = product.ingredients
        patient_instructions = source_kind in {"pharmacy_label", "prescription"} and extraction.label_kind not in {
            "package",
            "none",
        }
        proposal = printed_regimen(
            task.product.name,
            candidate.regimen_evidence.directions.value
            if patient_instructions and candidate.regimen_evidence.directions
            else None,
        )
        parts = candidate.regimen_evidence.instructions if patient_instructions else None
        if parts:
            proposal = apply_printed_parts(proposal, parts)
            for prior in self.sources(patient_id, task.id):
                evidence = prior.extraction_evidence
                if not evidence or evidence.label_kind != "dispensing" or prior.source_kind == SourceKind.PACKAGE:
                    continue
                for previous in evidence.candidates:
                    before = previous.regimen_evidence.instructions
                    if not before:
                        continue
                    for field in ("dose", "times_per_day", "every_hours", "food", "duration", "max_per_day"):
                        first, second = getattr(before, field), getattr(parts, field)
                        if first is not None and second is not None and first != second:
                            conflicts.append(f"regimen.{field}: conflicting printed instructions (source {source_id})")
                    if (before.as_needed and (parts.times_per_day or parts.every_hours)) or (
                        parts.as_needed and (before.times_per_day or before.every_hours)
                    ):
                        conflicts.append(f"regimen.schedule: conflicting PRN instructions (source {source_id})")
        merged = task.suggested_regimen.model_dump() if task.suggested_regimen else proposal.model_dump()
        for field in (
            "dose_amount",
            "dose_unit",
            "frequency_rule",
            "food_instruction",
            "course_start_date",
            "course_end_date",
            "is_prn",
        ):
            old, new = merged.get(field), proposal.model_dump().get(field)
            if old and new and old != new:
                conflicts.append(f"regimen.{field}: conflicting printed instructions (source {source_id})")
            elif not old and new:
                merged[field] = new
        printed_days = task.printed_course_days
        directions = candidate.regimen_evidence.directions
        if patient_instructions and (directions or parts):
            duration_text = " ".join(
                [directions.value if directions else "", "for " + (parts.duration or "") if parts else ""]
            )
            explicit_days = [int(value) for value in re.findall(r"\bfor\s+(\d{1,3})\s+days?\b", duration_text, re.I)]
            for days in explicit_days:
                if 1 <= days <= 365:
                    if printed_days and days != printed_days:
                        conflicts.append(
                            f"regimen.course_dates: conflicting printed course duration (source {source_id})"
                        )
                    else:
                        printed_days = days
        suggested = RegimenDraftInput.model_validate(merged)
        missing = ["dose_amount", "dose_unit", "schedule"]
        if suggested:
            missing = [
                key
                for key, value in [
                    ("dose_amount", suggested.dose_amount),
                    ("dose_unit", suggested.dose_unit),
                    ("schedule", suggested.frequency_rule or suggested.is_prn),
                ]
                if not value
            ]
        if task.possible_duplicate_ids:
            missing.append("existing_product_choice")
        if printed_days:
            missing += [key for key in ("course_start_date", "course_end_date") if not getattr(suggested, key)]
        status = "conflict" if conflicts else "pending_information" if missing else "ready_for_review"
        updated = task.model_copy(
            update={
                "product": ProductEvidence(**values),
                "product_missing": [key for key in ("strength", "dose_form", "ingredients") if not values[key]],
                "printed_course_days": printed_days,
                "source_ids": [*task.source_ids, source_id],
                "conflicts": conflicts,
                "missing": missing,
                "suggested_regimen": suggested,
                "status": status,
                "version": task.version + 1,
                "updated_at": self._clock.now(),
            }
        )
        self._storage.put(f"{patient_id}/{task.medication_id}/{digest}.png", clean)
        image_row = MedicationImage(
            id=uuid5(task.medication_id, digest + source_kind),
            patient_id=patient_id,
            medication_id=task.medication_id,
            image_kind="package" if source_kind == "package" else "source",
            storage_path=f"{patient_id}/{task.medication_id}/{digest}.png",
            checksum=digest,
            source_description=source_kind,
            source_id=source_id,
            eligibility_reason="source_photo_not_loose_pill",
            created_at=self._clock.now(),
        )
        self._repo.add("images", image_row)
        self._repo.add(
            "sources",
            SourceLink(
                id=uuid5(task.medication_id, str(source_id)),
                patient_id=patient_id,
                medication_id=task.medication_id,
                source_id=source_id,
                recorded_at=self._clock.now(),
            ),
        )
        self._repo.update_task(updated, task.version)
        return updated

    def prepare_review(
        self,
        *,
        patient_id: UUID,
        task_id: UUID,
        draft: RegimenDraftInput,
        distinct_product_confirmed: bool,
        patient_reviewed: bool,
        product_category: str = "unknown",
        replace_active_plan: bool = False,
    ) -> EnrollmentTask:
        task = self.get(patient_id, task_id)
        if product_category not in {"unknown", "POM", "P", "GSL", "supplement"}:
            raise ValidationError("Unsupported product category")
        if not patient_reviewed or task.conflicts:
            raise ValidationError("Review conflicting sources before creating a medication plan")
        for source in self.sources(patient_id, task_id):
            extraction = source.extraction_evidence
            if extraction and extraction.label_kind == "dispensing" and source.source_kind != SourceKind.PACKAGE:
                for candidate in extraction.candidates:
                    if candidate.regimen_evidence.instructions:
                        validate_printed_review(draft, candidate.regimen_evidence.instructions)
        if task.printed_course_days and (
            not draft.course_start_date
            or not draft.course_end_date
            or (draft.course_end_date - draft.course_start_date).days + 1 != task.printed_course_days
        ):
            raise ValidationError("Review the explicitly printed course duration and start/end dates")
        if task.possible_duplicate_ids and not distinct_product_confirmed:
            raise ValidationError("Choose an existing product or confirm a genuinely different product")
        if draft.medication_name.casefold() != task.product.name.casefold():
            raise ValidationError("Product name conflict")
        if task.draft_regimen_id:
            return task
        active = self._enrollment.find_active_regimen(patient_id, task.medication_id)
        if active is not None:
            raise RegimenOverlapError()
        for source_id in task.source_ids:
            source = self._sources.get(patient_id, source_id)
            if source and source.review_status == SourceReviewStatus.EXTRACTED:
                self._enrollment.review_source_fields(patient_id=patient_id, source_id=source_id)
        result = self._enrollment.enroll_draft(
            patient_id=patient_id, draft=draft, existing_medication_id=task.medication_id, evidence_task_id=task.id
        )
        if result.missing_instructions:
            raise ValidationError("Complete the missing dose and schedule instructions")
        aggregate = self._sources.get(patient_id, result.regimen.source_id)
        if aggregate and aggregate.review_status == SourceReviewStatus.EXTRACTED:
            self._enrollment.review_source_fields(patient_id=patient_id, source_id=result.regimen.source_id)
        self._repo.add(
            "sources",
            SourceLink(
                id=uuid5(task.medication_id, str(result.regimen.source_id)),
                patient_id=patient_id,
                medication_id=task.medication_id,
                source_id=result.regimen.source_id,
                recorded_at=self._clock.now(),
            ),
        )
        updated = task.model_copy(
            update={
                "product": task.product.model_copy(
                    update={
                        "verification": "patient_reviewed",
                        "category": product_category,
                        "category_basis": "unknown" if product_category == "unknown" else "patient_entered",
                    }
                ),
                "status": "draft_created",
                "draft_regimen_id": result.regimen.id,
                "version": task.version + 1,
                "updated_at": self._clock.now(),
                "missing": [],
            }
        )
        self._repo.update_task(updated, task.version)
        return updated

    def summary(self, task: EnrollmentTask, language: str) -> str:
        if task.conflicts:
            return (
                "来源中的药物规格或剂型存在冲突，请核对并补充清晰标签。原有用药计划保持不变。"
                if language == "zh"
                else (
                    "These sources conflict in product information. Please check the "
                    "strength/form and provide a clearer label. Your existing plan is unchanged."
                )
            )
        if task.possible_duplicate_ids:
            return (
                "已有同名药物，请选择已有药物或确认这是不同规格的产品。"
                if language == "zh"
                else (
                    "You already have a medication with this name. Choose the existing product "
                    "or confirm this is a different product."
                )
            )
        if task.missing:
            if task.suggested_regimen and task.suggested_regimen.dose_amount and task.suggested_regimen.dose_unit:
                return (
                    f"已保存 {task.product.name} 的标签用量证据。请对照原始服用指示核对具体时间，"
                    "并补充缺失的疗程起止日期；我不会从每天几次或标签日期猜测这些信息。"
                    if language == "zh"
                    else f"I saved the printed dose evidence for {task.product.name}. "
                    "Please review the actual clock times and any missing course start/end dates "
                    "against your instructions. "
                    "I will not invent times from a daily count or course dates from a label date."
                )
            return (
                f"已保存 {task.product.name} 的药物资料。还缺少服用说明，"
                "请补充药房标签或处方资料，并核对每次用量和时间。"
                if language == "zh"
                else f"I saved product evidence for {task.product.name}. "
                "Dose or schedule instructions are still missing. "
                "Please add a pharmacy label or review your prescription instructions."
            )
        return (
            "两份来源已关联，请核对药物资料与服用说明，然后确认用药计划。"
            if language == "zh"
            else (
                "Your sources are linked. Please review the product and dose instructions before confirming activation."
            )
        )
