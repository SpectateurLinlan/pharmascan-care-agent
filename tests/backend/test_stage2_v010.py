"""AUTOMATED contract/mapping checks against the supplied 0.10.0 snapshot."""

import copy
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from app.application.printed_instructions import apply_printed_parts, validate_printed_review
from app.contracts.dto import FrequencyRuleDTO, RegimenDraftInput
from app.contracts.source_extraction import ListedMedication, PrintedInstructions
from app.contracts.vision import VisionRequestError, VisionSchemaError, VisionUnavailable
from app.domain.errors import ValidationError
from app.infrastructure.stage2_http import HttpxStage2Transport
from app.infrastructure.stage2_label_adapter import PharmaScanLabelProvider
from app.infrastructure.stage2_schema import Stage2Contract

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def contract():
    return Stage2Contract(
        json.loads((ROOT / "docs/external/pharmascan-api-openapi-0.10.0.json").read_text(encoding="utf-8"))
    )


@pytest.fixture
def sticker():
    data = json.loads((ROOT / "tests/fixtures/stage2/v0_8_0/read_label_success.json").read_text(encoding="utf-8"))
    data.update(label_kind="dispensing", dispensed_by={"value": "DEMO pharmacy", "line": "DEMO pharmacy"})
    row = data["candidates"][0]
    row.update(release="ER", release_printed="XR")
    row["fields"].update(
        instructions={
            "text": "Take ONE tablet twice daily after food for 7 days",
            "line": "DEMO original line",
            "dose": {"amount": 1, "amount_max": None, "unit": "tablet"},
            "times_per_day": 2,
            "every_hours": None,
            "as_needed": False,
            "times_of_day": [],
            "food": "after_food",
            "duration": "7 days",
            "max_per_day": "2 tablets in 24 hours",
        },
        indication={"value": "blood sugar", "line": "For blood sugar"},
        cautions=[{"value": "Swallow whole", "line": "Swallow whole", "kind": "how_to_take"}],
        quantity={"value": "60 tablets", "line": "Qty: 60 TAB", "amount": 60, "unit": "tablet"},
    )
    return data


def extract(contract, sticker):
    from app.infrastructure.stage2_http import HttpTransport

    class Transport(HttpTransport):
        def post_multipart(self, path, files, data):
            assert path == "/v1/read-label" and set(files) == {"image"}
            assert json.loads(data["medications"]) == [{"id": "opaque", "name": "DEMO Metformin"}]
            return sticker

    return PharmaScanLabelProvider(
        transport=Transport(base_url="https://example.invalid", timeout_seconds=1), contract=contract
    ).extract_medication_source(
        source_document_id=uuid4(),
        source_kind="pharmacy_label",
        image_bytes=b"SIMULATED",
        medications=(ListedMedication(id="opaque", name="DEMO Metformin"),),
    )


def test_sticker_mapping_preserves_every_printed_part_without_activating(contract, sticker):
    result = extract(contract, sticker)
    row = result.candidates[0]
    assert result.label_kind == "dispensing" and result.dispensed_by.line == "DEMO pharmacy"
    assert result.provider == "pharmascan:v0.10.0:/v1/read-label"
    assert row.product.release == "ER" and row.product.release_printed == "XR"
    assert row.regimen_evidence.instructions.dose.amount == 1
    assert row.regimen_evidence.instructions.line == "DEMO original line"
    assert row.regimen_evidence.supplied_quantity.amount == 60
    assert row.regimen_evidence.cautions[0].line == "Swallow whole"
    assert row.regimen_evidence.indication.value == "blood sugar"
    assert row.regimen_evidence.dose_amount is None and not row.can_activate_regimen
    draft = apply_printed_parts(RegimenDraftInput(medication_name="DEMO"), row.regimen_evidence.instructions)
    assert draft.dose_amount == 1 and draft.dose_unit == "tablet" and draft.food_instruction == "after food"
    assert draft.frequency_rule is None and draft.course_start_date is None and draft.course_end_date is None


def test_missing_fields_stay_unknown_and_none_is_not_a_product(contract, sticker):
    data = copy.deepcopy(sticker)
    data["candidates"][0]["fields"] = None
    result = extract(contract, data)
    assert result.candidates[0].regimen_evidence.instructions is None
    assert result.candidates[0].regimen_evidence.dose_amount is None
    data.update(label_kind="none", candidates=[])
    assert extract(contract, data).candidates == []


@pytest.mark.parametrize(
    "updates",
    [
        {"every_hours": 6},
        {"as_needed": True},
        {"dose": {"amount": 1, "amount_max": 2, "unit": "tablet"}},
    ],
)
def test_interval_prn_and_range_never_get_an_invented_fixed_schedule(updates):
    parts = PrintedInstructions(text="DEMO", line="DEMO", **updates)
    draft = apply_printed_parts(RegimenDraftInput(medication_name="DEMO"), parts)
    if updates.get("every_hours"):
        # Owner-approved later flow retains the printed interval and asks for its anchor;
        # retaining a frequency is not inventing clock times or a historical start.
        assert draft.frequency_rule.kind == "interval"
        assert draft.frequency_rule.every_hours == updates["every_hours"]
        assert draft.frequency_rule.local_times == [] and draft.frequency_rule.interval_anchor is None
        assert draft.course_start_date is None
    else:
        assert draft.frequency_rule is None
    assert draft.is_prn == bool(updates.get("as_needed"))
    assert draft.dose_amount is None


def test_review_cannot_erase_explicit_frequency_or_dose():
    parts = PrintedInstructions(text="DEMO", line="DEMO", dose={"amount": 1, "unit": "tablet"}, times_per_day=2)
    draft = RegimenDraftInput(
        medication_name="DEMO",
        dose_amount=1,
        dose_unit="tablet",
        frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["20:00"]),
    )
    with pytest.raises(ValidationError):
        validate_printed_review(draft, parts)
    validate_printed_review(
        draft.model_copy(update={"frequency_rule": FrequencyRuleDTO(kind="daily", local_times=["08:00", "20:00"])}),
        parts,
    )


@pytest.mark.parametrize("printed,local", [("20:00", "20:00"), ("8:30 pm", "20:30"), ("12:15 am", "00:15")])
def test_explicit_clock_in_real_ocr_text_cannot_be_replaced_by_default_time(printed, local):
    parts = PrintedInstructions(
        text=f"Take ONE tablet daily at {printed} for 7 days.",
        line=f"Take ONE tablet daily at {printed} for 7 days.",
        times_per_day=1,
    )
    wrong = RegimenDraftInput(
        medication_name="DEMO", frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["08:00"])
    )
    with pytest.raises(ValidationError, match="explicit clock"):
        validate_printed_review(wrong, parts)
    validate_printed_review(
        wrong.model_copy(update={"frequency_rule": FrequencyRuleDTO(kind="daily", local_times=[local])}), parts
    )


def test_chinese_explicit_clock_is_preserved_and_invalid_am_pm_is_not_guessed():
    draft = RegimenDraftInput(
        medication_name="DEMO", frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["20:00"])
    )
    validate_printed_review(draft, PrintedInstructions(text="每天在20:00服用一片", line="每天在20:00服用一片"))
    with pytest.raises(ValidationError, match="ambiguous"):
        validate_printed_review(draft, PrintedInstructions(text="Take at 20:00 pm", line="Take at 20:00 pm"))


def test_printed_interval_first_clock_does_not_use_unknown_time_default():
    from datetime import date

    parts = PrintedInstructions(text="Take every 6 hours, starting at 20:00", line="DEMO", every_hours=6)
    draft = RegimenDraftInput(
        medication_name="DEMO",
        course_start_date=date(2026, 10, 18),
        frequency_rule=FrequencyRuleDTO(kind="interval", every_hours=6, local_times=["08:00"]),
    )
    with pytest.raises(ValidationError, match="explicit clock"):
        validate_printed_review(draft, parts)
    validate_printed_review(
        draft.model_copy(
            update={"frequency_rule": FrequencyRuleDTO(kind="interval", every_hours=6, local_times=["20:00"])}
        ),
        parts,
    )


@pytest.mark.parametrize("status", [409, 422, 429, 503])
def test_provider_failures_are_not_recognition_results(contract, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"code": "invalid_input", "detail": "DEMO", "request_id": "DEMO"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        transport = HttpxStage2Transport(
            client=client, contract=contract, base_url="https://example.invalid", sleep=lambda _: None
        )
        with pytest.raises((VisionRequestError, VisionUnavailable, VisionSchemaError)):
            transport.post_json("/v1/match", {})
    assert len(calls) == 1


def test_html_is_rejected_not_a_success(contract):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, headers={"content-type": "text/html"}, text="<html>Waking up</html>")
        )
    ) as client:
        transport = HttpxStage2Transport(
            client=client, contract=contract, base_url="https://example.invalid", sleep=lambda _: None
        )
        with pytest.raises(VisionSchemaError):
            transport.get_json("/health")


@pytest.mark.parametrize("status", [409, 429])
def test_source_service_version_or_capacity_failure_is_not_patient_invalid_input(contract, status):
    import io

    from app.domain.errors import ProviderUnavailableError
    from app.infrastructure.source_gateway import SourceGateway
    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(output, format="PNG")
    error = json.loads((ROOT / "tests/fixtures/stage2/v0_8_0/common_error.json").read_text(encoding="utf-8"))
    gateway = SourceGateway(
        base_url="https://example.invalid",
        contract=contract,
        client_factory=lambda: httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(status, json=error))
        ),
    )
    with pytest.raises(ProviderUnavailableError):
        gateway.extract_medication_source(
            source_document_id=uuid4(), source_kind="pharmacy_label", image_bytes=output.getvalue()
        )


def test_input_routing_does_not_execute_provider_suggested_tools(contract):
    import io

    from app.infrastructure.source_gateway import SourceGateway
    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(output, format="PNG")
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path == "/v1/check-input"
        return httpx.Response(
            200,
            json={
                "input_check": {"type": "printed", "checked": True, "abstained": True},
                "next_tools": ["arbitrary_sql", "record_dose"],
                "message": "DEMO",
            },
        )

    gateway = SourceGateway(
        base_url="https://example.invalid",
        contract=contract,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = gateway.route_image(output.getvalue())
    assert result.image_type == "printed" and result.suggested_workflow == "source_review"
    assert len(calls) == 1 and "next_tools" not in result.model_dump()
    with pytest.raises(VisionSchemaError):
        contract.validate("Body_check_input_photo_v1_check_input_post", {"image": "demo.png", "input_type": "printed"})


def test_embedding_search_requires_same_space_and_does_not_reembed(contract):
    from app.contracts.vision import EmbeddingResult, ModelVersionMismatch
    from app.infrastructure.stage2_adapter import HttpStage2VisionProvider
    from app.infrastructure.stage2_http import HttpTransport

    wire = json.loads((ROOT / "tests/fixtures/stage2/v0_8_0/identify_success.json").read_text(encoding="utf-8"))
    calls = []

    class Transport(HttpTransport):
        def post_json(self, path, payload):
            calls.append((path, payload))
            assert path == "/v1/search-by-embedding" and "imprint_reads" not in payload
            return wire

    query = EmbeddingResult(
        embedding=[1.0] + [0.0] * 255,
        dimension=256,
        model_version=wire["model_version"],
        embedding_space_id="DEMO-space",
        preprocessing_version="DEMO-preprocess",
        normalized=True,
        text_reading="unavailable",
        imprint_reads=["DO NOT USE"],
    )
    provider = HttpStage2VisionProvider(
        transport=Transport(base_url="https://example.invalid", timeout_seconds=1),
        contract=contract,
        model_version=query.model_version,
        embedding_space_id=query.embedding_space_id,
        preprocessing_version=query.preprocessing_version,
    )
    assert provider.search_by_embedding(query=query)
    with pytest.raises(ModelVersionMismatch):
        provider.search_by_embedding(query=query.model_copy(update={"embedding_space_id": "OTHER"}))
    assert len(calls) == 1


@pytest.mark.parametrize("reading", ["used", "unavailable", "skipped"])
def test_personal_match_forwards_only_actually_used_imprint_reads(contract, reading):
    from app.contracts.vision import EmbeddingResult, GalleryReference
    from app.infrastructure.stage2_adapter import HttpStage2VisionProvider
    from app.infrastructure.stage2_http import HttpTransport

    wire = json.loads((ROOT / "tests/fixtures/stage2/v0_8_0/match_success.json").read_text(encoding="utf-8"))
    wire["results"][0]["imprint_check"] = "not_read"
    payloads = []

    class Transport(HttpTransport):
        def post_json(self, path, payload):
            assert path == "/v1/match"
            payloads.append(payload)
            return wire

    query = EmbeddingResult(
        embedding=[1.0] + [0.0] * 255,
        dimension=256,
        model_version=wire["model_version"],
        embedding_space_id=wire["embedding_space_id"],
        preprocessing_version="DEMO",
        normalized=True,
        text_reading=reading,
        imprint_reads=["DEMO-123"],
    )
    reference = GalleryReference(
        medication_id=wire["results"][0]["medication_id"],
        name="DEMO",
        embeddings=[query.embedding],
        model_version=query.model_version,
        embedding_space_id=query.embedding_space_id,
        preprocessing_version=query.preprocessing_version,
    )
    provider = HttpStage2VisionProvider(
        transport=Transport(base_url="https://example.invalid", timeout_seconds=1),
        contract=contract,
        model_version=query.model_version,
        embedding_space_id=query.embedding_space_id,
        preprocessing_version=query.preprocessing_version,
    )
    runner_up = reference.model_copy(update={"medication_id": wire["results"][0]["runner_up"]["medication_id"]})
    result = provider.match(queries=[query], gallery=[reference, runner_up])
    assert ("query_reads" in payloads[0]) == (reading == "used")
    assert result.imprint_check == "not_read"  # A match is not proof of imprint verification.
