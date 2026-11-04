"""Progressive source reconciliation; OCR supplies evidence, patients review plans."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid5

from ..contracts.assistant_workflows import WorkflowContext
from ..contracts.dose_display import DoseBasis
from ..contracts.dto import FrequencyRuleDTO, PatientMedicationDTO, RegimenDraftInput, SourceDocumentDTO, SourceFieldDTO
from ..contracts.enrollment_operations import PreparedEnrollment
from ..contracts.enrollment_workflow import EnrollmentFields
from ..contracts.enums import FieldName, SourceKind, SourceReviewStatus
from ..contracts.medication_evidence import (
    EnrollmentTask,
    EvidenceEnrollmentWritePort,
    EvidenceRepository,
    EvidenceSourcePublication,
    EvidenceSourceSnapshot,
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
from ..contracts.source_extraction import ListedMedication, MedicationSourceExtractionDTO
from ..contracts.workflow_attachments import WorkflowEnrollmentSource
from ..domain.errors import (
    NotFoundError,
    ProviderUnavailableError,
    RegimenOverlapError,
    StaleVersionError,
    ValidationError,
)
from .enrollment import MedicationEnrollmentService
from .printed_instructions import apply_printed_parts, validate_printed_review
from .source_preview import SourcePreviewService


def evidence_name(name: str, strength: str | None) -> str:
    """Text-only alias comparison; strength/form remain independently reconciled."""
    if strength:
        suffix = r"\s*".join(re.escape(char) for char in re.sub(r"\s+", "", strength))
        name = re.sub(r"\s*" + suffix + r"\s*$", "", name, flags=re.I)
    return " ".join(name.casefold().split())


def strength_key(value: str) -> str:
    """Compare cosmetic spelling only. Never convert units or infer ingredients."""
    key = re.sub(r"\s+", "", unicodedata.normalize("NFKC", value).casefold())
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([a-zμ/]+)", key)
    if match:
        number = format(Decimal(match[1]), "f")
        return (number.rstrip("0").rstrip(".") if "." in number else number) + match[2]
    return key


def distinct_strength(left: str | None, right: str | None) -> bool:
    """Positive values in the same supported recorded unit; no unit conversion."""
    unit = r"mg|g|mcg|ug|μg|iu|mg/ml|mcg/ml|units/ml"
    first = re.fullmatch(
        rf"(\d+(?:\.\d+)?)({unit})",
        strength_key(left or ""),
    )
    second = re.fullmatch(rf"(\d+(?:\.\d+)?)({unit})", strength_key(right or ""))
    return bool(
        first
        and second
        and first[2] == second[2]
        and Decimal(first[1]) > 0
        and Decimal(second[1]) > 0
        and Decimal(first[1]) != Decimal(second[1])
    )


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
    @staticmethod
    def workflow_fields(
        extraction: MedicationSourceExtractionDTO, candidate_index: int | None = None
    ) -> EnrollmentFields:
        """Pure, unreviewed proposals using the existing printed-instruction rules."""
        index = 0 if len(extraction.candidates) == 1 and candidate_index is None else candidate_index
        if extraction.label_kind == "none" or index is None or not 0 <= index < len(extraction.candidates):
            raise ValidationError("Choose one clearly named product from the original photo")
        candidate = extraction.candidates[index]
        patient_instructions = extraction.source_kind in {
            "pharmacy_label",
            "prescription",
        } and extraction.label_kind not in {"package", "none"}
        parts = candidate.regimen_evidence.instructions if patient_instructions else None
        directions = candidate.regimen_evidence.directions if patient_instructions else None
        draft = printed_regimen(candidate.product.name[:160], directions.value if directions else None)
        if parts:
            draft = apply_printed_parts(draft, parts)
        count = parts.times_per_day if parts and not parts.as_needed and parts.every_hours is None else None
        if count and draft.frequency_rule is None:
            draft = draft.model_copy(update={"frequency_rule": FrequencyRuleDTO(kind="daily", local_times=[])})
        text = " ".join(
            [
                directions.value if directions else "",
                parts.text if parts else "",
                f"for {parts.duration}" if parts and parts.duration else "",
            ]
        )
        days = re.search(r"\bfor\s+(\d{1,3})\s+days?\b", text, re.I)
        day_count = int(days[1]) if days and 1 <= int(days[1]) <= 365 else None
        form = candidate.product.dose_form.value.strip().casefold() if candidate.product.dose_form else "unknown"
        return EnrollmentFields(
            **draft.model_dump(exclude={"patient_edited", "supersedes_regimen_id"}),
            method="photo",
            source_candidate_index=index,
            times_per_day=count,
            printed_course_days=day_count,
            dose_basis=DoseBasis(
                strength_text=(candidate.product.strength or "")[:100],
                form=form if form in {"tablet", "capsule", "liquid", "other"} else "unknown",
                formulation={"ER": "modified_release", "DR": "enteric"}.get(candidate.product.release, "unknown"),
                single_ingredient=len(candidate.product.ingredients) == 1 if candidate.product.ingredients else None,
                instructions_text=(parts.text if parts else directions.value if directions else "")[:1000],
            ),
        )

    @staticmethod
    def validate_workflow_fields(extraction: MedicationSourceExtractionDTO, fields: EnrollmentFields) -> None:
        proposal = EvidenceEnrollmentService.workflow_fields(extraction, fields.source_candidate_index)
        if evidence_name(fields.medication_name or "", None) != evidence_name(proposal.medication_name, None):
            raise ValidationError("The product name differs from the selected photo; reconcile the original source")
        if proposal.dose_basis.strength_text and (
            not fields.dose_basis
            or re.sub(r"\s+", "", fields.dose_basis.strength_text.casefold())
            != re.sub(r"\s+", "", proposal.dose_basis.strength_text.casefold())
        ):
            raise ValidationError("The product strength differs from the selected original")
        candidate = extraction.candidates[proposal.source_candidate_index]
        if extraction.source_kind in {"pharmacy_label", "prescription"} and extraction.label_kind not in {
            "package",
            "none",
        }:
            parts = candidate.regimen_evidence.instructions
            if parts:
                validate_printed_review(fields.draft, parts)
            elif proposal.dose_amount is not None and (
                fields.dose_amount != proposal.dose_amount or fields.dose_unit != proposal.dose_unit
            ):
                raise ValidationError("The dose differs from the printed instructions")
            if proposal.printed_course_days and (
                not fields.course_start_date
                or not fields.course_end_date
                or (fields.course_end_date - fields.course_start_date).days + 1 != proposal.printed_course_days
            ):
                raise ValidationError("Review the explicitly printed course length and start/end dates")

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
        source_writer: EvidenceEnrollmentWritePort | None = None,
    ):
        self._repo, self._medications, self._sources, self._fields = repository, medications, sources, fields
        self._enrollment, self._preview, self._storage = enrollment, preview, storage
        self._normalize, self._clock, self._ids = normalize, clock, ids
        self._source_writer = source_writer

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
        prepared = self.prepare_attachment(
            patient_id=patient_id,
            task_id=task_id,
            image=image,
            source_kind=source_kind,
            medication_id=medication_id,
            consent=consent,
            demo_only=demo_only,
            automatically_routed=automatically_routed,
        )
        if isinstance(prepared, EnrollmentTask):
            return prepared
        return self.publish_attachment(patient_id, prepared)

    def prepare_attachment(
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
    ) -> EvidenceSourcePublication | EnrollmentTask:
        if self._source_writer and self._source_writer.workflow_owner(patient_id, task_id) is not None:
            raise StaleVersionError("Continue the original saved source task to add another image")
        return self._prepare_attachment(
            patient_id=patient_id,
            task_id=task_id,
            image=image,
            source_kind=source_kind,
            medication_id=medication_id,
            consent=consent,
            demo_only=demo_only,
            automatically_routed=automatically_routed,
        )

    def prepare_verified_attachment(
        self,
        *,
        context: WorkflowContext,
        source: WorkflowEnrollmentSource,
        original: bytes,
        task_id: UUID,
        medication_id: UUID | None = None,
    ) -> EvidenceSourcePublication | EnrollmentTask:
        if self._source_writer is None:
            raise ProviderUnavailableError("Atomic source publication is unavailable")
        return self.prepare_source_proposal(context=context,source=source,original=original,
            task_id=task_id,medication_id=medication_id)

    def prepare_source_proposal(
        self, *, context: WorkflowContext, source: WorkflowEnrollmentSource, original: bytes,
        task_id: UUID, medication_id: UUID | None = None, allocation_key: UUID | None = None,
    ) -> EvidenceSourcePublication | EnrollmentTask:
        """Pure native validation/projection; publication still requires its own owned transaction."""
        if (
            context.capability_id != "medication.source.add"
            or context.save_mode != "allowed"
            or source.owner != context.owner
            or source.task_id != context.task_id
            or hashlib.sha256(original).hexdigest() != source.original_checksum
            or source.extraction.source_kind != source.source_kind
        ):
            raise ValidationError("The original source does not belong to this saved task")
        prepared = self._prepare_attachment(
            patient_id=context.owner,
            task_id=task_id,
            image=original,
            source_kind=source.source_kind,
            medication_id=medication_id,
            consent=True,
            demo_only=True,
            extracted=source.extraction,
            workflow_task_id=context.task_id,
            allocation_key=allocation_key,
        )
        return (
            replace(
                prepared,
                workflow_task_id=context.task_id,
                attachment_id=source.attachment_id,
                original_checksum=source.original_checksum,
            )
            if isinstance(prepared, EvidenceSourcePublication)
            else prepared
        )

    def duplicate_source_snapshot(
        self,patient_id: UUID,task_id: UUID,original: bytes,source_kind: str
    ) -> EvidenceSourceSnapshot:
        """Read actual owned duplicate facts; do not reinterpret the new extraction as an update."""
        task=self.get(patient_id,task_id)
        clean=self._normalize(original)
        digest=hashlib.sha256(clean).hexdigest()
        image=next((row for row in self._repo.list(patient_id,'images') if isinstance(row,MedicationImage)
            and row.medication_id==task.medication_id and row.checksum==digest
            and row.source_id in task.source_ids),None)
        if image is None or image.deleted_at is not None:
            raise StaleVersionError('The existing source image is unavailable')
        source=self._sources.get(patient_id,image.source_id)
        medication=self._medications.get(patient_id,task.medication_id)
        link=next((row for row in self._repo.list(patient_id,'sources') if isinstance(row,SourceLink)
            and row.source_id==image.source_id and row.medication_id==task.medication_id),None)
        if source is None or source.source_kind.value!=source_kind or medication is None or link is None:
            raise StaleVersionError('The owned duplicate source registration changed')
        return EvidenceSourceSnapshot(source=source,fields=tuple(self._fields.list_for_source(patient_id,source.id)),
            medication=medication,task=task,image=image,link=link,derived_byte_size=len(clean))

    def publish_verified_attachment(
        self,
        owner: UUID,
        prepared: EvidenceSourcePublication,
        source: WorkflowEnrollmentSource,
        original: bytes,
        action_key: UUID,
    ) -> EnrollmentTask:
        if self._source_writer is None:
            raise ProviderUnavailableError("Atomic source publication is unavailable")
        if (
            source.owner != owner
            or hashlib.sha256(original).hexdigest() != source.original_checksum
            or prepared.source.extraction_evidence != source.extraction
            or prepared.source.source_kind.value != source.source_kind
            or prepared.derived_image != self._normalize(original)
            or prepared.workflow_task_id != source.task_id
            or prepared.attachment_id != source.attachment_id
            or prepared.original_checksum != source.original_checksum
        ):
            raise ValidationError("The prepared evidence differs from its current saved original")
        return self.publish_attachment(owner, prepared, action_key=action_key)

    def bind_duplicate_original(
        self,
        owner: UUID,
        task: EnrollmentTask,
        source: WorkflowEnrollmentSource,
        original: bytes,
        action_key: UUID,
    ) -> EnrollmentTask:
        if self._source_writer is None:
            raise ProviderUnavailableError("Atomic source publication is unavailable")
        if source.owner != owner or hashlib.sha256(original).hexdigest() != source.original_checksum:
            raise ValidationError("The duplicate source differs from its saved original")
        return self._source_writer.bind_existing_original(
            owner,
            action_key,
            task,
            source,
            hashlib.sha256(self._normalize(original)).hexdigest(),
        )

    def saved_original_receipt(self, owner: UUID, action_key: UUID, workflow_task_id: UUID, attachment_id: UUID):
        if self._source_writer is None:
            raise ProviderUnavailableError("Atomic source publication is unavailable")
        return self._source_writer.lookup_original(owner, action_key, workflow_task_id, attachment_id)

    def workflow_owner(self, owner: UUID, task_id: UUID) -> UUID | None:
        return self._source_writer.workflow_owner(owner, task_id) if self._source_writer else None

    def _prepare_attachment(
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
        extracted: MedicationSourceExtractionDTO | None = None,
        workflow_task_id: UUID | None = None,
        allocation_key: UUID | None = None,
    ) -> EvidenceSourcePublication | EnrollmentTask:
        if not consent:
            raise ValidationError("Agree to private storage and image processing before saving")
        if source_kind not in {"package", "pharmacy_label", "prescription"}:
            raise ValidationError("PDF extraction is not available; upload a label image or enter instructions")
        clinical_revision = self._source_writer.revision(patient_id) if self._source_writer else None
        existing = self._repo.get(patient_id, "tasks", task_id)
        task = existing if isinstance(existing, EnrollmentTask) else None
        prior_task = task
        if task and medication_id and medication_id != task.medication_id:
            raise ValidationError("Supplement must belong to the same selected medication")
        selected = task.medication_id if task else medication_id
        medication = self._medications.get(patient_id, selected) if selected else None
        if selected and medication is None:
            raise NotFoundError("Owned medication not found")
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
                    original = self._sources.get(patient_id, row.source_id) if row.source_id else None
                    if original is None or (not automatically_routed and original.source_kind.value != source_kind):
                        raise ValidationError(
                            "This saved photo has a different source type; check the original registration"
                        )
                    return task
        authority = self.workflow_owner(patient_id, task_id)
        if authority is not None and authority != workflow_task_id:
            raise StaleVersionError("Continue the original saved source task to add new evidence")
        if self._preview is None and extracted is None:
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
        extraction = extracted or self._preview.preview(
            content=clean, source_kind=source_kind, consent=True, demo_only=demo_only, medications=listed
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
        extraction = extraction.model_copy(update={"source_kind": source_kind})
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
        source = SourceDocumentDTO(
            id=source_id,
            patient_id=patient_id,
            source_kind=SourceKind(source_kind),
            review_status=SourceReviewStatus.EXTRACTED,
            reviewed_at=None,
            extraction_evidence=extraction,
        )
        field_rows = []
        for field, value in [
            (FieldName.MEDICATION_NAME, product.name),
            (FieldName.STRENGTH, product.strength),
            (FieldName.FORM, product.dose_form),
        ]:
            if value is not None:
                field_rows.append(
                    SourceFieldDTO(
                        id=uuid5(allocation_key,'field:'+field.value) if allocation_key else self._ids.new_id(),
                        patient_id=patient_id,
                        source_id=source_id,
                        field_name=field,
                        field_value=value,
                        review_status=SourceReviewStatus.EXTRACTED,
                        reviewed_at=None,
                    )
                )
        if task is None:
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
                    id=uuid5(allocation_key,'medication') if allocation_key else self._ids.new_id(),
                    patient_id=patient_id, display_name=product.name, source_id=source_id
                )
            else:
                duplicates = []
            prior = next((row for row in existing_tasks if row.medication_id == medication.id), None)
            identity_source = (
                self._enrollment.get_source(patient_id, medication.source_id) if medication.source_id else None
            )
            basis = identity_source.dose_basis if identity_source else None
            base_product = (
                prior.product
                if prior
                else ProductEvidence(
                    name=medication.display_name,
                    strength=basis.strength_text or None if basis else None,
                    dose_form=basis.form if basis and basis.form != "unknown" else None,
                )
            )
            task = EnrollmentTask(
                id=task_id,
                patient_id=patient_id,
                medication_id=medication.id,
                product=base_product if medication_id else product,
                possible_duplicate_ids=duplicates,
                updated_at=self._clock.now(),
            )
        conflicts = list(task.conflicts)
        values = task.product.model_dump()
        for field in ("name", "strength", "dose_form", "formulation", "brand"):
            old, new = getattr(task.product, field), getattr(product, field)
            differs = (
                product_name(task.product) != product_name(product)
                if field == "name" and old and new
                else strength_key(old) != strength_key(new)
                if field == "strength" and old and new
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
            for prior in self.sources(patient_id, task.id) if prior_task else ():
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
        link = SourceLink(
            id=uuid5(task.medication_id, str(source_id)),
            patient_id=patient_id,
            medication_id=task.medication_id,
            source_id=source_id,
            recorded_at=self._clock.now(),
        )
        return EvidenceSourcePublication(
            source=source,
            fields=tuple(field_rows),
            medication=medication,
            create_medication=selected is None,
            prior_task=prior_task,
            task=EnrollmentTask.model_validate(updated.model_dump()),
            image=image_row,
            link=link,
            derived_image=clean,
            expected_clinical_revision=clinical_revision,
        )

    def publish_attachment(
        self,
        patient_id: UUID,
        prepared: EvidenceSourcePublication,
        *,
        action_key: UUID | None = None,
    ) -> EnrollmentTask:
        if prepared.task.patient_id != patient_id:
            raise ValidationError("Prepared source belongs to another patient")
        if self._source_writer:
            return self._source_writer.publish_once(
                patient_id,
                action_key or uuid5(prepared.task.id, f"source:{prepared.image.checksum}"),
                prepared,
            )
        # Original persistence adapter compatibility. Assistant does not compose
        # this path without an independently verified atomic write port.
        self._sources.add(prepared.source)
        for row in prepared.fields:
            self._fields.add(row)
        if prepared.create_medication:
            self._medications.add(prepared.medication)
        if prepared.prior_task is None:
            self._repo.add("tasks", prepared.task.model_copy(update={"version": prepared.task.version - 1}))
        self._storage.put(prepared.image.storage_path, prepared.derived_image)
        self._repo.add("images", prepared.image)
        self._repo.add("sources", prepared.link)
        self._repo.update_task(prepared.task, prepared.task.version - 1)
        return prepared.task

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
        on_prepared: Callable[[EnrollmentTask], None] | None = None,
        workflow_task_id: UUID | None = None,
        expected_version: int | None = None,
    ) -> EnrollmentTask:
        if on_prepared is not None and self._source_writer is None:
            raise ProviderUnavailableError("Atomic Assistant source review is unavailable")
        revision = self._source_writer.revision(patient_id) if self._source_writer else None
        task = self.get(patient_id, task_id)
        if expected_version is not None and task.version != expected_version:
            raise StaleVersionError("The source registration changed; reopen its current review")

        def review():
            authority = self._source_writer.workflow_owner(patient_id, task_id) if self._source_writer else None
            if authority is not None and (authority != workflow_task_id or on_prepared is None):
                raise StaleVersionError("Continue the original saved source review")
            result = self._review_confirmed(
                patient_id=patient_id,
                task_id=task_id,
                draft=draft,
                distinct_product_confirmed=distinct_product_confirmed,
                patient_reviewed=patient_reviewed,
                product_category=product_category,
                replace_active_plan=replace_active_plan,
            )
            if on_prepared is not None:
                on_prepared(result)
            return result

        if self._source_writer is None or task.draft_regimen_id is not None:
            return review()
        return self._source_writer.review_unactivated(patient_id, task_id, task.version, revision, review)

    def prepare_review_proposal(
        self,
        *,
        patient_id: UUID,
        task_id: UUID,
        draft: RegimenDraftInput,
        distinct_product_confirmed: bool,
        patient_reviewed: bool,
        product_category: str = "unknown",
        replace_active_plan: bool = False,
    ) -> PreparedEnrollment | EnrollmentTask:
        """Run existing native review policy and allocate DTOs without publishing rows."""
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
        if task.possible_duplicate_ids:
            # Reviewed product attributes, not a UI checkbox, can distinguish
            # products. Missing metadata is never evidence of a difference.
            known = {row.medication_id: row.product for row in self.list(patient_id)}
            for medication_id in task.possible_duplicate_ids:
                other = known.get(medication_id)
                if other is None or not (
                    distinct_strength(task.product.strength, other.strength)
                    or any(
                        left and right and str(left).strip().casefold() != str(right).strip().casefold()
                        for left, right in (
                            (task.product.dose_form, other.dose_form),
                            (task.product.formulation, other.formulation),
                        )
                    )
                ):
                    raise ValidationError(
                        "A similar medicine is already saved. "
                        "Choose the existing product or add clearer product evidence."
                    )
        if draft.medication_name.casefold() != task.product.name.casefold():
            raise ValidationError("Product name conflict")
        if task.draft_regimen_id:
            current = self._enrollment.get_regimen(patient_id, task.draft_regimen_id)
            normalized = self._enrollment.preview_draft(patient_id, draft)
            comparable = (
                "dose_amount",
                "dose_unit",
                "is_prn",
                "route",
                "food_instruction",
                "course_start_date",
                "course_end_date",
            )
            expected_rule = normalized.frequency_rule.model_dump(mode="json") if normalized.frequency_rule else None
            actual_rule = (
                FrequencyRuleDTO.model_validate(current.frequency_rule).model_dump(mode="json")
                if current and current.frequency_rule
                else None
            )
            if (
                current is None
                or current.patient_medication_id != task.medication_id
                or any(getattr(current, field) != getattr(normalized, field) for field in comparable)
                or actual_rule != expected_rule
                or current.supersedes_id != normalized.supersedes_regimen_id
                or (normalized.patient_edited and not current.patient_edited)
                or task.product.category != product_category
            ):
                raise ValidationError(
                    "This source review is already saved with different details; review a new plan version"
                )
            return task
        active = self._enrollment.find_active_regimen(patient_id, task.medication_id)
        if active is not None:
            raise RegimenOverlapError()
        proposed = self._enrollment.prepare_draft(
            patient_id=patient_id,
            draft=draft,
            existing_medication_id=task.medication_id,
            evidence_task_id=task.id,
        )
        if proposed.result.missing_instructions:
            raise ValidationError("Complete the missing dose and schedule instructions")
        return proposed

    def _review_confirmed(
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
        proposed = self.prepare_review_proposal(
            patient_id=patient_id, task_id=task_id, draft=draft,
            distinct_product_confirmed=distinct_product_confirmed, patient_reviewed=patient_reviewed,
            product_category=product_category, replace_active_plan=replace_active_plan,
        )
        if isinstance(proposed, EnrollmentTask):
            return proposed
        task = self.get(patient_id, task_id)
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
        if (
            task.suggested_regimen
            and task.suggested_regimen.frequency_rule
            and task.suggested_regimen.frequency_rule.kind == "interval"
        ):
            return (
                "首次服药日期和时间是什么？请在计划核对表中填写；时间留空时默认使用 08:00，并会标明默认值。"
                "核对确认前不会激活计划。"
                if language == "zh"
                else "What are the first-dose date and time? Enter them in the plan review form. "
                "A blank time defaults to 08:00 and is labelled as a default. "
                "The plan is not activated until you review and confirm."
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
