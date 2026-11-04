"""Reuse native policy for request-memory DTOs; fixed SQL still authorizes every write."""

from uuid import UUID

from ..contracts.assistant_workflows import BusinessRef
from ..contracts.enrollment_operations import PreparedEnrollment
from ..contracts.medication_evidence import EnrollmentTask
from ..contracts.workflow_medication_writes import (
    MEDICATION_WRITE_COMMAND,
    MedicationSourceMaterializationPort,
    MedicationWriteCommand,
    MedicationWriteRequest,
)
from ..domain.errors import ProviderUnavailableError, StaleVersionError, ValidationError
from .enrollment import MedicationEnrollmentService
from .enrollment_operations import EnrollmentOperationService
from .evidence_enrollment import EvidenceEnrollmentService


class MedicationWritePreparationService:
    def __init__(
        self,
        *,
        enrollment: MedicationEnrollmentService,
        operations: EnrollmentOperationService,
        evidence: EvidenceEnrollmentService,
        source_materializer: MedicationSourceMaterializationPort | None = None,
    ):
        self._enrollment, self._operations, self._evidence = enrollment, operations, evidence
        self._source_materializer = source_materializer

    @staticmethod
    def _bound(prepared: PreparedEnrollment, binding, owner):
        if prepared.result.regimen.patient_id != owner or prepared.source.patient_id != owner:
            raise ValidationError("Native medication proposal belongs to another patient")
        return prepared.model_copy(
            update={"workflow_task_id": binding.task_id, "workflow_revision": binding.task_revision}
        )

    def prepare(self, owner: UUID, command: MedicationWriteCommand) -> MedicationWriteRequest:
        command = MEDICATION_WRITE_COMMAND.validate_python(command.model_dump())
        binding = command.binding
        if command.kind == "change_plan":
            values = command.values
            expected = BusinessRef(kind="regimen", id=values.predecessor_id, version=values.expected_version)
            if (
                binding.capability_id != "medication.plan.change"
                or binding.prepared_ref != expected
                or values.action_key != binding.action_key
                or values.workflow_task_id != binding.task_id
                or values.workflow_revision != binding.task_revision
            ):
                raise StaleVersionError("Native plan preparation differs from this saved review")
            preview = self._operations.plan_change_preview(
                owner, values.predecessor_id, values.expected_version, values.expected_state, values.fields
            )
            if (
                not preview.changed
                or preview.preview.missing_fields
                or preview.preview.conflicts
                or preview.preview.normalized_draft is None
            ):
                raise ValidationError("Complete and check the changed instructions")
            draft = preview.preview.normalized_draft.model_copy(
                update={
                    "patient_edited": True,
                    "supersedes_regimen_id": preview.target.id if preview.target.state.value == "active" else None,
                }
            )
            prepared = self._enrollment.prepare_draft(
                patient_id=owner, draft=draft, existing_medication_id=preview.target.patient_medication_id
            )
            return MedicationWriteRequest(command=command, prepared=self._bound(prepared, binding, owner))
        if command.kind == "review_registration":
            if (
                binding.capability_id not in {"medication.source.add", "medication.source.review"}
                or binding.prepared_ref.kind != "enrollment_task"
            ):
                raise ValidationError("Use the current owned source registration review")
            actual = self._evidence.get(owner, binding.prepared_ref.id)
            if actual.version != binding.prepared_ref.version:
                raise StaleVersionError("The source registration changed")
            prepared = self._evidence.prepare_review_proposal(
                patient_id=owner,
                task_id=actual.id,
                draft=command.draft,
                patient_reviewed=command.confirmed,
                distinct_product_confirmed=command.distinct_product_confirmed,
                product_category=command.product_category,
                replace_active_plan=command.replace_active_plan,
            )
            if isinstance(prepared, EnrollmentTask):
                return MedicationWriteRequest(command=command, existing_review=prepared)
            return MedicationWriteRequest(command=command, prepared=self._bound(prepared, binding, owner))
        if command.kind == "save_source":
            if self._source_materializer is None:
                raise ProviderUnavailableError("Tracked native source materialization is unavailable")
            materialized = self._source_materializer.materialize(owner, command)
            if (
                materialized.attachment_id != command.attachment_id
                or materialized.metadata.task.patient_id != owner
                or materialized.metadata.source.patient_id != owner
            ):
                raise ValidationError("Materialized source differs from the owned original")
            return MedicationWriteRequest(command=command, materialized_source=materialized)
        return MedicationWriteRequest(command=command)
