"""SIMULATED transaction: no SQL, patient session, activation or clinical inference."""

import hashlib
from uuid import UUID

from pydantic import ValidationError as SchemaValidationError

from ..contracts.enrollment_operations import EnrollmentRecordRef, PreparedEnrollment
from ..domain.errors import DuplicateEventError, ProviderUnavailableError, StaleVersionError, ValidationError
from .memory_repos import InMemoryStore
from .supabase_data import SupabaseDataClient


class InMemoryEnrollmentWritePort:
    def __init__(self, store: InMemoryStore):
        self._store = store

    def revision(self, owner: UUID) -> int:
        with self._store.clinical.lock:
            return self._store.clinical.revisions.get(owner, 0)

    def lookup(self, owner: UUID, action_key: UUID) -> EnrollmentRecordRef | None:
        with self._store.clinical.lock:
            return self._store.enrollment_operations.get((owner, action_key))

    def for_regimen(self, owner: UUID, regimen_id: UUID) -> EnrollmentRecordRef | None:
        with self._store.clinical.lock:
            return next(
                (
                    row
                    for (patient, _), row in self._store.enrollment_operations.items()
                    if patient == owner and row.regimen_id == regimen_id
                ),
                None,
            )

    def for_attachment(self, owner: UUID, attachment_id: UUID) -> EnrollmentRecordRef | None:
        with self._store.clinical.lock:
            return next(
                (
                    row
                    for (patient, _), row in self._store.enrollment_operations.items()
                    if patient == owner and attachment_id in row.attachment_ids
                ),
                None,
            )

    def create_once(
        self,
        owner: UUID,
        action_key: UUID,
        binding_digest: str,
        prepared: PreparedEnrollment,
        *,
        expected_revision: int,
    ) -> EnrollmentRecordRef:
        # Revalidate a typed aggregate as well as its owner before any publication.
        prepared = PreparedEnrollment.model_validate(prepared.model_dump())
        result = prepared.result
        if result.regimen.patient_id != owner:
            raise ValidationError("Prepared enrollment belongs to another patient")
        receipt = EnrollmentRecordRef(
            source_candidate_index=prepared.source_candidate_index,
            attachment_ids=prepared.attachment_ids,
            workflow_task_id=prepared.workflow_task_id,
            version_no=result.regimen.version_no,
            binding_digest=binding_digest,
            regimen_id=result.regimen.id,
            medication_id=result.medication.id,
            source_id=prepared.source.id,
        )
        with self._store.clinical.lock:
            previous = self.lookup(owner, action_key)
            if previous:
                if previous.binding_digest != binding_digest:
                    raise DuplicateEventError("Enrollment action key is bound to different inputs")
                return previous
            if self.revision(owner) != expected_revision:
                raise StaleVersionError("Medication records changed; review the current details before retrying")
            publications = []
            if not prepared.already_persisted:
                rows = [
                    (self._store.sources, [prepared.source]),
                    (self._store.source_fields, result.source_fields),
                    (self._store.regimens, [result.regimen]),
                ]
                if prepared.create_medication:
                    rows.append((self._store.medications, [result.medication]))
                elif self._store.medications.get((owner, result.medication.id)) != result.medication:
                    raise StaleVersionError("Existing medication changed")
                for table, values in rows:
                    staged = table.rows.copy()
                    for value in values:
                        key = (owner, value.id)
                        if key in staged:
                            raise DuplicateEventError("Prepared record ID is already in use")
                        staged[key] = value
                    publications.append((table, staged))
            else:
                if self._store.regimens.get((owner, result.regimen.id)) != result.regimen:
                    raise StaleVersionError("Existing draft changed")
                if self.for_regimen(owner, result.regimen.id) is not None:
                    raise StaleVersionError("This draft already belongs to a saved enrollment; resume that task")
            receipts = {**self._store.enrollment_operations, (owner, action_key): receipt}
            # All validation/allocation completed; readers share this same lock.
            for table, staged in publications:
                table.rows = staged
            self._store.enrollment_operations = receipts
            self._store.clinical.revisions[owner] = expected_revision + 1
            return receipt


class SupabaseEnrollmentWritePort:
    """Draft manual-only adapter. Not composed or granted for patient execution."""

    def __init__(self, data: SupabaseDataClient):
        self._data = data

    def revision(self, owner: UUID) -> int:
        self._data.check_patient(owner)
        rows = self._data.rows("assistant_enrollment_generations", owner=f"eq.{owner}", limit="2")
        if not rows:
            return 0
        if (
            len(rows) != 1
            or rows[0].get("owner") != str(owner)
            or type(rows[0].get("revision")) is not int
            or rows[0]["revision"] < 0
        ):
            raise ProviderUnavailableError("Enrollment revision could not be verified")
        return rows[0]["revision"]

    def _receipt(self, owner: UUID, field: str, value: UUID) -> EnrollmentRecordRef | None:
        self._data.check_patient(owner)
        rows = self._data.rows(
            "assistant_enrollment_operations", owner=f"eq.{owner}", **{field: f"eq.{value}"}, limit="2"
        )
        if not rows:
            return None
        if len(rows) != 1 or rows[0].get("owner") != str(owner) or rows[0].get(field) != str(value):
            raise ProviderUnavailableError("Enrollment receipt binding could not be verified")
        try:
            return EnrollmentRecordRef.model_validate(
                {key: val for key, val in rows[0].items() if key in EnrollmentRecordRef.model_fields}
            )
        except SchemaValidationError as error:
            raise ProviderUnavailableError("Enrollment receipt was invalid") from error

    def lookup(self, owner: UUID, action_key: UUID) -> EnrollmentRecordRef | None:
        return self._receipt(owner, "action_key", action_key)

    def for_regimen(self, owner: UUID, regimen_id: UUID) -> EnrollmentRecordRef | None:
        return self._receipt(owner, "regimen_id", regimen_id)

    def for_attachment(self, owner: UUID, attachment_id: UUID) -> EnrollmentRecordRef | None:
        self._data.check_patient(owner)
        raise ProviderUnavailableError("Persistent original-source enrollment binding is not enabled")

    def create_once(
        self,
        owner: UUID,
        action_key: UUID,
        binding_digest: str,
        prepared: PreparedEnrollment,
        *,
        expected_revision: int,
    ) -> EnrollmentRecordRef:
        self._data.check_patient(owner)
        prepared = PreparedEnrollment.model_validate(prepared.model_dump())
        if prepared.result.regimen.patient_id != owner:
            raise ValidationError("Prepared enrollment belongs to another patient")
        if (
            prepared.workflow_task_id is None
            or prepared.workflow_revision is None
            or prepared.attachment_ids
            or prepared.source.source_kind.value != "user_manual"
            or prepared.source.extraction_evidence is not None
            or prepared.already_persisted
            or prepared.result.regimen.evidence_task_id is not None
        ):
            raise ProviderUnavailableError("This persistent enrollment preparation is not enabled")
        payload = self._data.request(
            "POST",
            "/rest/v1/rpc/assistant_enrollment_prepare_once",
            body={
                "p_action_key": str(action_key),
                "p_task_id": str(prepared.workflow_task_id),
                "p_expected_task_revision": prepared.workflow_revision,
                "p_expected_clinical_revision": expected_revision,
                "p_binding_digest": binding_digest,
                "p_prepared": prepared.model_dump(mode="json"),
                "p_source_checksum": hashlib.sha256(
                    f"pharmascan-synthetic-source::{owner}::{prepared.source.id}".encode()
                ).hexdigest(),
            },
        )
        if not isinstance(payload, dict) or set(payload) not in ({"result"}, {"error"}):
            raise ProviderUnavailableError("Enrollment persistence returned an invalid response")
        if "error" in payload:
            if not isinstance(payload["error"], str):
                raise ProviderUnavailableError("Enrollment persistence returned an invalid error")
            error_type = {"stale": StaleVersionError, "duplicate": DuplicateEventError, "invalid": ValidationError}.get(
                payload["error"], ProviderUnavailableError
            )
            raise error_type("Enrollment persistence did not accept this preparation")
        try:
            receipt = EnrollmentRecordRef.model_validate(payload["result"])
        except SchemaValidationError as error:
            raise ProviderUnavailableError("Enrollment persistence returned an invalid receipt") from error
        if receipt.workflow_task_id != prepared.workflow_task_id or receipt.binding_digest != binding_digest:
            raise ProviderUnavailableError("Enrollment persistence returned a different action binding")
        return receipt
