"""Identity-grouped private images and calibrated provider evidence, separate from intake."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from ..contracts.enums import IdentityStatus, RegimenState
from ..contracts.medication_evidence import (
    EvidenceRepository,
    ImageEmbedding,
    ImageKind,
    MedicationImage,
    PersonalVisionPort,
    PrivateImageStore,
    RecognitionRun,
    VisualReferenceSet,
)
from ..contracts.ports import Clock, IdGenerator
from ..contracts.vision import MatchOutcome
from ..domain.errors import NotFoundError, ProviderUnavailableError, ValidationError
from .enrollment import MedicationEnrollmentService


class PersonalGalleryService:
    def __init__(
        self,
        *,
        repository: EvidenceRepository,
        storage: PrivateImageStore,
        vision: PersonalVisionPort | None,
        enrollment: MedicationEnrollmentService,
        normalize: Callable[[bytes], bytes],
        clock: Clock,
        ids: IdGenerator,
    ):
        self._repo, self._storage, self._vision, self._enrollment = repository, storage, vision, enrollment
        self._normalize, self._clock, self._ids = normalize, clock, ids

    def list(self, patient_id: UUID) -> list[dict]:
        images = self._repo.list(patient_id, "images")
        tasks = self._repo.list(patient_id, "tasks")
        embedded_ids = {row.image_id for row in self._repo.list(patient_id, "embeddings")}
        result = []
        today = self._clock.now().astimezone(ZoneInfo("Asia/Singapore")).date()
        medications = self._repo.medications(patient_id)
        for medication in medications:
            regimens = self._enrollment.list_regimens(patient_id, medication.id)
            current = [
                row
                for row in regimens
                if row.state == RegimenState.ACTIVE
                and (not row.course_start_date or row.course_start_date <= today)
                and (not row.course_end_date or row.course_end_date >= today)
            ]
            photos = [row for row in images if isinstance(row, MedicationImage) and row.medication_id == medication.id]
            owned_tasks = [row for row in tasks if row.medication_id == medication.id]
            task = max(owned_tasks, key=lambda row: row.updated_at) if owned_tasks else None
            future = any(
                row.state == RegimenState.ACTIVE and row.course_start_date and row.course_start_date > today
                for row in regimens
            )
            result.append(
                {
                    "medication": medication,
                    "similar_name_records": sum(
                        other.id != medication.id
                        and other.display_name.casefold().strip() == medication.display_name.casefold().strip()
                        for other in medications
                    ),
                    "product": task.product if task else None,
                    "evidence_task_id": task.id if task else None,
                    "status": "current"
                    if current
                    else "upcoming"
                    if future
                    else "historical"
                    if any(
                        row.state in {RegimenState.ACTIVE, RegimenState.ENDED, RegimenState.SUPERSEDED}
                        for row in regimens
                    )
                    else "pending",
                    "regimens": regimens,
                    "images": photos,
                    "eligible_count": sum(row.eligibility == "eligible" and row.id in embedded_ids for row in photos),
                }
            )
        return result

    def image(self, patient_id: UUID, image_id: UUID) -> bytes:
        record = self._repo.get(patient_id, "images", image_id)
        if not isinstance(record, MedicationImage):
            raise NotFoundError("Reference photo not found")
        return self._storage.get(record.storage_path)

    def retire(self, patient_id: UUID, image_id: UUID) -> MedicationImage:
        owned = self._repo.get(patient_id, "images", image_id)
        if not isinstance(owned, MedicationImage):
            raise NotFoundError("Reference photo not found")
        return self._repo.retire_image(patient_id, image_id)

    def upload(
        self,
        *,
        patient_id: UUID,
        medication_id: UUID,
        image: bytes,
        image_kind: ImageKind,
        source_description: str,
        reviewed: bool,
        for_comparison: bool,
        consent: bool,
        demo_only: bool,
    ) -> MedicationImage:
        if not consent:
            raise ValidationError("Agree to photo processing before continuing")
        medication = self._enrollment.get_medication(patient_id, medication_id)
        if medication is None:
            raise NotFoundError("Owned medication not found")
        if not source_description.strip():
            raise ValidationError("Describe where this reference came from")
        clean = self._normalize(image)
        digest = hashlib.sha256(clean).hexdigest()
        image_id = uuid5(medication_id, digest + image_kind)
        old = self._repo.get(patient_id, "images", image_id)
        if isinstance(old, MedicationImage):
            return old
        embedded = None
        reason = "reference_photo_associated_only"
        eligible = False
        if image_kind == "loose_pill" and for_comparison:
            if not reviewed or medication.identity_status == IdentityStatus.UNVERIFIED:
                reason = "review_product_and_photo_association_first"
            elif self._vision is None:
                reason = "personal_embedding_unavailable"
            else:
                try:
                    model, embedded = self._vision.encode(clean)
                    eligible = model.normalized and embedded.normalized and model.dimension == embedded.dimension == 256
                    reason = "patient_reviewed_visual_reference_only" if eligible else "unsupported_embedding_metadata"
                except ProviderUnavailableError:
                    reason = "personal_embedding_unavailable"
        elif image_kind in {"package", "blister", "source"}:
            reason = "automatic_loose_pill_matching_not_available_for_this_image_type"
        path = f"{patient_id}/{medication_id}/{digest}.png"
        self._storage.put(path, clean)
        row = MedicationImage(
            id=image_id,
            patient_id=patient_id,
            medication_id=medication_id,
            image_kind=image_kind,
            storage_path=path,
            checksum=digest,
            source_description=source_description,
            reviewed=reviewed,
            eligibility="eligible" if eligible else "associated",
            eligibility_reason=reason,
            created_at=self._clock.now(),
        )
        if embedded and eligible:
            set_id = uuid5(medication_id, model.model_version + model.embedding_space_id + model.preprocessing_version)
            reference = VisualReferenceSet(
                id=set_id, patient_id=patient_id, medication_id=medication_id, model=model, created_at=self._clock.now()
            )
            embedding = ImageEmbedding(
                id=image_id,
                patient_id=patient_id,
                medication_id=medication_id,
                image_id=image_id,
                reference_set_id=set_id,
                result=embedded,
            )
            self._repo.add_reference(row, reference, embedding)
        else:
            self._repo.add("images", row)
        return row

    def check(
        self, *, patient_id: UUID, regimen_id: UUID | None, image: bytes, consent: bool, demo_only: bool
    ) -> RecognitionRun:
        if not consent:
            raise ValidationError("Agree to photo processing before continuing")
        selected = self._enrollment.get_regimen(patient_id, regimen_id) if regimen_id else None
        if regimen_id and selected is None:
            raise NotFoundError("Owned regimen not found")
        if self._vision is None:
            raise ProviderUnavailableError("Personal matching unavailable")
        photos = {row.id: row for row in self._repo.list(patient_id, "images") if isinstance(row, MedicationImage)}
        refs = [
            row
            for row in self._repo.list(patient_id, "embeddings")
            if isinstance(row, ImageEmbedding)
            and row.image_id in photos
            and photos[row.image_id].eligibility == "eligible"
            and photos[row.image_id].reviewed
        ]
        outcome: MatchOutcome | None = None
        decision, reason = (
            "missing_reference",
            "No eligible personal pill photos are available. Add a reference photo to your medication.",
        )
        used = []
        if refs:
            try:
                _model, query = self._vision.encode(self._normalize(image))
                compatible = [
                    row
                    for row in refs
                    if (
                        row.result.model_version,
                        row.result.embedding_space_id,
                        row.result.preprocessing_version,
                        row.result.dimension,
                        row.result.normalized,
                    )
                    == (
                        query.model_version,
                        query.embedding_space_id,
                        query.preprocessing_version,
                        query.dimension,
                        query.normalized,
                    )
                ]
                if len(compatible) > 50:
                    raise ValidationError("Select a smaller personal reference set")
                if compatible:
                    names = {str(row.id): row.display_name for row in self._repo.medications(patient_id)}
                    outcome = self._vision.compare(query, compatible, names)
                    used = [row.image_id for row in compatible]
                    decision = outcome.decision
                    reason = "Visual evidence only. Review the current recorded medication plan separately."
                    if outcome.medication_id:
                        matched = UUID(outcome.medication_id)
                        today = self._clock.now().astimezone(ZoneInfo("Asia/Singapore")).date()
                        current = self._enrollment.find_active_regimen(patient_id, matched)
                        if (
                            not current
                            or (current.course_end_date and current.course_end_date < today)
                            or (current.course_start_date and current.course_start_date > today)
                        ):
                            decision, reason = (
                                "conflict",
                                (
                                    "The similar reference belongs to a historical or inactive plan. Check your "
                                    "current instructions with a pharmacist."
                                ),
                            )
                        elif any(
                            row.medication_id == matched and row.conflicts
                            for row in self._repo.list(patient_id, "tasks")
                        ):
                            decision, reason = (
                                "conflict",
                                "Your product sources have unresolved differences. Verify the strength and form first.",
                            )
                        elif selected and (selected.patient_medication_id != matched or selected.id != current.id):
                            decision, reason = (
                                "conflict",
                                (
                                    "The photo evidence differs from your selected current medication. Please "
                                    "verify your original label."
                                ),
                            )
                else:
                    reason = (
                        "Your stored references use a different model or image processing version. "
                        "Add compatible references."
                    )
            except ProviderUnavailableError:
                decision, reason = (
                    "unavailable",
                    "Personal visual comparison is temporarily unavailable. Review your recorded instructions.",
                )
        run = RecognitionRun(
            id=self._ids.new_id(),
            patient_id=patient_id,
            task="check_dose",
            selected_regimen_id=regimen_id,
            reference_ids=used,
            outcome=outcome,
            decision=decision,
            reason=reason,
            created_at=self._clock.now(),
        )
        self._repo.add("runs", run)
        return run
