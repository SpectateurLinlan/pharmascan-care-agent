"""SIMULATED PDF library lifecycle tests; no PostgreSQL or Storage provider."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Lock
from uuid import UUID

import pytest
from app.application.library_files import MedicationLibraryFileService
from app.domain.errors import NotFoundError, ValidationError
from app.infrastructure.library_files import MemoryMedicationLibraryFiles

PATIENT = UUID(int=7001)
OTHER = UUID(int=7002)
MEDICATION = UUID(int=7101)
OTHER_MEDICATION = UUID(int=7102)
PDF = b"%PDF-1.7\n1 0 obj<</Type/Catalog>>endobj\n%%EOF"


class Enrollment:
    def get_medication(self, patient_id: UUID, medication_id: UUID):
        if patient_id in {PATIENT, OTHER} and medication_id in {MEDICATION, OTHER_MEDICATION}:
            return object()
        return None


class Clock:
    def now(self):
        return datetime(2026, 10, 19, tzinfo=UTC)


class Store:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.lock = Lock()
        self.fail_delete_once = False

    def put(self, path: str, data: bytes):
        with self.lock:
            self.objects.setdefault(path, data)

    def get(self, path: str):
        return self.objects[path]

    def delete(self, path: str):
        if self.fail_delete_once:
            self.fail_delete_once = False
            raise RuntimeError("simulated storage outage")
        self.objects.pop(path, None)


@pytest.fixture
def setup():
    repository, storage = MemoryMedicationLibraryFiles(), Store()
    service = MedicationLibraryFileService(
        repository=repository, storage=storage, enrollment=Enrollment(), clock=Clock(), demo_only=True
    )
    return service, repository, storage


def upload(
    service,
    *,
    patient_id=PATIENT,
    medication_id=MEDICATION,
    filename="source.pdf",
    content_type="application/pdf",
    data=PDF,
):
    return service.upload(
        patient_id=patient_id,
        medication_id=medication_id,
        filename=filename,
        content_type=content_type,
        data=data,
        category="prescription",
        description="Patient supplied",
    )


def test_pdf_validation_and_medication_ownership(setup):
    service, _, _ = setup
    for filename, content_type, data in (
        ("source.png", "application/pdf", PDF),
        ("source.pdf", "image/png", PDF),
        ("source.pdf", "application/pdf", b"not a pdf"),
        ("source.pdf", "application/pdf", b"%PDF-1.7"),
        ("source.pdf", "application/pdf", PDF + b"<html>DEMO trailing payload</html>"),
    ):
        with pytest.raises(ValidationError):
            upload(service, filename=filename, content_type=content_type, data=data)
    with pytest.raises(ValidationError):
        upload(service, data=b"%PDF-1.7\n" + b"x" * (10 * 1024 * 1024))
    with pytest.raises(NotFoundError):
        service.upload(
            patient_id=UUID(int=7003),
            medication_id=MEDICATION,
            filename="x.pdf",
            content_type="application/pdf",
            data=PDF,
            category="other",
        )


def test_duplicate_is_patient_and_medication_scoped(setup):
    service, repository, _ = setup
    first, duplicate = upload(service)
    again, was_duplicate = upload(service)
    different_medication, other_duplicate = upload(service, medication_id=OTHER_MEDICATION)
    other_patient, cross_patient_duplicate = upload(service, patient_id=OTHER)
    assert not duplicate and was_duplicate and first.id == again.id
    assert not other_duplicate and different_medication.id != first.id
    assert not cross_patient_duplicate and other_patient.id != first.id
    assert len(repository.list_for_medication(PATIENT, MEDICATION)) == 1
    assert len(repository.list_for_medication(PATIENT, OTHER_MEDICATION)) == 1


def test_concurrent_identical_uploads_register_one_file(setup):
    service, repository, _ = setup
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: upload(service), range(16)))
    assert len(repository.list_for_medication(PATIENT, MEDICATION)) == 1
    assert sum(not duplicate for _, duplicate in results) == 1
    assert sum(duplicate for _, duplicate in results) == 15


def test_metadata_version_and_owner_scoping(setup):
    service, _, _ = setup
    file, _ = upload(service)
    with pytest.raises(NotFoundError):
        service.content(OTHER, file.id)
    updated = service.update(
        PATIENT, file.id, expected_version=1, title="Reviewed copy", category="other", description="Patient note"
    )
    assert updated.version == 2 and updated.original_filename == "source.pdf"
    with pytest.raises(ValidationError):
        service.update(PATIENT, file.id, expected_version=1, title="Stale", category="other", description="")


def test_confirmed_delete_is_tombstoned_and_cleanup_retries(setup):
    service, repository, storage = setup
    file, _ = upload(service)
    with pytest.raises(ValidationError):
        service.delete(PATIENT, file.id, confirmed=False)
    storage.fail_delete_once = True
    with pytest.raises(RuntimeError):
        service.delete(PATIENT, file.id, confirmed=True)
    tombstone = repository.get(PATIENT, file.id)
    assert tombstone is not None and tombstone.deleted_at is not None and tombstone.cleanup_pending
    service.delete(PATIENT, file.id, confirmed=True)
    assert repository.get(PATIENT, file.id).cleanup_pending is False
    assert file.storage_path not in storage.objects


def test_patient_supplied_pdf_is_not_inferred_as_a_regimen_source(setup):
    service, _, storage = setup
    file, _ = upload(service)
    assert file.source_document_id is None and file.regimen_version_id is None
    assert file.demo_only is True
    assert service.content(PATIENT, file.id)[1] == PDF
    assert service.list(PATIENT, MEDICATION) == [file]


def test_registration_timeout_is_retryable_without_deleting_possibly_referenced_bytes(setup, monkeypatch):
    service, repository, storage = setup
    register = repository.add_if_absent

    def committed_but_response_lost(row):
        register(row)
        raise TimeoutError("DEMO lost response")

    monkeypatch.setattr(repository, "add_if_absent", committed_but_response_lost)
    with pytest.raises(TimeoutError):
        upload(service)
    assert len(storage.objects) == 1
    monkeypatch.setattr(repository, "add_if_absent", register)
    existing, duplicate = upload(service)
    assert duplicate and len(storage.objects) == 1
    assert repository.get(PATIENT, existing.id) is not None


def test_uncommitted_registration_failure_converges_on_retry_and_does_not_sweep_objects(setup, monkeypatch):
    service, repository, storage = setup
    register = repository.add_if_absent
    monkeypatch.setattr(repository, "add_if_absent", lambda row: (_ for _ in ()).throw(TimeoutError("DEMO")))
    with pytest.raises(TimeoutError):
        upload(service)
    assert len(storage.objects) == 1 and not repository.list_for_medication(PATIENT, MEDICATION)
    monkeypatch.setattr(repository, "add_if_absent", register)
    _, duplicate = upload(service)
    assert not duplicate and len(storage.objects) == 1


def test_deleted_duplicate_is_not_silently_recreated_in_storage(setup):
    service, repository, storage = setup
    file, _ = upload(service)
    service.delete(PATIENT, file.id, confirmed=True)
    with pytest.raises(ValidationError, match="previously removed"):
        upload(service)
    assert not storage.objects and repository.get(PATIENT, file.id).deleted_at is not None
