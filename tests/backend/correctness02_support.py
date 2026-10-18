"""DEMO_ONLY actual application/HTTP harness; cached public labels, no live model."""

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from app.agent.conversation import ConversationService
from app.agent.model_tools import ModelTools
from app.application.ai_quota import QuotaAgent
from app.application.medication_understanding import MedicationUnderstandingService
from app.contracts.dose_display import DoseBasis
from app.contracts.dto import DoseEventDTO, DoseOccurrenceDTO, FrequencyRuleDTO, RegimenDraftInput
from app.contracts.model import FunctionCall, ModelReply
from app.contracts.observations import ObservationInput
from app.contracts.preferences import PreferenceUpdate
from app.contracts.source_extraction import (
    ExtractedMedication,
    IngredientIdentity,
    MedicationSourceExtractionDTO,
    ProductIdentity,
    RegimenEvidence,
)
from app.infrastructure.memory_quota import MemoryQuota
from app.infrastructure.memory_repos import InMemoryAgentSessionRepository
from app.infrastructure.openfda_knowledge import OpenFDAKnowledge
from app.transport.app_factory import create_app
from app.transport.auth import AuthBoundary, StaticTokenVerifier
from app.transport.container import build_container
from fastapi.testclient import TestClient

from .conftest import CountingIdGenerator, FixedClock

OWNER = UUID("de020000-0000-4000-8000-000000000001")
FOREIGN = UUID("de020000-0000-4000-8000-000000000002")
TOKEN = "DEMO.correctness02-synthetic-token"
LABELS = json.loads((Path(__file__).parent / "fixtures/correctness02_labels.json").read_text(encoding="utf8"))[
    "results"
]


class StubModel:
    model = "DEMO_ONLY_stateless_stub"

    def __init__(self):
        self.requests = 0

    def create(self, **kwargs):
        self.requests += 1
        if kwargs["history"][-1]["type"] == "function_result":
            return ModelReply(text="")
        text = json.loads(kwargs["history"][0]["content"][0]["text"])["current_input"]
        if re.search(r"what .*(?:should i take|is due)", text, re.I):
            return ModelReply(
                calls=[
                    FunctionCall(
                        id="DEMO-schedule",
                        name="check_due_dose",
                        arguments={"window": "tonight" if "tonight" in text.lower() else "today"},
                    )
                ]
            )
        status = re.search(r"did i take (.+?)(?: yesterday| today|\?)", text, re.I)
        if status:
            return ModelReply(
                calls=[FunctionCall(id="DEMO-status", name="get_dose_status", arguments={"medication_name": status[1]})]
            )
        if re.search(r"^I took .+ yesterday", text, re.I):
            return ModelReply(
                calls=[
                    FunctionCall(
                        id="DEMO-refused-past-write", name="prepare_self_report", arguments={"intake_status": "taken"}
                    )
                ]
            )
        return ModelReply(
            text="Please clarify your medication or record question; no verified answer is available for that request."
        )


class RecordingTools(ModelTools):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.calls = []

    def execute(self, **kwargs):
        output = super().execute(**kwargs)
        self.calls.append(
            {
                "tool": kwargs["name"],
                "parameters": json.loads(json.dumps(kwargs["arguments"], default=str)),
                "data": output.data,
            }
        )
        return output


def add_plan(root, name, strength, ingredient, *, existing=None, times=None, amount=1, prn=False):
    evidence = MedicationSourceExtractionDTO(
        source_document_id=uuid4(),
        source_kind="pharmacy_label",
        provider_source="photo",
        provider="DEMO_ONLY_synthetic_prescription",
        extraction_model="DEMO_fixture_v1",
        note="DEMO_ONLY synthetic patient instructions; ingredient identity fixture",
        candidates=[
            ExtractedMedication(
                product=ProductIdentity(
                    name=ingredient,
                    brand=None,
                    ingredients=[IngredientIdentity(name=ingredient, rxcui=None)],
                    strength=strength,
                    rxcui=None,
                    rxnorm_name=None,
                    source_lines=["DEMO_ONLY synthetic pharmacy label"],
                ),
                regimen_evidence=RegimenEvidence(),
            )
        ],
    )
    draft = root.enrollment.enroll_draft(
        patient_id=OWNER,
        existing_medication_id=existing,
        draft=RegimenDraftInput(
            medication_name=name,
            dose_amount=amount,
            dose_unit="tablet",
            is_prn=prn,
            frequency_rule=None if prn else FrequencyRuleDTO(kind="daily", local_times=times or ["08:00"]),
            route="oral",
        ),
        extraction_evidence=evidence,
        dose_basis=DoseBasis(
            strength_text=strength,
            form="tablet",
            formulation="standard",
            single_ingredient=True,
            patient_checked=True,
            instructions_text="DEMO_ONLY reviewed instructions",
        ),
    )
    root.enrollment.review_source_fields(patient_id=OWNER, source_id=draft.regimen.source_id)
    challenge, _ = root.enrollment.request_activation_challenge(
        patient_id=OWNER, regimen_id=draft.regimen.id, session_id=uuid4(), session_state_version=1
    )
    root.enrollment.confirm_challenge(patient_id=OWNER, challenge_id=challenge.id)
    active = root.enrollment.activate_regimen(
        patient_id=OWNER,
        regimen_id=draft.regimen.id,
        challenge_id=challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=1,
    )
    return draft.model_copy(update={"regimen": active.regimen})


def build_harness():
    clock = FixedClock(datetime(2026, 10, 12, 0, tzinfo=UTC))
    root = build_container(
        clock=clock,
        ids=CountingIdGenerator(),
        auth=AuthBoundary(
            mode="supabase",
            verifier=StaticTokenVerifier({TOKEN: {"sub": str(OWNER)}, "DEMO.foreign": {"sub": str(FOREIGN)}}),
        ),
    )
    root.preferences.save(OWNER, PreferenceUpdate(conversation_history_enabled=True, reminders_enabled=False))
    old = add_plan(root, "Amlodipine 5 mg", "5 mg", "AMLODIPINE")
    clock.advance(days=4)
    root.enrollment.end_regimen(patient_id=OWNER, regimen_id=old.regimen.id)
    current = add_plan(
        root, "Amlodipine 5 mg", "5 mg", "AMLODIPINE", existing=old.medication.id, amount=0.5, times=["20:00"]
    )
    second = add_plan(root, "Amlodipine 10 mg", "10 mg", "AMLODIPINE")
    third = add_plan(root, "Metformin 500 mg", "500 mg", "METFORMIN HYDROCHLORIDE", times=["20:00"])
    clock.advance(days=2, hours=4)
    for index, (plan, day, status) in enumerate(
        [(old, 15, "reported_taken"), (current, 17, "reported_not_taken"), (second, 17, "unsure"), (third, 17, None)]
    ):
        due = datetime(2026, 10, day, 0, tzinfo=UTC)
        occurrence = DoseOccurrenceDTO(
            id=uuid4(),
            patient_id=OWNER,
            regimen_id=plan.regimen.id,
            rule_id=uuid4(),
            due_at=due,
            status="scheduled",
            generation_key=f"DEMO-c02-{index}",
        )
        root.store.occurrences[(OWNER, occurrence.id)] = occurrence
        if status:
            event = DoseEventDTO(
                id=uuid4(),
                patient_id=OWNER,
                regimen_id=plan.regimen.id,
                occurrence_id=occurrence.id,
                event_time=due + timedelta(minutes=5),
                created_at=clock.now(),
                intake_status=status,
                idempotency_key=f"DEMO-event-{index}",
            )
            root.store.events[(OWNER, event.id)] = event
    for index, text in enumerate(["DEMO felt tired", "DEMO headache resolved", "DEMO felt well"]):
        root.observations.save(
            OWNER,
            ObservationInput(
                id=uuid4(),
                description=text,
                occurred_at=clock.now() - timedelta(hours=3 - index),
                confirmed=True,
                **(
                    {"kind": "blood_pressure", "value": 128, "secondary_value": 82, "unit": "mmHg"}
                    if index == 1
                    else {}
                ),
            ),
        )
    requests = []
    provider_state = {"mode": "normal"}

    def cached_labels(request):
        requests.append(str(request.url))
        if provider_state["mode"] == "timeout":
            raise httpx.ReadTimeout("DEMO_ONLY timeout")
        if provider_state["mode"] == "mismatch":
            return httpx.Response(200, json={"results": [LABELS[0]]})
        search = request.url.params.get("search", "").upper()
        matches = [row for row in LABELS if any(name.upper() in search for name in row["openfda"]["generic_name"])]
        return httpx.Response(200, json={"results": matches}) if matches else httpx.Response(404)

    knowledge = MedicationUnderstandingService(
        root.enrollment,
        OpenFDAKnowledge(httpx.Client(transport=httpx.MockTransport(cached_labels)), clock, monotonic=lambda: 0),
        clock,
    )
    tools = RecordingTools(
        registry=root.registry,
        fallback=root.orchestrator,
        medication_understanding=knowledge,
        long_term=root.long_term,
        enrollment=root.enrollment,
        observations=root.observations,
        clock=clock,
    )
    model = StubModel()
    conversation = ConversationService(
        model=model,
        tools=tools,
        fallback=root.orchestrator,
        sessions=InMemoryAgentSessionRepository(root.store),
        ids=root.ids,
    )
    root.ai_agent = QuotaAgent(
        repository=MemoryQuota(clock=clock, nonce_factory=lambda: str(uuid4()), limit=200),
        conversation=conversation,
        fallback=root.orchestrator,
        daily_limit=200,
    )
    app = create_app(container=root)
    result = Harness(app, root, tools, model, requests, [old, current, second, third])
    result.provider_state = provider_state
    return result


class Harness:
    def __init__(self, app, root, tools, model, requests, plans):
        self.app, self.root, self.tools, self.model, self.requests, self.plans = (
            app,
            root,
            tools,
            model,
            requests,
            plans,
        )
        self.client = TestClient(app, raise_server_exceptions=False)
        self.session = None
        self.conversation = None
        self.counter = 0
        self.rows = []

    def ask(self, text, *, language="en", selection=None):
        self.root.clock.advance(microseconds=1)
        self.root.preferences.save(OWNER, PreferenceUpdate(preferred_language=language))
        start = len(self.tools.calls)
        self.counter += 1
        request = {
            "text": text,
            "language": language,
            "session_id": self.session,
            "conversation_id": self.conversation,
            "client_turn_id": f"DEMO-{id(self)}-{self.counter}",
        }
        if selection:
            request["medication_selection"] = selection
        response = self.client.post("/api/agent/messages", headers={"Authorization": "Bearer " + TOKEN}, json=request)
        data = (
            response.json()
            if "application/json" in response.headers.get("content-type", "")
            else {"message": response.text}
        )
        if response.status_code == 200:
            self.session = data["session_id"]
            self.conversation = data.get("conversation_id")
        self.rows.append(
            {
                "user": text,
                "actual": data.get("message", str(data)),
                "status_code": response.status_code,
                "reply": data,
                "tools": self.tools.calls[start:],
                "selection": selection,
                "session": self.session,
                "conversation": self.conversation,
            }
        )
        return data

    def restore(self):
        response = self.client.post(
            f"/api/agent/conversations/{self.conversation}/resume", headers={"Authorization": "Bearer " + TOKEN}
        )
        assert response.status_code == 200, response.text
        self.session = response.json()["session_id"]

    def close(self):
        self.client.close()
