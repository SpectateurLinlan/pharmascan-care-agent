"""AUTOMATED/SIMULATED evidence/provider tests; no live success claim."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from uuid import UUID, uuid4

import pytest
from app.application.evidence_enrollment import EvidenceEnrollmentService, printed_regimen
from app.application.personal_gallery import PersonalGalleryService
from app.application.source_preview import SourcePreviewService
from app.contracts.dto import FrequencyRuleDTO, PatientMedicationDTO, RegimenDraftInput
from app.contracts.enums import IdentityStatus
from app.contracts.medication_evidence import ImageEmbedding, VisualReferenceSet
from app.contracts.source_extraction import (
    ExtractedMedication,
    MedicationSourceExtractionDTO,
    PrintedEvidence,
    ProductIdentity,
    RegimenEvidence,
)
from app.contracts.vision import EmbeddingResult, MatchOutcome, ModelMetadata
from app.domain.errors import NotFoundError, ProviderUnavailableError, RegimenOverlapError, ValidationError
from app.infrastructure.evidence_repos import MemoryEvidenceRepository, MemoryImageStore, SupabaseEvidenceRepository

PATIENT = UUID(int=100)
OTHER = UUID(int=200)


class Label:
    strength = "500 mg"
    name = "Metformin"
    directions = None
    parts = None
    label_kind = None
    release = None

    def extract_medication_source(self, *, source_document_id, source_kind, image_bytes, medications=()):
        return MedicationSourceExtractionDTO(
            source_document_id=source_document_id,
            source_kind=source_kind,
            provider_source="photo",
            extraction_model="SIMULATED",
            note="DEMO",
            label_kind=self.label_kind,
            candidates=[
                ExtractedMedication(
                    product=ProductIdentity(
                        name=self.name,
                        brand=None,
                        ingredients=[],
                        strength=self.strength,
                        rxcui=None,
                        rxnorm_name=None,
                        source_lines=["Metformin " + self.strength],
                        release=self.release,
                    ),
                    regimen_evidence=RegimenEvidence(
                        instructions=self.parts,
                        directions=PrintedEvidence(value=self.directions, line=self.directions)
                        if self.directions
                        else None,
                    ),
                )
            ],
        )


class Vision:
    calls = 0
    model = ModelMetadata(
        api_version="0.8.0",
        model_version="DEMO",
        embedding_space_id="DEMO-space",
        preprocessing_version="DEMO-preprocess",
        dimension=256,
        normalized=True,
        crop_window=1.55,
        threshold=0.894,
        margin=0.115,
        calibration_json="{}",
        training_coverage="SIMULATED",
        known_limits=[],
    )

    def encode(self, image):
        self.calls += 1
        return self.model, EmbeddingResult(
            embedding=[1.0] + [0.0] * 255,
            dimension=256,
            embedding_space_id="DEMO-space",
            model_version="DEMO",
            preprocessing_version="DEMO-preprocess",
            normalized=True,
        )

    def compare(self, query, references, names):
        return MatchOutcome(
            decision="match", medication_id=str(references[0].medication_id), score=1.0, threshold=0.894, margin=0.115
        )


@pytest.fixture
def evidence(wired):
    repo = MemoryEvidenceRepository(wired.medications)
    storage = MemoryImageStore()
    label = Label()
    service = EvidenceEnrollmentService(
        repository=repo,
        medications=wired.medications,
        sources=wired.sources,
        fields=wired.source_fields,
        enrollment=wired.enrollment,
        preview=SourcePreviewService(provider=label, ids=wired.ids),
        storage=storage,
        normalize=lambda image: image,
        clock=wired.clock,
        ids=wired.ids,
    )
    vision = Vision()
    gallery = PersonalGalleryService(
        repository=repo,
        storage=storage,
        vision=vision,
        enrollment=wired.enrollment,
        normalize=lambda image: image,
        clock=wired.clock,
        ids=wired.ids,
    )
    return service, gallery, repo, label, vision


def attach(service, task, image=b"DEMO package", kind="package"):
    return service.attach(
        patient_id=PATIENT,
        task_id=task,
        image=image,
        source_kind=kind,
        medication_id=None,
        consent=True,
        demo_only=True,
    )


def mark_product_reviewed(service, task):
    service.prepare_review(
        patient_id=PATIENT,
        task_id=task.id,
        patient_reviewed=True,
        distinct_product_confirmed=False,
        draft=RegimenDraftInput(
            medication_name="Metformin",
            dose_amount=1,
            dose_unit="tablet",
            frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["20:00"]),
        ),
    )


@pytest.mark.parametrize("different_strength", [False, True])
@pytest.mark.parametrize("legacy_hint", [False, True])
def test_review_uses_product_evidence_instead_of_distinct_checkbox(evidence, different_strength, legacy_hint):
    service, _, _, label, _ = evidence
    first = attach(service, uuid4())
    if different_strength:
        label.strength = "1000 mg"
    second = attach(service, uuid4(), image=b"DEMO second product")
    assert first.medication_id in second.possible_duplicate_ids
    values = dict(
        patient_id=PATIENT,
        task_id=second.id,
        patient_reviewed=True,
        distinct_product_confirmed=legacy_hint,
        draft=RegimenDraftInput(
            medication_name=second.product.name,
            dose_amount=1,
            dose_unit="tablet",
            frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["20:00"]),
        ),
    )
    if different_strength:
        assert service.prepare_review(**values).draft_regimen_id is not None
    else:
        with pytest.raises(ValidationError, match="similar medicine"):
            service.prepare_review(**values)


def test_package_then_label_retains_sources_identity_and_clarifies(evidence, wired):
    service, _, repo, label, _ = evidence
    task_id = uuid4()
    task = attach(service, task_id)
    assert task.missing and task.status == "pending_information"
    assert task.product_missing == ["dose_form", "ingredients"]
    assert not wired.enrollment.list_regimens(PATIENT, task.medication_id)
    assert "pharmacy label" in service.summary(task, "en")
    label.directions = "Take 1 tablet at 20:00 every day with food."
    task = attach(service, task_id, b"DEMO label", "pharmacy_label")
    assert len(task.source_ids) == 2 and task.status == "ready_for_review"
    assert task.suggested_regimen.dose_amount == 1
    assert task.suggested_regimen.frequency_rule.local_times == ["20:00"]
    assert len(repo.medications(PATIENT)) == 1
    assert service.get(PATIENT, task_id) == task
    assert len(service.sources(PATIENT, task_id)) == 2
    assert service.sources(PATIENT, task_id)[0].provided_by == "patient"
    assert service.sources(PATIENT, task_id)[0].recorded_at == wired.clock.now()
    with pytest.raises(NotFoundError):
        service.get(OTHER, task_id)
    assert not wired.store.events


def test_v010_structured_sticker_merges_identity_without_inventing_times(evidence, wired):
    from app.contracts.source_extraction import PrintedInstructions

    service, _, repo, label, _ = evidence
    label.release = "ER"
    first = attach(service, uuid4())
    label.label_kind = "dispensing"
    label.parts = PrintedInstructions(
        text="Take ONE tablet twice daily after food for 7 days",
        line="DEMO sticker",
        dose={"amount": 1, "unit": "tablet"},
        times_per_day=2,
        food="after_food",
        duration="7 days",
    )
    second = attach(service, first.id, b"DEMO sticker v010", "pharmacy_label")
    assert second.medication_id == first.medication_id and len(repo.medications(PATIENT)) == 1
    assert second.suggested_regimen.dose_amount == 1 and second.suggested_regimen.frequency_rule is None
    assert second.printed_course_days == 7 and second.status == "pending_information"
    assert {"schedule", "course_start_date", "course_end_date"}.issubset(second.missing)
    assert service.get(PATIENT, second.id) == second and len(service.sources(PATIENT, second.id)) == 2
    assert not wired.store.events and not wired.store.regimens
    label.parts = label.parts.model_copy(update={"times_per_day": 3})
    conflict = attach(service, second.id, b"DEMO third conflicting sticker", "pharmacy_label")
    assert conflict.status == "conflict" and any("times_per_day" in value for value in conflict.conflicts)
    assert service.get(PATIENT, second.id).conflicts == conflict.conflicts


def test_package_classification_cannot_supply_patient_schedule(evidence):
    from app.contracts.source_extraction import PrintedInstructions

    service, _, _, label, _ = evidence
    label.label_kind = "package"
    label.parts = PrintedInstructions(text="DEMO", line="DEMO", dose={"amount": 1, "unit": "tablet"}, times_per_day=1)
    label.directions = "Take 1 tablet at 20:00 daily"
    saved = attach(service, uuid4(), kind="pharmacy_label")
    assert saved.suggested_regimen.dose_amount is None and saved.suggested_regimen.frequency_rule is None


def test_none_label_never_creates_medication_even_with_inconsistent_candidates(evidence, wired):
    service, _, repo, label, _ = evidence
    label.label_kind = "none"
    with pytest.raises(ValidationError):
        attach(service, uuid4())
    assert repo.medications(PATIENT) == [] and not wired.store.sources and not wired.store.regimens


def test_same_name_and_strength_but_different_release_preserves_conflict(evidence, wired):
    service, _, _, label, _ = evidence
    label.release = "ER"
    first = attach(service, uuid4())
    label.release = "DR"
    second = attach(service, first.id, b"DEMO other release", "pharmacy_label")
    assert second.status == "conflict" and second.product.formulation == "extended release"
    assert any("formulation" in value for value in second.conflicts)
    assert len(service.sources(PATIENT, first.id)) == 2 and not wired.store.regimens


def test_strength_conflict_is_persisted_and_blocks_review(evidence, wired):
    service, _, _, label, _ = evidence
    task = attach(service, uuid4())
    label.strength = "1000 mg"
    updated = attach(service, task.id, b"DEMO conflicting label", "pharmacy_label")
    assert updated.status == "conflict" and "strength" in updated.conflicts[0]
    assert updated.product.strength == "500 mg" and len(updated.source_ids) == 2
    with pytest.raises(ValidationError):
        service.prepare_review(
            patient_id=PATIENT,
            task_id=task.id,
            draft=RegimenDraftInput(
                medication_name="Metformin",
                dose_amount=1,
                dose_unit="tablet",
                frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["20:00"]),
            ),
            patient_reviewed=True,
            distinct_product_confirmed=False,
        )
    assert not wired.enrollment.list_regimens(PATIENT, task.medication_id)


def test_repeat_source_is_idempotent_and_missing_fields_are_not_inferred(evidence):
    service, _, repo, _, _ = evidence
    task = attach(service, uuid4())
    assert attach(service, task.id) == task
    assert len(repo.list(PATIENT, "images")) == 1
    proposal = printed_regimen("Metformin", "500 mg. Dispense 30 tablets. Twice daily.")
    assert proposal.dose_amount is None and proposal.frequency_rule is None and proposal.course_end_date is None


def test_private_photos_types_duplicate_upload_and_historical_match(evidence, wired):
    service, gallery, repo, _, vision = evidence
    task = attach(service, uuid4())
    prepared = service.prepare_review(
        patient_id=PATIENT,
        task_id=task.id,
        patient_reviewed=True,
        distinct_product_confirmed=False,
        draft=RegimenDraftInput(
            medication_name="Metformin",
            dose_amount=1,
            dose_unit="tablet",
            frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["20:00"]),
        ),
    )
    assert prepared.draft_regimen_id and not wired.store.events
    kwargs = dict(
        patient_id=PATIENT,
        medication_id=task.medication_id,
        image=b"DEMO loose",
        image_kind="loose_pill",
        source_description="DEMO patient sample",
        reviewed=True,
        for_comparison=True,
        consent=True,
        demo_only=True,
    )
    first = gallery.upload_with_status(**kwargs)
    photo = first.photo
    assert first.duplicate is False and photo.eligibility == "associated"
    duplicate = gallery.upload_with_status(**{**kwargs, "image_kind": "package"})
    assert duplicate.photo.id == photo.id and duplicate.duplicate is True
    assert duplicate.photo.image_kind == "loose_pill"
    assert len(repo.list(PATIENT, "embeddings")) == 0 and vision.calls == 0
    assert gallery.image(PATIENT, photo.id) == b"DEMO loose"
    with pytest.raises(NotFoundError):
        gallery.image(OTHER, photo.id)
    package = gallery.upload(**{**kwargs, "image": b"DEMO blister", "image_kind": "blister"})
    assert package.eligibility == "associated" and vision.calls == 0
    other = gallery.upload(
        **{**kwargs, "image": b"DEMO other evidence", "image_kind": "source", "for_comparison": False}
    )
    assert other.eligibility == "associated" and other.image_kind == "source" and vision.calls == 0
    # A photo category selected by the patient cannot create a reference index.
    run = gallery.check(patient_id=PATIENT, regimen_id=None, image=b"DEMO query", consent=True, demo_only=True)
    assert run.decision == "missing_reference" and run.outcome is None
    assert not run.safe_to_take and not run.ingestion_proven and not wired.store.events


@pytest.mark.parametrize(
    "content_type",
    [
        "synthetic packaging",
        "synthetic dispensing label",
        "synthetic loose pill",
        "synthetic blister pack",
        "synthetic ambiguous image",
        "synthetic unknown image",
    ],
)
def test_user_selected_loose_pill_never_activates_unvalidated_content(evidence, content_type):
    service, gallery, repo, _, vision = evidence
    task = attach(service, uuid4())
    mark_product_reviewed(service, task)
    before = vision.calls
    image = synthetic_gallery_image(content_type)
    photo = gallery.upload(
        patient_id=PATIENT,
        medication_id=task.medication_id,
        image=image,
        image_kind="loose_pill",
        source_description="DEMO patient selected loose pill",
        reviewed=True,
        for_comparison=True,
        consent=True,
        demo_only=True,
    )
    assert photo.image_kind == "loose_pill"
    assert photo.eligibility == "associated" and photo.reviewed is True
    assert vision.calls == before
    assert repo.get(PATIENT, "embeddings", photo.id) is None
    assert gallery.list(PATIENT)[0]["eligible_count"] == 0


def synthetic_gallery_image(content_type):
    """Small labelled DEMO_ONLY drawings; never real patient or medication photos."""
    from io import BytesIO

    from PIL import Image, ImageDraw

    image = Image.new("RGB", (240, 160), "#f4f2ec")
    draw = ImageDraw.Draw(image)
    draw.text((12, 12), "DEMO_ONLY", fill="#14534b")
    if content_type == "synthetic packaging":
        draw.rectangle((50, 45, 190, 140), outline="#14534b", width=4)
        draw.text((68, 72), "PACK", fill="#14534b")
    elif content_type == "synthetic dispensing label":
        draw.rectangle((18, 42, 222, 145), fill="white", outline="#14534b", width=2)
        draw.text((30, 60), "DEMO LABEL", fill="#14534b")
        draw.text((30, 90), "NO PATIENT DATA", fill="#14534b")
    elif content_type == "synthetic loose pill":
        draw.ellipse((75, 52, 165, 135), fill="#fdfcf9", outline="#77736b", width=3)
        draw.line((88, 90, 152, 90), fill="#77736b", width=2)
    elif content_type == "synthetic blister pack":
        draw.rounded_rectangle((28, 45, 212, 142), radius=10, fill="#d9dedb", outline="#77736b", width=3)
        for x in (64, 120, 176):
            for y in (77, 116):
                draw.ellipse((x - 12, y - 12, x + 12, y + 12), fill="#fdfcf9", outline="#77736b")
    elif content_type == "synthetic ambiguous image":
        draw.ellipse((70, 48, 158, 128), outline="#77736b", width=3)
        draw.rectangle((135, 68, 205, 130), outline="#14534b", width=3)
    else:
        draw.line((75, 55, 175, 135), fill="#77736b", width=8)
        draw.line((175, 55, 75, 135), fill="#77736b", width=8)
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def test_no_validated_classifier_keeps_upload_as_evidence_only(evidence):
    service, gallery, repo, _, vision = evidence
    task = attach(service, uuid4())
    mark_product_reviewed(service, task)

    photo = gallery.upload(
        patient_id=PATIENT,
        medication_id=task.medication_id,
        image=b"DEMO possible pill",
        image_kind="loose_pill",
        source_description="DEMO unknown content",
        reviewed=True,
        for_comparison=True,
        consent=True,
        demo_only=True,
    )
    assert photo.eligibility == "associated"
    assert photo.eligibility_reason == "image_content_not_independently_validated_comparison_disabled"
    assert vision.calls == 0 and repo.get(PATIENT, "embeddings", photo.id) is None


def test_duplicate_uploads_are_idempotent_even_when_submitted_concurrently(evidence):
    service, gallery, repo, _, vision = evidence
    task = attach(service, uuid4())
    mark_product_reviewed(service, task)
    kwargs = dict(
        patient_id=PATIENT,
        medication_id=task.medication_id,
        image=b"DEMO identical image",
        image_kind="loose_pill",
        source_description="DEMO patient sample",
        reviewed=True,
        for_comparison=True,
        consent=True,
        demo_only=True,
    )
    barrier = Barrier(2)
    original_get = repo.get
    checks = 0
    check_lock = Lock()

    def synchronized_get(patient_id, kind, record_id):
        nonlocal checks
        result = original_get(patient_id, kind, record_id)
        if kind == "images":
            with check_lock:
                should_wait = checks < 2
                checks += 1
            if should_wait:
                barrier.wait(timeout=2)
        return result

    repo.get = synchronized_get
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: gallery.upload_with_status(**kwargs), range(2)))
    assert rows[0].photo.id == rows[1].photo.id
    assert sorted(row.duplicate for row in rows) == [False, True]
    assert len([row for row in repo.list(PATIENT, "images") if row.checksum == rows[0].photo.checksum]) == 1
    assert len(repo.list(PATIENT, "embeddings")) == 0
    assert vision.calls == 0


def test_identical_bytes_are_scoped_to_patient_and_medication_identity(evidence, wired):
    service, gallery, repo, _, _ = evidence
    first_task = attach(service, uuid4())
    mark_product_reviewed(service, first_task)
    same_name_other_product = PatientMedicationDTO(
        id=uuid4(), patient_id=PATIENT, display_name="Metformin", identity_status=IdentityStatus.USER_REVIEWED_DOCUMENT
    )
    other_patient = PatientMedicationDTO(
        id=uuid4(), patient_id=OTHER, display_name="Metformin", identity_status=IdentityStatus.USER_REVIEWED_DOCUMENT
    )
    wired.medications.add(same_name_other_product)
    wired.medications.add(other_patient)
    common = dict(
        image=b"DEMO same bytes across identities",
        image_kind="loose_pill",
        source_description="DEMO patient sample",
        reviewed=True,
        for_comparison=True,
        consent=True,
        demo_only=True,
    )
    first = gallery.upload(patient_id=PATIENT, medication_id=first_task.medication_id, **common)
    second = gallery.upload(patient_id=PATIENT, medication_id=same_name_other_product.id, **common)
    third = gallery.upload(patient_id=OTHER, medication_id=other_patient.id, **common)
    assert len({first.id, second.id, third.id}) == 3
    assert sum(row.checksum == first.checksum for row in repo.list(PATIENT, "images")) == 2
    assert len(repo.list(OTHER, "images")) == 1


def test_supabase_duplicate_insert_uses_owner_scoped_atomic_conflict_handling(evidence):
    _, gallery, _, _, _ = evidence
    task = attach(evidence[0], uuid4())
    image = gallery.upload(
        patient_id=PATIENT,
        medication_id=task.medication_id,
        image=b"DEMO adapter conflict test",
        image_kind="package",
        source_description="DEMO synthetic source",
        reviewed=False,
        for_comparison=False,
        consent=True,
        demo_only=True,
    )

    class RequestClient:
        def __init__(self):
            self.responses = [[{"id": str(image.id)}], []]
            self.requests = []

        def check_patient(self, patient_id):
            assert patient_id == PATIENT

        def request(self, method, path, **kwargs):
            self.requests.append((method, path, kwargs))
            return self.responses.pop(0)

    client = RequestClient()
    repository = SupabaseEvidenceRepository(client, None)
    assert repository.add_image_if_absent(image) is True
    assert repository.add_image_if_absent(image) is False
    assert len(client.requests) == 2
    for method, path, kwargs in client.requests:
        assert method == "POST" and path == "/rest/v1/medication_images"
        assert kwargs["params"] == {"on_conflict": "patient_id,id"}
        assert kwargs["prefer"] == "resolution=ignore-duplicates,return=representation"
        assert kwargs["body"]["patient_id"] == str(PATIENT)


def test_gallery_without_references_and_consent_denial(evidence, wired):
    _, gallery, repo, _, vision = evidence
    run = gallery.check(patient_id=PATIENT, regimen_id=None, image=b"DEMO query", consent=True, demo_only=True)
    assert run.decision == "missing_reference" and vision.calls == 0
    with pytest.raises(ValidationError):
        gallery.check(patient_id=PATIENT, regimen_id=None, image=b"DEMO", consent=False, demo_only=True)
    assert len(repo.list(PATIENT, "runs")) == 1 and not wired.store.events


def reviewed_reference(evidence, wired, *, course_start_date=None, course_end_date=None):
    service, gallery, _, _, _ = evidence
    task = attach(service, uuid4())
    prepared = service.prepare_review(
        patient_id=PATIENT,
        task_id=task.id,
        patient_reviewed=True,
        distinct_product_confirmed=False,
        draft=RegimenDraftInput(
            medication_name="Metformin",
            course_start_date=course_start_date,
            course_end_date=course_end_date,
            dose_amount=1,
            dose_unit="tablet",
            frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["20:00"]),
        ),
    )
    photo = gallery.upload(
        patient_id=PATIENT,
        medication_id=task.medication_id,
        image=b"DEMO loose",
        image_kind="loose_pill",
        source_description="DEMO sample",
        reviewed=True,
        for_comparison=True,
        consent=True,
        demo_only=True,
    )
    challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=PATIENT, regimen_id=prepared.draft_regimen_id, session_id=UUID(int=400), session_state_version=1
    )
    wired.enrollment.confirm_challenge(patient_id=PATIENT, challenge_id=challenge.id)
    wired.enrollment.activate_regimen(
        patient_id=PATIENT,
        regimen_id=prepared.draft_regimen_id,
        challenge_id=challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=1,
    )
    return prepared, photo


def test_personal_match_respects_persisted_source_conflict(evidence, wired):
    service, gallery, _, label, _ = evidence
    task, _ = reviewed_reference(evidence, wired)
    label.strength = "1000 mg"
    conflict = service.attach(
        patient_id=PATIENT,
        task_id=uuid4(),
        image=b"DEMO changed label",
        source_kind="pharmacy_label",
        medication_id=task.medication_id,
        consent=True,
        demo_only=True,
    )
    assert conflict.conflicts
    run = gallery.check(
        patient_id=PATIENT, regimen_id=task.draft_regimen_id, image=b"DEMO query", consent=True, demo_only=True
    )
    assert run.decision == "missing_reference" and run.outcome is None
    assert not run.safe_to_take and not wired.store.events


def test_incompatible_embedding_does_not_call_match(evidence, wired):
    _, gallery, repo, _, vision = evidence
    _, photo = reviewed_reference(evidence, wired)
    # Simulate a retained legacy row whose old classifier provenance does not
    # qualify it under the current comparison boundary.
    legacy = photo.model_copy(
        update={
            "eligibility": "eligible",
            "eligibility_reason": "stage2_checked_loose_pill_patient_reviewed_reference_only",
        }
    )
    repo._records[("images", photo.id)] = legacy
    model, embedded = vision.encode(b"DEMO legacy reference")
    reference = VisualReferenceSet(
        id=uuid4(), patient_id=PATIENT, medication_id=photo.medication_id, model=model, created_at=photo.created_at
    )
    embedding = ImageEmbedding(
        id=photo.id,
        patient_id=PATIENT,
        medication_id=photo.medication_id,
        image_id=photo.id,
        reference_set_id=reference.id,
        result=embedded,
    )
    repo.add_reference(legacy, reference, embedding)
    vision.encode = lambda *_args: pytest.fail("Legacy content must not be encoded for comparison")
    vision.compare = lambda *args: pytest.fail("Incompatible references must never reach match")
    run = gallery.check(patient_id=PATIENT, regimen_id=None, image=b"DEMO query", consent=True, demo_only=True)
    assert run.decision == "missing_reference" and not run.reference_ids and run.outcome is None
    assert repo.get(PATIENT, "images", photo.id).eligibility == "eligible"
    assert repo.get(PATIENT, "images", photo.id).eligibility_reason == legacy.eligibility_reason
    assert repo.get(PATIENT, "embeddings", photo.id) is not None
    assert gallery.list(PATIENT)[0]["images"][0].eligibility == "associated"
    assert gallery.list(PATIENT)[0]["eligible_count"] == 0


def test_legacy_comparison_candidate_is_never_sent_to_match(evidence, wired):
    _, gallery, _, _, vision = evidence
    reviewed_reference(evidence, wired)
    vision.compare = lambda *args: pytest.fail("Unverified image type must not reach matching")
    run = gallery.check(patient_id=PATIENT, regimen_id=None, image=b"DEMO query", consent=True, demo_only=True)
    assert run.decision == "missing_reference" and run.outcome is None and not run.safe_to_take


def test_stage2_failure_preserves_private_association_and_abstains(evidence, wired):
    _, gallery, _, _, vision = evidence
    task, _ = reviewed_reference(evidence, wired)

    def unavailable(*args):
        raise ProviderUnavailableError("SIMULATED timeout")

    vision.encode = unavailable
    run = gallery.check(
        patient_id=PATIENT, regimen_id=task.draft_regimen_id, image=b"DEMO query", consent=True, demo_only=True
    )
    assert run.decision == "missing_reference" and run.outcome is None and not wired.store.events
    photo = gallery.upload(
        patient_id=PATIENT,
        medication_id=task.medication_id,
        image=b"DEMO another pill",
        image_kind="loose_pill",
        source_description="DEMO sample",
        reviewed=True,
        for_comparison=True,
        consent=True,
        demo_only=True,
    )
    assert photo.eligibility == "associated"
    assert photo.eligibility_reason == "image_content_not_independently_validated_comparison_disabled"


def test_storage_failure_does_not_commit_eligible_reference(evidence, wired):
    service, gallery, repo, _, _ = evidence
    task = attach(service, uuid4())
    before = len(repo.list(PATIENT, "images"))

    def unavailable(*args):
        raise ProviderUnavailableError("SIMULATED storage unavailable")

    gallery._storage.put = unavailable
    with pytest.raises(ProviderUnavailableError):
        gallery.upload(
            patient_id=PATIENT,
            medication_id=task.medication_id,
            image=b"DEMO new pill",
            image_kind="loose_pill",
            source_description="DEMO sample",
            reviewed=False,
            for_comparison=True,
            consent=True,
            demo_only=True,
        )
    assert len(repo.list(PATIENT, "images")) == before and not repo.list(PATIENT, "embeddings")


def test_actual_reference_validation_rejects_blank_and_small_input():
    from io import BytesIO

    from app.infrastructure.evidence_images import patient_reference_image
    from PIL import Image

    for size in ((32, 32), (100, 100)):
        stream = BytesIO()
        Image.new("RGB", size, "white").save(stream, "PNG")
        with pytest.raises(ValidationError):
            patient_reference_image(stream.getvalue())


def test_retire_reference_is_owned_retry_safe_and_retains_history(evidence, wired):
    _, gallery, repo, _, _ = evidence
    _, photo = reviewed_reference(evidence, wired)
    with pytest.raises(NotFoundError):
        gallery.retire(OTHER, photo.id)
    retired = gallery.retire(PATIENT, photo.id)
    assert retired.eligibility == "ineligible" and gallery.retire(PATIENT, photo.id) == retired
    assert repo.get(PATIENT, "embeddings", photo.id) is None and gallery.image(PATIENT, photo.id)
    assert gallery.list(PATIENT)[0]["eligible_count"] == 0
    run = gallery.check(patient_id=PATIENT, regimen_id=None, image=b"DEMO query", consent=True, demo_only=True)
    assert run.decision == "missing_reference" and not wired.store.events


def test_photo_metadata_change_fails_closed_and_preserves_original_bytes(evidence, wired):
    _, gallery, repo, _, _ = evidence
    _, photo = reviewed_reference(evidence, wired)
    original = gallery.image(PATIENT, photo.id)
    changed = gallery.manage_image(
        PATIENT,
        photo.id,
        action="edit",
        expected_version=photo.metadata_version,
        image_kind="package",
        source_description="DEMO package view",
    )
    assert changed.eligibility == "ineligible"
    assert changed.eligibility_reason == "patient_metadata_changed"
    assert gallery.image(PATIENT, photo.id) == original
    assert repo.get(PATIENT, "embeddings", photo.id) is None
    assert repo.audit_records[-1]["action"] == "edit"


def test_remove_and_delete_photo_have_distinct_lifecycle_effects(evidence, wired):
    _, gallery, repo, _, _ = evidence
    _, photo = reviewed_reference(evidence, wired)
    original = gallery.image(PATIENT, photo.id)
    removed = gallery.manage_image(
        PATIENT,
        photo.id,
        action="remove",
        expected_version=photo.metadata_version,
        confirmed=True,
    )
    assert removed.gallery_removed and removed.deleted_at is None
    assert gallery.image(PATIENT, photo.id) == original
    assert repo.get(PATIENT, "embeddings", photo.id) is None

    deletable = gallery.upload(
        patient_id=PATIENT,
        medication_id=photo.medication_id,
        image=b"DEMO independent photo for delete",
        image_kind="loose_pill",
        source_description="DEMO separate photo",
        reviewed=True,
        for_comparison=False,
        consent=True,
        demo_only=True,
    )
    deleted = gallery.manage_image(
        PATIENT,
        deletable.id,
        action="delete",
        expected_version=deletable.metadata_version,
        confirmed=True,
    )
    assert deleted.deleted_at is not None and deleted.cleanup_pending is False
    with pytest.raises(NotFoundError):
        gallery.image(PATIENT, deletable.id)


def test_new_course_uses_same_identity_and_preserves_previous_regimen(evidence, wired):
    service, _, repo, label, _ = evidence
    first, _ = reviewed_reference(evidence, wired)
    label.directions = "Take 2 tablets at 20:00 every day with food."
    task = service.attach(
        patient_id=PATIENT,
        task_id=uuid4(),
        image=b"DEMO updated course label",
        source_kind="pharmacy_label",
        medication_id=first.medication_id,
        consent=True,
        demo_only=True,
    )
    draft = RegimenDraftInput(
        medication_name="Metformin",
        dose_amount=2,
        dose_unit="tablet",
        frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["20:00"]),
        food_instruction="with food",
    )
    params = dict(
        patient_id=PATIENT,
        task_id=task.id,
        draft=draft,
        patient_reviewed=True,
        distinct_product_confirmed=False,
        product_category="supplement",
    )
    with pytest.raises(RegimenOverlapError):
        service.prepare_review(**params)
    with pytest.raises(RegimenOverlapError):
        service.prepare_review(**params, replace_active_plan=True)
    wired.enrollment.end_regimen(patient_id=PATIENT, regimen_id=first.draft_regimen_id)
    second = service.prepare_review(**params, replace_active_plan=True)
    assert service.prepare_review(**params, replace_active_plan=True).draft_regimen_id == second.draft_regimen_id
    assert len(repo.medications(PATIENT)) == 1 and second.product.category_basis == "patient_entered"
    assert wired.enrollment.get_regimen(PATIENT, first.draft_regimen_id).dose_amount == 1
    challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=PATIENT, regimen_id=second.draft_regimen_id, session_id=UUID(int=400), session_state_version=2
    )
    wired.enrollment.confirm_challenge(patient_id=PATIENT, challenge_id=challenge.id)
    wired.enrollment.activate_regimen(
        patient_id=PATIENT,
        regimen_id=second.draft_regimen_id,
        challenge_id=challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=2,
    )
    assert wired.enrollment.get_regimen(PATIENT, first.draft_regimen_id).state.value == "ended"
    assert wired.enrollment.get_regimen(PATIENT, second.draft_regimen_id).dose_amount == 2
    assert len(wired.enrollment.list_regimens(PATIENT, first.medication_id)) == 2 and not wired.store.events


def test_gallery_flags_same_names_without_merging_distinct_identities(evidence, wired):
    service, gallery, _, _, _ = evidence
    task = attach(service, uuid4())
    second = wired.enrollment.enroll_draft(
        patient_id=PATIENT,
        draft=RegimenDraftInput(
            medication_name="Metformin",
            dose_amount=2,
            dose_unit="tablet",
            frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["08:00"]),
        ),
    )
    rows = gallery.list(PATIENT)
    assert len(rows) == 2 and all(row["similar_name_records"] == 1 for row in rows)
    assert {row["medication"].id for row in rows} == {task.medication_id, second.medication.id}
    assert service.get(PATIENT, task.id).product.strength == "500 mg" and not wired.store.events


def test_medication_files_aggregate_only_explicit_enrollment_source_links(evidence, wired):
    service, gallery, _, _, _ = evidence
    task = attach(service, uuid4(), image=b"DEMO source image")

    result = gallery.files(PATIENT, task.medication_id)
    summary = next(row for row in gallery.list(PATIENT) if row["medication"].id == task.medication_id)

    assert result["medication_id"] == str(task.medication_id)
    assert len(result["files"]) == 1
    file = result["files"][0]
    assert file["format"] == "PNG"
    assert file["purpose_tags"] == ["evidence", "enrollment_source"]
    assert file["eligibility"] == "associated"
    assert file["sources"][0]["id"] == str(task.source_ids[-1])
    assert file["sources"][0]["extraction_evidence"]["extraction_model"] == "SIMULATED"
    assert file["sources"][0]["image_ids"] == [file["image_id"]]
    assert summary["source_document_count"] == len(task.source_ids)
    plan = wired.enrollment.enroll_draft(
        patient_id=PATIENT,
        existing_medication_id=task.medication_id,
        evidence_task_id=task.id,
        draft=RegimenDraftInput(
            medication_name="Metformin",
            dose_amount=1,
            dose_unit="tablet",
            frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["08:00"]),
        ),
    )
    linked_source = next(
        row
        for row in gallery.files(PATIENT, task.medication_id)["source_records"]
        if row["id"] == str(plan.regimen.source_id)
    )
    assert linked_source["regimen_ids"] == [str(plan.regimen.id)]
    with pytest.raises(NotFoundError):
        gallery.files(OTHER, task.medication_id)


def test_medication_files_merge_exact_storage_object_only(evidence):
    service, gallery, repo, _, _ = evidence
    task = attach(service, uuid4(), image=b"DEMO exact path")
    stored = repo.list(PATIENT, "images")[-1]
    duplicate_record = stored.model_copy(update={"id": uuid4(), "source_id": None, "image_kind": "loose_pill"})
    similar_name_other_file = stored.model_copy(
        update={"id": uuid4(), "storage_path": stored.storage_path + ".other", "source_id": None}
    )
    repo.add("images", duplicate_record)
    repo.add("images", similar_name_other_file)

    files = gallery.files(PATIENT, task.medication_id)["files"]

    assert len(files) == 2
    exact = next(item for item in files if len(item["image_ids"]) == 2)
    assert set(exact["image_ids"]) == {str(stored.id), str(duplicate_record.id)}
    assert set(exact["purpose_tags"]) == {"evidence", "enrollment_source"}
    assert exact["eligibility"] == "associated"


def test_explicit_course_duration_requires_dates_and_never_uses_fill_expiry_or_supply(evidence):
    from datetime import date

    service, _, _, label, _ = evidence
    label.directions = "Take 1 tablet at 20:00 every day after food for 7 days."
    task = attach(service, uuid4(), b"DEMO finite course", "pharmacy_label")
    assert task.printed_course_days == 7 and task.suggested_regimen.course_start_date is None
    draft = task.suggested_regimen
    with pytest.raises(ValidationError):
        service.prepare_review(
            patient_id=PATIENT, task_id=task.id, draft=draft, patient_reviewed=True, distinct_product_confirmed=False
        )
    proposed = printed_regimen("Metformin", "Take 1 tablet at 20:00 every day for 7 days. Start 2026-10-14.")
    assert proposed.course_start_date == date(2026, 10, 14) and proposed.course_end_date == date(2026, 10, 20)
    assert (
        printed_regimen("Metformin", "Dispense 30 tablets. Filled 2026-10-14. Expiry 2027-10-14.").course_start_date
        is None
    )


def test_strength_in_printed_name_is_not_false_name_conflict_but_strength_still_matters(evidence):
    service, _, _, label, _ = evidence
    task = attach(service, uuid4())
    label.name = "Metformin 500mg"
    consistent = attach(service, task.id, b"DEMO name with strength", "pharmacy_label")
    assert not consistent.conflicts and consistent.product.name == "Metformin"
    label.name = "Metformin 1000 mg"
    label.strength = "1000 mg"
    conflict = attach(service, task.id, b"DEMO actual strength change", "pharmacy_label")
    assert conflict.status == "conflict" and conflict.conflicts[0].startswith("strength:")


def test_gallery_current_plan_uses_injected_patient_calendar(evidence, wired):
    from datetime import date

    from app.application.timezone import FixedTzProvider

    task, _ = reviewed_reference(evidence, wired, course_start_date=date(2026, 10, 13))
    plan = wired.enrollment.get_regimen(PATIENT, task.draft_regimen_id)
    _, _, repo, _, vision = evidence
    gallery = PersonalGalleryService(
        repository=repo,
        storage=MemoryImageStore(),
        vision=vision,
        enrollment=wired.enrollment,
        normalize=lambda image: image,
        clock=wired.clock,
        ids=wired.ids,
        tz_provider=FixedTzProvider("America/Los_Angeles"),
    )
    # At this instant Singapore is Oct13, but this patient's calendar is Oct12.
    run = gallery.check(patient_id=PATIENT, regimen_id=plan.id, image=b"DEMO query", consent=True, demo_only=True)
    assert run.decision == "missing_reference" and run.outcome is None
    assert not run.safe_to_take and not wired.store.events


def test_gallery_elapsed_planned_end_remains_current_without_lifecycle_write(evidence, wired):
    from datetime import timedelta

    task, _ = reviewed_reference(
        evidence,
        wired,
        course_start_date=wired.clock.now().date() + timedelta(days=1),
        course_end_date=wired.clock.now().date() + timedelta(days=2),
    )
    wired.clock.advance(days=4)
    plan = wired.enrollment.get_regimen(PATIENT, task.draft_regimen_id)
    before = dict(wired.store.regimens)
    entry = next(row for row in evidence[1].list(PATIENT) if row["medication"].id == task.medication_id)
    assert entry["status"] == "current"
    assert wired.enrollment.get_regimen(PATIENT, plan.id).state.value == "active"
    assert wired.store.regimens == before
