"""AUTOMATED/SIMULATED evidence/provider tests; no live success claim."""

from uuid import UUID, uuid4

import pytest
from app.application.evidence_enrollment import EvidenceEnrollmentService, printed_regimen
from app.application.personal_gallery import PersonalGalleryService
from app.application.source_preview import SourcePreviewService
from app.contracts.dto import FrequencyRuleDTO, RegimenDraftInput
from app.contracts.source_extraction import (
    ExtractedMedication,
    MedicationSourceExtractionDTO,
    PrintedEvidence,
    ProductIdentity,
    RegimenEvidence,
)
from app.contracts.vision import EmbeddingResult, MatchOutcome, ModelMetadata
from app.domain.errors import NotFoundError, ValidationError
from app.infrastructure.evidence_repos import MemoryEvidenceRepository, MemoryImageStore

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
    photo = gallery.upload(**kwargs)
    assert photo.eligibility == "eligible" and len(repo.list(PATIENT, "embeddings")) == 1
    assert gallery.upload(**kwargs).id == photo.id and vision.calls == 1
    assert gallery.image(PATIENT, photo.id) == b"DEMO loose"
    with pytest.raises(NotFoundError):
        gallery.image(OTHER, photo.id)
    package = gallery.upload(**{**kwargs, "image": b"DEMO blister", "image_kind": "blister"})
    assert package.eligibility == "associated" and vision.calls == 1
    # A reviewed reference without an active regimen is historical evidence,
    # never current-dose approval.
    run = gallery.check(patient_id=PATIENT, regimen_id=None, image=b"DEMO query", consent=True, demo_only=True)
    assert run.decision == "conflict" and run.outcome.decision == "match"
    assert not run.safe_to_take and not run.ingestion_proven and not wired.store.events


def test_gallery_without_references_and_consent_denial(evidence, wired):
    _, gallery, repo, _, vision = evidence
    run = gallery.check(patient_id=PATIENT, regimen_id=None, image=b"DEMO query", consent=True, demo_only=True)
    assert run.decision == "missing_reference" and vision.calls == 0
    with pytest.raises(ValidationError):
        gallery.check(patient_id=PATIENT, regimen_id=None, image=b"DEMO", consent=False, demo_only=True)
    assert len(repo.list(PATIENT, "runs")) == 1 and not wired.store.events


def reviewed_reference(evidence, wired):
    service, gallery, _, _, _ = evidence
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
    assert run.decision == "conflict" and run.outcome.decision == "match"
    assert "unresolved" in run.reason and not wired.store.events


def test_incompatible_embedding_does_not_call_match(evidence, wired):
    _, gallery, repo, _, vision = evidence
    _, photo = reviewed_reference(evidence, wired)
    original = repo.get(PATIENT, "embeddings", photo.id)
    # Explicitly simulated model upgrade; old references must not be mixed.
    repo._records[("embeddings", photo.id)] = original.model_copy(
        update={"result": original.result.model_copy(update={"embedding_space_id": "OTHER-space"})}
    )
    vision.compare = lambda *args: pytest.fail("Incompatible references must never reach match")
    run = gallery.check(patient_id=PATIENT, regimen_id=None, image=b"DEMO query", consent=True, demo_only=True)
    assert run.decision == "missing_reference" and not run.reference_ids and run.outcome is None
    assert "different model" in run.reason


@pytest.mark.parametrize("decision", ["unknown", "ambiguous"])
def test_low_similarity_and_close_candidates_abstain(evidence, wired, decision):
    _, gallery, _, _, vision = evidence
    task, _ = reviewed_reference(evidence, wired)
    vision.compare = lambda *args: MatchOutcome(
        decision=decision, medication_id=None, score=0.2, threshold=0.894, margin=0.115
    )
    run = gallery.check(
        patient_id=PATIENT, regimen_id=task.draft_regimen_id, image=b"DEMO query", consent=True, demo_only=True
    )
    assert run.decision == decision and not run.safe_to_take and not wired.store.events


def test_stage2_failure_preserves_private_association_and_abstains(evidence, wired):
    from app.domain.errors import ProviderUnavailableError

    _, gallery, _, _, vision = evidence
    task, _ = reviewed_reference(evidence, wired)

    def unavailable(*args):
        raise ProviderUnavailableError("SIMULATED timeout")

    vision.encode = unavailable
    run = gallery.check(
        patient_id=PATIENT, regimen_id=task.draft_regimen_id, image=b"DEMO query", consent=True, demo_only=True
    )
    assert run.decision == "unavailable" and not wired.store.events
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
    assert photo.eligibility == "associated" and photo.eligibility_reason == "personal_embedding_unavailable"


def test_storage_failure_does_not_commit_eligible_reference(evidence, wired):
    from app.domain.errors import ProviderUnavailableError

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
    assert repo.get(PATIENT, "embeddings", photo.id) and gallery.image(PATIENT, photo.id)
    assert gallery.list(PATIENT)[0]["eligible_count"] == 0
    run = gallery.check(patient_id=PATIENT, regimen_id=None, image=b"DEMO query", consent=True, demo_only=True)
    assert run.decision == "missing_reference" and not wired.store.events


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
    with pytest.raises(ValidationError):
        service.prepare_review(**params)
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
    assert wired.enrollment.get_regimen(PATIENT, first.draft_regimen_id).state.value == "superseded"
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
