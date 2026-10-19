"""Identity-grouped private images and calibrated provider evidence, separate from intake."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from uuid import UUID, uuid5

from ..contracts.enums import RegimenState
from ..contracts.medication_evidence import (
    EvidenceRepository,
    GalleryUploadResult,
    ImageEmbedding,
    ImageKind,
    MedicationImage,
    PersonalVisionPort,
    PrivateImageStore,
    RecognitionRun,
)
from ..contracts.ports import Clock, IdGenerator
from ..contracts.vision import MatchOutcome
from ..domain.errors import NotFoundError, ProviderUnavailableError, ValidationError
from .enrollment import MedicationEnrollmentService
from .timezone import FixedTzProvider, LocalTzProvider

ACTIVE_REFERENCE_REASON: str | None = None
UNVERIFIED_CONTENT_REASON = "image_content_not_independently_validated_comparison_disabled"


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
        tz_provider: LocalTzProvider | None = None,
    ):
        self._repo, self._storage, self._vision, self._enrollment = repository, storage, vision, enrollment
        self._normalize, self._clock, self._ids = normalize, clock, ids
        self._timezone = tz_provider or FixedTzProvider()

    def list(self, patient_id: UUID) -> list[dict]:
        images = self._repo.list(patient_id, "images")
        tasks = self._repo.list(patient_id, "tasks")
        source_links = self._repo.list(patient_id, "sources")
        embedded_ids = {row.image_id for row in self._repo.list(patient_id, "embeddings")}
        result = []
        today = self._clock.now().astimezone(self._timezone.local_tz(patient_id)).date()
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
            photos = [
                row
                for row in images
                if isinstance(row, MedicationImage)
                and row.medication_id == medication.id
                and row.deleted_at is None
                and not row.gallery_removed
            ]
            # No current service independently validates general image
            # content. Keep old photos, but project every historical active
            # reference out of comparison without changing stored evidence.
            photos = [
                row.model_copy(
                    update={
                        "eligibility": "associated",
                        "eligibility_reason": UNVERIFIED_CONTENT_REASON,
                    }
                )
                if row.eligibility == "eligible" and row.eligibility_reason != ACTIVE_REFERENCE_REASON
                else row
                for row in photos
            ]
            owned_tasks = [row for row in tasks if row.medication_id == medication.id]
            task = max(owned_tasks, key=lambda row: row.updated_at) if owned_tasks else None
            medication_sources = {
                source_id
                for source_id in [
                    medication.source_id,
                    *(row.source_id for row in regimens),
                    *(
                        row.source_id
                        for row in images
                        if isinstance(row, MedicationImage) and row.medication_id == medication.id
                    ),
                    *(row.source_id for row in source_links if getattr(row, "medication_id", None) == medication.id),
                    *(source_id for item in owned_tasks for source_id in item.source_ids),
                ]
                if source_id is not None
            }
            source_documents = [
                document
                for source_id in medication_sources
                if (document := self._enrollment.get_source(patient_id, source_id)) is not None
            ]
            updated_at = max(
                [row.created_at for row in photos]
                + [row.created_at for row in regimens]
                + [row.recorded_at for row in source_links if getattr(row, "medication_id", None) == medication.id]
                + [row.reviewed_at for row in source_documents if row.reviewed_at is not None]
                + ([task.updated_at] if task else []),
                default=None,
            )
            future = any(
                row.state == RegimenState.ACTIVE and row.course_start_date and row.course_start_date > today
                for row in regimens
            )
            result.append(
                {
                    "medication": medication,
                    "product_id": medication.product_id,
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
                    "file_count": len({row.storage_path for row in photos}),
                    "source_document_count": len(source_documents),
                    "updated_at": updated_at,
                    "eligible_count": sum(
                        row.eligibility == "eligible"
                        and row.eligibility_reason == ACTIVE_REFERENCE_REASON
                        and row.id in embedded_ids
                        for row in photos
                    ),
                }
            )
        return result

    def files(self, patient_id: UUID, medication_id: UUID) -> dict:
        """Aggregate only source and image records explicitly linked to this medication."""
        medication = self._enrollment.get_medication(patient_id, medication_id)
        if medication is None:
            raise NotFoundError("Medication not found")
        images = [
            row
            for row in self._repo.list(patient_id, "images")
            if isinstance(row, MedicationImage)
            and row.medication_id == medication_id
            and row.deleted_at is None
            and not row.gallery_removed
        ]
        # Match the gallery list's comparison projection. A persisted legacy
        # flag without current validated provenance is not an active reference.
        images = [
            row.model_copy(update={"eligibility": "associated", "eligibility_reason": UNVERIFIED_CONTENT_REASON})
            if row.eligibility == "eligible" and row.eligibility_reason != ACTIVE_REFERENCE_REASON
            else row
            for row in images
        ]
        regimens = self._enrollment.list_regimens(patient_id, medication_id)
        links = [
            row
            for row in self._repo.list(patient_id, "sources")
            if getattr(row, "medication_id", None) == medication_id
        ]
        tasks = [
            row for row in self._repo.list(patient_id, "tasks") if getattr(row, "medication_id", None) == medication_id
        ]
        source_ids = {
            source_id
            for source_id in [
                medication.source_id,
                *(row.source_id for row in regimens),
                *(row.source_id for row in links),
                *(row.source_id for row in images),
                *(source_id for task in tasks for source_id in task.source_ids),
            ]
            if source_id is not None
        }
        source_links = {row.source_id: row for row in links}
        source_regimens = {
            source_id: [str(row.id) for row in regimens if row.source_id == source_id] for source_id in source_ids
        }
        sources = []
        for source_id in sorted(source_ids, key=str):
            document = self._enrollment.get_source(patient_id, source_id)
            if document is None:
                continue
            source_images = [row for row in images if row.source_id == source_id]
            link = source_links.get(source_id)
            recorded_at = link.recorded_at if link else min((row.created_at for row in source_images), default=None)
            sources.append(
                {
                    "id": str(document.id),
                    "source_kind": str(document.source_kind),
                    "review_status": str(document.review_status),
                    "reviewed_at": document.reviewed_at.isoformat() if document.reviewed_at else None,
                    "extraction_evidence": document.extraction_evidence.model_dump(mode="json")
                    if document.extraction_evidence
                    else None,
                    "recorded_at": recorded_at.isoformat() if recorded_at else None,
                    "fields": [
                        {
                            "id": str(row.id),
                            "field_name": str(row.field_name),
                            "field_value": row.field_value,
                            "review_status": str(row.review_status),
                            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
                        }
                        for row in self._enrollment.list_source_fields(patient_id, source_id)
                    ],
                    "regimen_ids": source_regimens[source_id],
                    "image_ids": [str(row.id) for row in source_images],
                }
            )

        # Group exact same-storage-object records only. Similar content, names,
        # and checksums are not sufficient to merge distinct evidence records.
        grouped: dict[str, dict] = {}
        for row in images:
            item = grouped.setdefault(
                row.storage_path,
                {
                    "id": str(row.id),
                    "image_id": str(row.id),
                    "image_ids": [],
                    # Provenance belongs in details; it is not a trustworthy
                    # primary title for the underlying patient image.
                    "name": "Medication photo",
                    "format": "PNG",
                    "content_type": "image",
                    "photo_description": row.image_kind,
                    "purpose_tags": ["evidence"],
                    "created_at": row.created_at.isoformat(),
                    "eligibility": row.eligibility,
                    "eligibility_reason": row.eligibility_reason,
                    "source_ids": [],
                },
            )
            item["image_ids"].append(str(row.id))
            if row.created_at.isoformat() > item["created_at"]:
                item["created_at"] = row.created_at.isoformat()
            if row.eligibility == "eligible":
                item["eligibility"] = "eligible"
                item["eligibility_reason"] = row.eligibility_reason
            if row.source_id:
                item["source_ids"].append(str(row.source_id))
            if row.source_id and "enrollment_source" not in item["purpose_tags"]:
                item["purpose_tags"].append("enrollment_source")
            if row.eligibility == "eligible" and "appearance_reference" not in item["purpose_tags"]:
                item["purpose_tags"].append("appearance_reference")
        files = []
        for item in grouped.values():
            source_ids_for_file = item["source_ids"]
            item["sources"] = [source for source in sources if source["id"] in source_ids_for_file]
            # Keep purpose values semantic; source IDs are carried separately.
            item["purpose_tags"] = [
                value
                for value in item["purpose_tags"]
                if value in {"evidence", "enrollment_source", "appearance_reference"}
            ]
            files.append(item)
        records_without_file = [source for source in sources if not source["image_ids"]]
        return {
            "medication_id": str(medication_id),
            "files": files,
            "source_records": records_without_file,
            "regimens": [row.model_dump(mode="json") for row in regimens],
        }

    def image(self, patient_id: UUID, image_id: UUID) -> bytes:
        record = self._repo.get(patient_id, "images", image_id)
        if not isinstance(record, MedicationImage) or record.deleted_at is not None:
            raise NotFoundError("Reference photo not found")
        return self._storage.get(record.storage_path)

    def retire(self, patient_id: UUID, image_id: UUID) -> MedicationImage:
        owned = self._repo.get(patient_id, "images", image_id)
        if not isinstance(owned, MedicationImage):
            raise NotFoundError("Reference photo not found")
        return self._repo.retire_image(patient_id, image_id)

    def manage_image(
        self,
        patient_id: UUID,
        image_id: UUID,
        *,
        action: str,
        expected_version: int,
        image_kind: ImageKind | None = None,
        source_description: str | None = None,
        confirmed: bool = False,
    ) -> MedicationImage:
        """Apply an owner-scoped image lifecycle change and retryable cleanup."""
        owned = self._repo.get(patient_id, "images", image_id)
        if not isinstance(owned, MedicationImage):
            raise NotFoundError("Photo not found")
        if owned.deleted_at is not None:
            if action != "delete":
                raise NotFoundError("Photo not found")
            if not owned.cleanup_pending:
                return owned
            changed, path = owned, owned.storage_path
        else:
            changed, path = self._repo.manage_image(
                patient_id,
                image_id,
                action=action,
                expected_version=expected_version,
                occurred_at=self._clock.now(),
                image_kind=image_kind,
                source_description=source_description,
                confirmed=confirmed,
            )
        if action == "delete" and changed.cleanup_pending:
            self._storage.delete(path)
            self._repo.acknowledge_image_cleanup(patient_id, image_id)
            changed = changed.model_copy(update={"cleanup_pending": False})
        return changed

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
        return self.upload_with_status(
            patient_id=patient_id,
            medication_id=medication_id,
            image=image,
            image_kind=image_kind,
            source_description=source_description,
            reviewed=reviewed,
            for_comparison=for_comparison,
            consent=consent,
            demo_only=demo_only,
        ).photo

    def upload_with_status(
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
    ) -> GalleryUploadResult:
        if not consent:
            raise ValidationError("Agree to photo processing before continuing")
        medication = self._enrollment.get_medication(patient_id, medication_id)
        if medication is None:
            raise NotFoundError("Owned medication not found")
        if not source_description.strip():
            raise ValidationError("Describe where this reference came from")
        clean = self._normalize(image)
        digest = hashlib.sha256(clean).hexdigest()
        image_id = uuid5(medication_id, digest)
        old = self._repo.get(patient_id, "images", image_id)
        if old is None:
            # Recognize deterministic IDs from the previous gallery version.
            old = self._repo.get(patient_id, "images", uuid5(medication_id, digest + image_kind))
        if old is None:
            old = next(
                (
                    row
                    for row in self._repo.list(patient_id, "images")
                    if isinstance(row, MedicationImage)
                    and row.medication_id == medication_id
                    and row.checksum == digest
                ),
                None,
            )
        if isinstance(old, MedicationImage):
            if old.eligibility == "eligible" and old.eligibility_reason != ACTIVE_REFERENCE_REASON:
                old = old.model_copy(
                    update={
                        "eligibility": "associated",
                        "eligibility_reason": UNVERIFIED_CONTENT_REASON,
                    }
                )
            return GalleryUploadResult(photo=old, duplicate=True)
        reason = (
            UNVERIFIED_CONTENT_REASON
            if image_kind == "loose_pill"
            else "automatic_loose_pill_matching_not_available_for_this_image_type"
        )
        path = f"{patient_id}/{medication_id}/{digest}.png"
        row = MedicationImage(
            id=image_id,
            patient_id=patient_id,
            medication_id=medication_id,
            image_kind=image_kind,
            storage_path=path,
            checksum=digest,
            source_description=source_description,
            reviewed=reviewed,
            eligibility="associated",
            eligibility_reason=reason,
            created_at=self._clock.now(),
        )
        self._storage.put(path, clean)
        inserted = self._repo.add_image_if_absent(row)
        if not inserted:
            persisted = self._repo.get(patient_id, "images", image_id)
            if isinstance(persisted, MedicationImage):
                row = persisted
        return GalleryUploadResult(photo=row, duplicate=not inserted)

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
            and photos[row.image_id].eligibility_reason == ACTIVE_REFERENCE_REASON
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
                        today = self._clock.now().astimezone(self._timezone.local_tz(patient_id)).date()
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
