"""Opt-in loopback DEMO_ONLY progress runtime; zero actual provider requests."""

from time import sleep
from uuid import uuid4

from app.agent.conversation import ConversationService
from app.agent.model_tools import ModelTools
from app.application.ai_quota import QuotaAgent
from app.contracts.agent_execution import bounded_timeout
from app.contracts.model import FunctionCall, ModelReply
from app.infrastructure.memory_quota import MemoryQuota
from app.infrastructure.memory_repos import InMemoryAgentSessionRepository

from .assistant_knowledge_runtime import create_app as knowledge_app


class DemoModel:
    model = "DEMO-recording-model"

    def create(self, *, history, **_kwargs):
        sleep(bounded_timeout(1.2))
        if not any(item.get("type") == "function_result" for item in history):
            return ModelReply(calls=[FunctionCall(id="DEMO-list", name="list_active_medications", arguments={})])
        return ModelReply(text="DEMO: application records checked. No medical recommendation is generated.")


def create_app():
    app = knowledge_app(workflows_enabled=True, progress_enabled=True)
    root = app.state.container
    conversation = ConversationService(
        model=DemoModel(),
        tools=ModelTools(
            registry=root.registry,
            fallback=root.orchestrator,
            medication_understanding=root.medication_understanding,
            clock=root.clock,
        ),
        fallback=root.orchestrator,
        sessions=InMemoryAgentSessionRepository(root.store),
        ids=root.ids,
    )
    root.ai_agent = QuotaAgent(
        repository=MemoryQuota(clock=root.clock, nonce_factory=lambda: str(uuid4()), limit=20),
        conversation=conversation,
        fallback=root.orchestrator,
    )
    return app
