"""Adversarial review regression tests. LOCAL/SIMULATED, no provider calls."""

from uuid import UUID

import httpx
import pytest
from app.contracts.dose_display import DoseBasis, DoseDisplayInput
from app.contracts.dto import FrequencyRuleDTO, RegimenDraftInput
from app.contracts.preferences import Preferences, PreferenceUpdate
from app.contracts.source_extraction import (
    ExtractedMedication,
    MedicationSourceExtractionDTO,
    ProductIdentity,
    RegimenEvidence,
)
from app.domain.dose_display import dose_display
from app.domain.errors import AuthenticationRequiredError, ValidationError
from app.infrastructure.preference_repos import SupabasePreferences
from app.infrastructure.supabase_data import SupabaseDataClient


def checked_basis(**changes) -> DoseBasis:
    return DoseBasis(
        **{
            "strength_text": "500 mg",
            "form": "tablet",
            "formulation": "standard",
            "single_ingredient": True,
            "instructions_text": "Take 1 tablet daily",
            "patient_checked": True,
            **changes,
        }
    )


@pytest.mark.parametrize(
    "instructions",
    [
        "Take 1 tablet in the morning; 2 tablets at night.",
        "Take 1 tablet (250 mg) daily",
        "Take 1 tablet. 每次2片",
        "每次1片，晚上2片",
        "不是每次1片",
        "Never ever take 1 tablet",
        "Take 1 tablet; don't split it",
    ],
)
def test_ambiguous_or_negative_instructions_never_produce_a_total(instructions):
    result = dose_display(
        DoseDisplayInput(basis=checked_basis(instructions_text=instructions), units_per_dose=1, dose_unit="tablet")
    )
    assert result.status != "calculated"
    assert result.total_amount is None


@pytest.mark.parametrize(
    "change",
    [{"strength_text": "850 mg"}, {"form": "capsule"}, {"formulation": "modified_release"}],
)
def test_new_regimen_cannot_change_known_product_identity_or_leave_partial_writes(wired, change):
    patient = UUID(int=100)
    draft = RegimenDraftInput(
        medication_name="DEMO Product",
        dose_amount=1,
        dose_unit="tablet",
        frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["20:00"]),
    )
    first = wired.enrollment.enroll_draft(patient_id=patient, draft=draft, dose_basis=checked_basis())
    wired.enrollment.review_source_fields(patient_id=patient, source_id=first.regimen.source_id)
    before_sources = len(wired.store.sources)
    before_regimens = len(wired.store.regimens)
    incoming = checked_basis(**change)
    # Use matching count/form so rejection must come from product identity, not arithmetic.
    incoming = incoming.model_copy(update={"instructions_text": f"Take 1 {incoming.form}"})
    with pytest.raises(ValidationError, match="[Pp]roduct"):
        wired.enrollment.enroll_draft(
            patient_id=patient,
            draft=draft.model_copy(update={"dose_unit": incoming.form}),
            dose_basis=incoming,
            existing_medication_id=first.medication.id,
        )
    assert len(wired.store.sources) == before_sources
    assert len(wired.store.regimens) == before_regimens
    assert wired.sources.get(patient, first.regimen.source_id).dose_basis == checked_basis()


def test_known_identity_from_a_later_regimen_is_still_checked(wired):
    patient = UUID(int=100)
    draft = RegimenDraftInput(medication_name="DEMO partial identity", dose_amount=1, dose_unit="tablet")
    first = wired.enrollment.enroll_draft(patient_id=patient, draft=draft)
    wired.enrollment.enroll_draft(
        patient_id=patient, draft=draft, existing_medication_id=first.medication.id, dose_basis=checked_basis()
    )
    with pytest.raises(ValidationError, match="Product"):
        wired.enrollment.enroll_draft(
            patient_id=patient,
            draft=draft,
            existing_medication_id=first.medication.id,
            dose_basis=checked_basis(strength_text="850 mg"),
        )


@pytest.mark.parametrize("release", ["ER", "DR"])
def test_printed_release_cannot_be_replaced_with_standard_release(wired, release):
    patient = UUID(int=100)
    draft = RegimenDraftInput(medication_name="DEMO label", dose_amount=1, dose_unit="tablet")
    extraction = MedicationSourceExtractionDTO(
        source_document_id=UUID(int=999),
        source_kind="package",
        provider_source="photo",
        extraction_model="SIMULATED",
        note="demo_only",
        candidates=[
            ExtractedMedication(
                product=ProductIdentity(
                    name="DEMO label",
                    brand=None,
                    ingredients=[],
                    strength="500 mg",
                    rxcui=None,
                    rxnorm_name=None,
                    source_lines=["DEMO label"],
                    release=release,
                ),
                regimen_evidence=RegimenEvidence(),
            )
        ],
    )
    first = wired.enrollment.enroll_draft(patient_id=patient, draft=draft, extraction_evidence=extraction)
    with pytest.raises(ValidationError, match="Product"):
        wired.enrollment.enroll_draft(
            patient_id=patient, draft=draft, existing_medication_id=first.medication.id, dose_basis=checked_basis()
        )


def test_legacy_edit_without_new_basis_still_cannot_turn_tablets_into_capsules(wired):
    patient = UUID(int=100)
    draft = RegimenDraftInput(medication_name="DEMO form", dose_amount=1, dose_unit="tablet")
    first = wired.enrollment.enroll_draft(patient_id=patient, draft=draft, dose_basis=checked_basis())
    with pytest.raises(ValidationError, match="Product"):
        wired.enrollment.enroll_draft(
            patient_id=patient,
            draft=draft.model_copy(update={"dose_unit": "capsule"}),
            existing_medication_id=first.medication.id,
        )


def test_request_preference_cache_keeps_owner_checks_and_invalidates_after_write(clock):
    """A warm cache must not become an authorization or stale-read shortcut."""
    owner, other = UUID(int=1), UUID(int=2)
    profiles = {}
    for identity in [owner, other]:
        row = Preferences(patient_id=identity, created_at=clock.now(), updated_at=clock.now()).model_dump(mode="json")
        row["user_id"] = row.pop("patient_id")
        row["language"] = row.pop("preferred_language")
        profiles[str(identity)] = row
    calls = []

    def handle(request):
        identity = request.headers["authorization"].removeprefix("Bearer DEMO-")
        calls.append((request.method, identity))
        if request.method == "PATCH":
            import json

            profiles[identity].update(json.loads(request.content))
        return httpx.Response(200, json=[profiles[identity]])

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:

        def repository(identity):
            return SupabasePreferences(
                SupabaseDataClient(
                    base_url="https://example.invalid",
                    publishable_key="SIMULATED-publishable",
                    access_token=f"DEMO-{identity}",
                    patient_id=identity,
                    client=http,
                )
            )

        a, b = repository(owner), repository(other)
        a.get(owner)
        a.get(owner)
        assert len(calls) == 1
        with pytest.raises(AuthenticationRequiredError):
            a.get(other)
        assert len(calls) == 1
        assert b.get(other).timezone == "Asia/Singapore"
        assert a.save(owner, PreferenceUpdate(timezone="Europe/London")).timezone == "Europe/London"
        assert a.save(owner, PreferenceUpdate(conversation_history_enabled=True)).conversation_history_enabled is True
        assert b.get(other).timezone == "Asia/Singapore"
        assert calls == [
            ("GET", str(owner)),
            ("GET", str(other)),
            ("PATCH", str(owner)),
            ("GET", str(owner)),
            ("PATCH", str(owner)),
            ("GET", str(owner)),
        ]
