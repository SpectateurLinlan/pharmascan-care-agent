"""Real native memory services plus recording proof boundary; no SQL/Storage acceptance."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.application.library_files import MedicationLibraryFileService
from app.application.personal_gallery import PersonalGalleryService
from app.infrastructure.evidence_repos import MemoryEvidenceRepository
from app.infrastructure.library_files import MemoryMedicationLibraryFiles

from .test_medication_library_files import PDF, Clock
from .test_native_media_verification import setup


def test_existing_unbound_gallery_publishes_and_acknowledges_only_after_proof():
    _, storage, owner, _, _, events, objects, state, _ = setup()
    medication = uuid4()

    class Repository(MemoryEvidenceRepository):
        def add_image_if_absent(self, row):
            assert state["proof"] is not None and state["proof"].result == "bytes_verified"
            events.append("native-publish")
            return super().add_image_if_absent(row)

        def acknowledge_image_cleanup(self, o, identifier):
            assert events[-1] == "settle-delete"
            events.append("native-ack")
            return super().acknowledge_image_cleanup(o, identifier)

    repo = Repository(SimpleNamespace(list_for_patient=lambda owner: []))
    service = PersonalGalleryService(
        repository=repo,
        storage=storage,
        vision=None,
        enrollment=SimpleNamespace(get_medication=lambda *a: object()),
        normalize=lambda raw: b"DEMO-native-derived",
        clock=Clock(),
        ids=None,
    )
    result = service.upload_with_status(
        patient_id=owner,
        medication_id=medication,
        image=b"DEMO-input-not-retained",
        image_kind="package",
        source_description="DEMO supplied",
        reviewed=True,
        for_comparison=False,
        consent=True,
        demo_only=True,
    )
    assert events.index("bytes_verified") < events.index("native-publish")
    assert list(objects.values()) == [b"DEMO-native-derived"]
    changed = service.manage_image(
        owner, result.photo.id, action="delete", expected_version=result.photo.metadata_version, confirmed=True
    )
    assert changed.cleanup_pending is False and not objects
    assert events.index("absent_after_delete") < events.index("native-ack")


def test_existing_unbound_pdf_publication_ack_and_public_dto_are_unchanged():
    _, storage, owner, _, _, events, objects, state, _ = setup(bucket="medication-sources")

    class Repository(MemoryMedicationLibraryFiles):
        def add_if_absent(self, row):
            assert state["proof"] is not None and state["proof"].result == "bytes_verified"
            events.append("native-publish")
            return super().add_if_absent(row)

        def acknowledge_cleanup(self, o, identifier):
            assert events[-1] == "settle-delete"
            events.append("native-ack")
            return super().acknowledge_cleanup(o, identifier)

    repo = Repository()
    service = MedicationLibraryFileService(
        repository=repo,
        storage=storage,
        enrollment=SimpleNamespace(get_medication=lambda *a: object()),
        clock=Clock(),
        demo_only=True,
    )
    row, duplicate = service.upload(
        patient_id=owner,
        medication_id=uuid4(),
        filename="DEMO.pdf",
        content_type="application/pdf",
        data=PDF,
        category="prescription",
    )
    assert not duplicate and row.original_filename == "DEMO.pdf"
    assert list(objects.values()) == [PDF]
    service.delete(owner, row.id, confirmed=True)
    assert repo.get(owner, row.id).cleanup_pending is False and not objects
    assert events.index("bytes_verified") < events.index("native-publish")
    assert events.index("absent_after_delete") < events.index("native-ack")


def test_existing_source_registration_uses_native_proof_without_chat_task(wired):
    from app.application.evidence_enrollment import EvidenceEnrollmentService
    from app.application.source_preview import SourcePreviewService

    from .test_medication_evidence import PATIENT, Label, attach

    _, storage, _, _, _, events, objects, state, _ = setup(owner_id=PATIENT)

    class Repository(MemoryEvidenceRepository):
        def add(self, kind, row):
            if kind == "images":
                assert state["proof"] is not None
            return super().add(kind, row)

    repo = Repository(wired.medications)
    service = EvidenceEnrollmentService(
        repository=repo,
        medications=wired.medications,
        sources=wired.sources,
        fields=wired.source_fields,
        enrollment=wired.enrollment,
        preview=SourcePreviewService(provider=Label(), ids=wired.ids),
        storage=storage,
        normalize=lambda raw: raw,
        clock=wired.clock,
        ids=wired.ids,
    )
    task = attach(service, uuid4())
    assert task.product.name == "Metformin" and events.index("get") < events.index("bytes_verified")
    assert len(objects) == 1


@pytest.mark.parametrize("legacy_path", [False, True])
def test_native_draft_untracked_writer_retains_pending_without_delete_or_ack(legacy_path):
    import hashlib

    import httpx
    from app.application.native_media_verification import VerifiedNativeMediaStore
    from app.domain.errors import StaleVersionError
    from app.infrastructure.draft_deletion import SupabaseDraftDeletion
    from app.infrastructure.supabase_data import SupabaseDataClient

    owner, target = uuid4(), uuid4()
    digest = hashlib.sha256(b"DEMO").hexdigest()
    path = f"{owner}/{uuid4()}/{digest}.png" if not legacy_path else f"{owner}/DEMO-historical-source.png"
    calls = []

    def reply(request):
        calls.append(request.url.path)
        assert request.url.path.endswith("/delete_unconfirmed_medication")
        return httpx.Response(200, json={"deleted": True, "medication_deleted": True, "storage_paths": [path]})

    data = SupabaseDataClient(
        base_url="https://demo.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-patient",
        patient_id=owner,
        client=httpx.Client(transport=httpx.MockTransport(reply)),
    )

    class Intents:
        def prepare_delete(self, *a):
            if legacy_path:
                pytest.fail("Historical noncanonical path issued a new intent")
            raise StaleVersionError("Untracked legacy writer requires reconciliation")

    storage = VerifiedNativeMediaStore(
        owner=owner,
        storage=SimpleNamespace(
            bucket_id="visual-references", delete=lambda *a: pytest.fail("Untracked object was deleted")
        ),
        intents=Intents(),
        verifier=object(),
        clock=Clock(),
    )
    result = SupabaseDraftDeletion(data, storage).delete(owner, "draft", target)
    assert result.deleted and result.cleanup_pending
    assert calls == ["/rest/v1/rpc/delete_unconfirmed_medication"]
