"""Atomic simulated source publication. No SQL, provider calls or patient activation."""

import hashlib
from collections.abc import Callable
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID, uuid5

from ..contracts.dto import PatientMedicationDTO, SourceDocumentDTO, SourceFieldDTO
from ..contracts.medication_evidence import EnrollmentTask, EvidenceSourcePublication, MedicationImage, SourceLink
from ..contracts.workflow_attachments import WorkflowEnrollmentSource
from ..domain.errors import DuplicateEventError, NotFoundError, StaleVersionError, ValidationError
from .evidence_repos import MemoryEvidenceRepository, MemoryImageStore
from .memory_repos import InMemoryStore


@dataclass(frozen=True)
class _Receipt:
    binding: tuple
    task_id: UUID
    source_id: UUID
    attachment_id: UUID | None = None
    workflow_task_id: UUID | None = None


class MemoryEvidenceEnrollmentWritePort:
    @contextmanager
    def local_transaction(self):
        """Public local scope including memory objects and native operation receipts."""
        with self._store.clinical.lock, self._evidence.local_transaction(), self._images.local_transaction():
            tables = [self._store.sources, self._store.source_fields, self._store.medications, self._store.regimens]
            snapshots = [deepcopy(table.rows) for table in tables]
            receipts, generations = deepcopy(self._receipts), deepcopy(self._store.clinical.revisions)
            try:
                yield
            except BaseException:
                for table, snapshot in zip(tables, snapshots, strict=True):
                    table.rows = snapshot
                self._receipts.clear()
                self._receipts.update(receipts)
                self._store.clinical.revisions.clear()
                self._store.clinical.revisions.update(generations)
                raise

    def __init__(self, store: InMemoryStore, evidence: MemoryEvidenceRepository, images: MemoryImageStore):
        self._store, self._evidence, self._images = store, evidence, images
        if evidence._lock is not store.clinical.lock or images._lock is not store.clinical.lock:
            raise ValueError("Source repositories must share the clinical transaction lock")
        self._receipts: dict[tuple[UUID, UUID], _Receipt] = {}

    def revision(self, owner: UUID) -> int:
        with self._store.clinical.lock:
            return self._store.clinical.revisions.get(owner, 0)

    def workflow_owner(self, owner: UUID, task_id: UUID) -> UUID | None:
        with self._store.clinical.lock:
            # First saved workflow owns registration changes. Later identical-photo
            # references protect their raw originals, without transferring authority.
            return next(
                (
                    receipt.workflow_task_id
                    for (patient, _), receipt in self._receipts.items()
                    if patient == owner and receipt.task_id == task_id and receipt.workflow_task_id is not None
                ),
                None,
            )

    def review_unactivated(
        self,
        owner: UUID,
        task_id: UUID,
        expected_version: int,
        expected_clinical_revision: int,
        apply: Callable[[], EnrollmentTask],
    ) -> EnrollmentTask:
        """A fixed application source-review callback; never HTTP/model-provided code.

        Run existing review policy against unpublished maps. All normal readers
        share this lock; failures restore the original snapshots before release.
        The callback must not perform providers, notifications or activation.
        """
        with self._store.clinical.lock:
            task = self._evidence.get(owner, "tasks", task_id)
            if (
                not isinstance(task, EnrollmentTask)
                or task.version != expected_version
                or task.draft_regimen_id is not None
                or self.revision(owner) != expected_clinical_revision
            ):
                raise StaleVersionError("The source review changed; reopen its current version")
            # Existing workflow-bound instructions retain their own independent
            # confirmation authority. Do not acquire a workflow lock from inside
            # this clinical transaction or adopt another enrollment's source.
            related_sources = {
                *task.source_ids,
                *(
                    row.source_id
                    for row in self._store.regimens.values()
                    if row.patient_id == owner and row.evidence_task_id == task.id and row.source_id is not None
                ),
            }
            if any(
                patient == owner and row.workflow_task_id is not None and row.source_id in related_sources
                for (patient, _), row in self._store.enrollment_operations.items()
            ):
                raise StaleVersionError("Continue the original saved enrollment to review these instructions")
            tables = (self._store.sources, self._store.source_fields, self._store.medications, self._store.regimens)
            snapshots = tuple(table.rows for table in tables)
            evidence, revisions = self._evidence._records, self._store.clinical.revisions
            operations = self._store.enrollment_operations
            copies = tuple(snapshot.copy() for snapshot in snapshots)
            staged_evidence, staged_revisions, staged_operations = evidence.copy(), revisions.copy(), operations.copy()
            for table, snapshot in zip(tables, copies, strict=True):
                table.rows = snapshot
            self._evidence._records = staged_evidence
            self._store.clinical.revisions = staged_revisions
            self._store.enrollment_operations = staged_operations
            try:
                result = apply()
                regimen = self._store.regimens.get((owner, result.draft_regimen_id))
                if (
                    result.patient_id != owner
                    or result.id != task_id
                    or result.status != "draft_created"
                    or result.medication_id != task.medication_id
                    or result.version != expected_version + 1
                    or self._evidence.get(owner, "tasks", task_id) != result
                    or regimen is None
                    or regimen.patient_medication_id != task.medication_id
                    or regimen.state.value not in {"draft", "pending_clarification"}
                ):
                    raise ValidationError("Source review did not produce the expected unactivated owned plan")
                for table, before in zip(tables, snapshots, strict=True):
                    if {key: row for key, row in table.rows.items() if key[0] != owner} != {
                        key: row for key, row in before.items() if key[0] != owner
                    }:
                        raise ValidationError("Source review changed another patient's records")
                if {key: row for key, row in self._evidence._records.items() if row.patient_id != owner} != {
                    key: row for key, row in evidence.items() if row.patient_id != owner
                }:
                    raise ValidationError("Source review changed another patient's evidence")
                if any(self._store.regimens.get(key) != row for key, row in snapshots[-1].items()):
                    raise ValidationError("Source review cannot change an existing plan version")
                return result
            except BaseException:
                for table, before in zip(tables, snapshots, strict=True):
                    table.rows = before
                self._evidence._records = evidence
                self._store.clinical.revisions = revisions
                self._store.enrollment_operations = operations
                raise

    def lookup(self, owner: UUID, action_key: UUID) -> EnrollmentTask | None:
        with self._store.clinical.lock:
            receipt = self._receipts.get((owner, action_key))
            if receipt is None:
                return None
            task = self._evidence.get(owner, "tasks", receipt.task_id)
            return task if isinstance(task, EnrollmentTask) and receipt.source_id in task.source_ids else None

    def original_sources(self, owner: UUID, attachment_id: UUID) -> tuple[UUID, ...]:
        with self._store.clinical.lock:
            return tuple(
                dict.fromkeys(
                    receipt.source_id
                    for (patient, _), receipt in self._receipts.items()
                    if patient == owner and receipt.attachment_id == attachment_id
                )
            )

    def lookup_original(self, owner: UUID, action_key: UUID, workflow_task_id: UUID, attachment_id: UUID):
        with self._store.clinical.lock:
            receipt = self._receipts.get((owner, action_key))
            if receipt is None:
                return None
            if receipt.workflow_task_id != workflow_task_id or receipt.attachment_id != attachment_id:
                raise DuplicateEventError("Source receipt belongs to another task or original")
            actual = self.lookup(owner, action_key)
            if actual is None:
                raise StaleVersionError("The saved source is unavailable; check its current record before retrying")
            return actual

    def bind_existing_original(
        self,
        owner: UUID,
        action_key: UUID,
        task: EnrollmentTask,
        source: WorkflowEnrollmentSource,
        checksum: str,
    ) -> EnrollmentTask:
        if task.patient_id != owner or source.owner != owner or source.extraction.source_kind != source.source_kind:
            raise ValidationError("The original source belongs to another owner or type")
        binding = (
            task.id,
            task.medication_id,
            checksum,
            source.source_kind,
            source.task_id,
            source.attachment_id,
            source.original_checksum,
        )
        with self._store.clinical.lock:
            previous = self._receipts.get((owner, action_key))
            if previous and previous.binding != binding:
                raise DuplicateEventError("Source action key is bound to a different original")
            actual = self._evidence.get(owner, "tasks", task.id)
            if actual != task:
                raise StaleVersionError("The saved source changed; check its current record")
            image = next(
                (
                    row
                    for row in self._evidence.list(owner, "images")
                    if isinstance(row, MedicationImage)
                    and row.medication_id == task.medication_id
                    and row.checksum == checksum
                    and row.source_description == source.source_kind
                    and row.source_id in task.source_ids
                ),
                None,
            )
            if image is None or self._store.sources.get((owner, image.source_id)) is None:
                raise StaleVersionError("The matching owned source evidence is unavailable")
            if previous is None:
                self._receipts = {
                    **self._receipts,
                    (owner, action_key): _Receipt(
                        binding, task.id, image.source_id, source.attachment_id, source.task_id
                    ),
                }
            return actual

    def publish_once(self, owner: UUID, action_key: UUID, prepared: EvidenceSourcePublication) -> EnrollmentTask:
        # Revalidate every copied DTO and every ownership/reference assertion before
        # allocating any published maps. A Python DTO is not authorization evidence.
        source = SourceDocumentDTO.model_validate(prepared.source.model_dump())
        fields = tuple(SourceFieldDTO.model_validate(row.model_dump()) for row in prepared.fields)
        medication = PatientMedicationDTO.model_validate(prepared.medication.model_dump())
        task = EnrollmentTask.model_validate(prepared.task.model_dump())
        image = MedicationImage.model_validate(prepared.image.model_dump())
        link = SourceLink.model_validate(prepared.link.model_dump())
        prior = EnrollmentTask.model_validate(prepared.prior_task.model_dump()) if prepared.prior_task else None
        rows = (source, medication, task, image, link, *fields, *((prior,) if prior else ()))
        if any(row.patient_id != owner for row in rows):
            raise ValidationError("Prepared source rows belong to different patients")
        origin = (prepared.workflow_task_id, prepared.attachment_id, prepared.original_checksum)
        if any(value is not None for value in origin) and (
            not all(value is not None for value in origin) or len(prepared.original_checksum) != 64
        ):
            raise ValidationError("Original source provenance is incomplete")
        expected_sources = [*(prior.source_ids if prior else ()), source.id]
        if (
            image.medication_id != medication.id
            or link.medication_id != medication.id
            or task.medication_id != medication.id
            or (prior and prior.medication_id != medication.id)
            or image.source_id != source.id
            or link.source_id != source.id
            or task.source_ids != expected_sources
            or task.version != (prior.version if prior else 1) + 1
            or (prior and task.id != prior.id)
            or task.status == "draft_created"
            or task.draft_regimen_id is not None
            or (prior and prior.status == "draft_created")
            or image.id != uuid5(medication.id, image.checksum + source.source_kind.value)
            or link.id != uuid5(medication.id, str(source.id))
            or image.storage_path != f"{owner}/{medication.id}/{image.checksum}.png"
            or hashlib.sha256(prepared.derived_image).hexdigest() != image.checksum
            or not fields
            or len({row.id for row in fields}) != len(fields)
            or any(
                row.source_id != source.id or row.review_status.value != "extracted" or row.reviewed_at
                for row in fields
            )
            or source.review_status.value != "extracted"
            or source.reviewed_at
            or source.extraction_evidence is None
            or source.extraction_evidence.source_document_id != source.id
            or source.extraction_evidence.source_kind != source.source_kind.value
            or image.source_description != source.source_kind.value
            or (
                prepared.create_medication
                and (
                    prior is not None
                    or medication.source_id != source.id
                    or medication.identity_status.value != "unverified"
                )
            )
        ):
            raise ValidationError("Prepared source aggregate references or content do not match")
        target = None if prepared.create_medication else medication.id
        binding = (task.id, target, image.checksum, source.source_kind.value, *origin)
        with self._store.clinical.lock:
            occupied = self._evidence._records.get(("tasks", task.id))
            if occupied is not None and occupied.patient_id != owner:
                raise NotFoundError("Source registration not found")
            previous = self._receipts.get((owner, action_key))
            if previous:
                if previous.binding != binding:
                    raise DuplicateEventError("Source action key is bound to different inputs")
                actual = self.lookup(owner, action_key)
                if actual is None:
                    raise StaleVersionError("The previously saved source is unavailable; check its current record")
                return actual
            # Two requests for the same source can finish recognition concurrently.
            # Reuse only an actually saved owned image/task, never an absent row.
            current = self._evidence.get(owner, "tasks", task.id)
            if isinstance(current, EnrollmentTask):
                duplicate = next(
                    (
                        row
                        for row in self._evidence.list(owner, "images")
                        if isinstance(row, MedicationImage)
                        and row.medication_id == current.medication_id
                        and row.checksum == image.checksum
                        and row.source_id in current.source_ids
                        and row.source_description == source.source_kind.value
                    ),
                    None,
                )
                if duplicate is not None and (target is None or current.medication_id == target):
                    self._receipts = {
                        **self._receipts,
                        (owner, action_key): _Receipt(
                            binding, current.id, duplicate.source_id, prepared.attachment_id, prepared.workflow_task_id
                        ),
                    }
                    return current
            if (
                prepared.expected_clinical_revision is None
                or self.revision(owner) != prepared.expected_clinical_revision
            ):
                raise StaleVersionError("Medication records changed; prepare the source again")
            if current != prior:
                raise StaleVersionError("Source registration changed; prepare its current version again")
            if not prepared.create_medication and self._store.medications.get((owner, medication.id)) != medication:
                raise StaleVersionError("The selected medication changed")
            staged = []
            for table, values in (
                (self._store.sources, (source,)),
                (self._store.source_fields, fields),
                (self._store.medications, (medication,) if prepared.create_medication else ()),
            ):
                snapshot = table.rows.copy()
                for row in values:
                    if (owner, row.id) in snapshot:
                        raise DuplicateEventError("Source record ID is already in use")
                    snapshot[(owner, row.id)] = row
                staged.append((table, snapshot))
            evidence = self._evidence._records.copy()
            for kind, row in (("sources", link), ("images", image)):
                if (kind, row.id) in evidence:
                    raise DuplicateEventError("Evidence record ID is already in use")
                evidence[(kind, row.id)] = row
            evidence[("tasks", task.id)] = task
            objects = self._images.stage_put(image.storage_path, prepared.derived_image)
            receipts = {
                **self._receipts,
                (owner, action_key): _Receipt(
                    binding, task.id, source.id, prepared.attachment_id, prepared.workflow_task_id
                ),
            }
            revisions = {**self._store.clinical.revisions, owner: self.revision(owner) + 1}
            # No validation, provider, storage operation or allocation after this
            # point; all normal readers use the same injected transaction lock.
            for table, snapshot in staged:
                table.rows = snapshot
            self._evidence._records = evidence
            self._images._data = objects
            self._receipts = receipts
            self._store.clinical.revisions = revisions
            return task
