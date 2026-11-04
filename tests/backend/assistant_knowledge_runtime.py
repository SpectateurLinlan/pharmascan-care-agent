"""Opt-in loopback acceptance runtime: real app, synthetic owners, public replay.

Run only with MEDITHREAD_LOCAL_ACCEPTANCE=1; never a deployment entry point.
No Settings.from_env, LLM, SQL, Auth provider, vision or notification integration.
"""

import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
from app.agent.conversation import ConversationService
from app.agent.model_tools import ModelTools
from app.application.ai_quota import QuotaAgent
from app.application.medication_names import MedicationNameResolver
from app.application.medication_understanding import MedicationUnderstandingService
from app.infrastructure.memory_quota import MemoryQuota
from app.infrastructure.memory_repos import InMemoryAgentSessionRepository
from app.infrastructure.openfda_knowledge import OpenFDAKnowledge
from app.transport.app_factory import create_app as patient_app
from app.transport.container import build_container


def create_app(
    *,
    workflows_enabled: bool = False,
    workflow_preview=None,
    clock=None,
    workflow_visual=None,
    workflow_personal_vision=None,
    progress_enabled=False,
):
    if os.environ.get("MEDITHREAD_LOCAL_ACCEPTANCE") != "1":
        raise RuntimeError("This synthetic runtime requires explicit local acceptance opt-in")
    root = build_container(
        knowledge_v2_enabled=True,
        assistant_workflows_enabled=workflows_enabled,
        assistant_progress_enabled=progress_enabled,
        workflow_preview=workflow_preview,
        workflow_visual=workflow_visual,
        workflow_personal_vision=workflow_personal_vision,
        clock=clock,
    )
    root.close_request()
    fixture = json.loads((Path(__file__).parent / "fixtures/ibuprofen_labels_public.json").read_text(encoding="utf-8"))

    def replay(request):
        if "IBUPROFEN" not in request.url.params.get("search", ""):
            return httpx.Response(404)
        return httpx.Response(200, content=fixture["raw_response_utf8"], headers={"Content-Type": "application/json"})

    http = httpx.Client(transport=httpx.MockTransport(replay))
    root.medication_understanding = MedicationUnderstandingService(
        root.enrollment,
        OpenFDAKnowledge(http, root.clock, monotonic=lambda: 0, scoped_facts=True),
        root.clock,
        name_resolver=MedicationNameResolver(),
    )
    if root.assistant_workflows is not None:
        from app.application.workflow_knowledge import WorkflowKnowledgeService

        root.assistant_knowledge = WorkflowKnowledgeService(
            workflows=root.assistant_workflows,
            understanding=root.medication_understanding,
            resolver=MedicationNameResolver(),
        )
    root.close_request = http.close

    class NoModel:
        def create(self, **kwargs):
            raise AssertionError("This acceptance runtime must not invoke an LLM")

    conversation = ConversationService(
        model=NoModel(),
        fallback=root.orchestrator,
        tools=ModelTools(
            registry=root.registry,
            fallback=root.orchestrator,
            medication_understanding=root.medication_understanding,
            clock=root.clock,
        ),
        sessions=InMemoryAgentSessionRepository(root.store),
        ids=root.ids,
    )
    root.ai_agent = QuotaAgent(
        repository=MemoryQuota(clock=root.clock, nonce_factory=lambda: str(uuid4())),
        conversation=conversation,
        fallback=root.orchestrator,
    )
    return patient_app(container=root)
