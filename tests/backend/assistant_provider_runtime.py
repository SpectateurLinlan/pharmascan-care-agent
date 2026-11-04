"""Explicit synthetic acceptance adapter; no environment load on import."""

import os
from contextlib import contextmanager
from time import monotonic
from uuid import uuid4

import httpx
from app.agent.conversation import ConversationService
from app.agent.model_tools import ModelTools
from app.application.agent_execution import AgentExecutionService
from app.application.agent_runtime_metadata import combine_usage
from app.application.ai_quota import QuotaAgent
from app.contracts.agent_execution import current_execution
from app.contracts.model import ModelProviderError
from app.infrastructure.gemini_model import GeminiModel, bounded_request, bounded_retry_response, gemini_http_options
from app.infrastructure.memory_agent_runs import MemoryRunRepository
from app.infrastructure.memory_quota import MemoryQuota
from app.infrastructure.memory_repos import InMemoryAgentSessionRepository
from app.infrastructure.memory_workflows import MemoryWorkflowState
from google import genai

from .assistant_acceptance import CaseResult, RunnerUnavailable, denied_reason
from .assistant_eval import ObservedRun, grade, load_suite
from .assistant_eval_runtime import clinical, execute, offline_network_guard
from .workflow_support import WorkflowHarness

ORIGIN = "https://generativelanguage.googleapis.com"


class AcceptanceTransport(httpx.BaseTransport):
    def __init__(self, limiter, delegate):
        self._limiter, self._delegate = limiter, delegate
        self.real = isinstance(delegate, httpx.HTTPTransport)

    def handle_request(self, request):
        if (
            request.url.scheme != "https"
            or request.url.host != "generativelanguage.googleapis.com"
            or request.url.port not in {None, 443}
            or request.url.userinfo
            or request.url.path != "/v1/interactions"
            or request.method != "POST"
        ):
            raise ValueError("Acceptance provider target denied")
        if len(request.content) > 65536:
            raise ValueError("Acceptance request size exceeded")
        remaining = self._limiter.remaining(12)
        request.extensions["timeout"] = {
            key: min(value, remaining) if value is not None else remaining
            for key, value in request.extensions.get("timeout", {}).items()
        }
        self._limiter.before_request(real=self.real)
        return self._delegate.handle_request(request)

    def close(self):
        self._delegate.close()


class GlobalExecution:
    """Combine the runner's suite deadline with the existing per-turn port."""

    def __init__(self, inner, limiter):
        self._inner, self._limiter = inner, limiter

    def check(self):
        self._limiter.check()
        self._inner.check()

    def remaining(self, native_timeout):
        return min(self._limiter.remaining(native_timeout), self._inner.remaining(native_timeout))

    @contextmanager
    def step(self, kind):
        self.check()
        try:
            with self._inner.step(kind):
                yield
                self.check()
        except Exception:
            self.check()
            raise

    def guarded(self, write):
        def checked():
            self.check()
            return write()

        return self._inner.guarded(checked)

    def model_started(self, *args):
        self.check()
        self._inner.model_started(*args)

    def model_returned(self, returned_model, usage):
        # The request may already have consumed resources when its deadline is
        # reached. Preserve observed usage before the enclosing step stops.
        self._limiter.record_usage(usage)
        self._inner.model_returned(returned_model, usage)

    def sdk_attempt(self):
        self.check()
        self._inner.sdk_attempt()


@contextmanager
def global_execution(limiter):
    inner = current_execution.get()
    if inner is None:
        raise ValueError("Missing per-turn execution control")
    token = current_execution.set(GlobalExecution(inner, limiter))
    try:
        yield
    finally:
        current_execution.reset(token)


class CountedModel:
    def __init__(self, model, limiter):
        self._model, self._limiter = model, limiter
        self.model = model.model
        self.usage = None
        self.returned_model = None

    def create(self, **kwargs):
        self._limiter.model_request()
        result = self._model.create(**kwargs)
        self._limiter.check()
        if result.usage is not None:
            self.usage = combine_usage(self.usage, result.usage)
        self.returned_model = result.returned_model
        return result


class InjectedFailureModel:
    model = "DEMO-injected-failure"

    def create(self, **_kwargs):
        raise ModelProviderError("unavailable")


class AcceptanceRuntime:
    def __init__(self, config, limiter, *, transport_factory=None, simulated=False):
        self.config, self.limiter = config, limiter
        self._transport_factory, self.simulated = transport_factory, simulated
        self._key = None
        self._entered = False
        self._suite = load_suite()

    def __enter__(self):
        if reason := denied_reason(self.config):
            raise RunnerUnavailable(reason)
        self.limiter.check()
        if self.config.mode == "provider-memory":
            self._key = os.environ.get(self.config.api_key_env)
            if not self._key:
                raise RunnerUnavailable("provider_key_missing")
        self._entered = True
        return self

    def __exit__(self, *_args):
        self._key = None
        self._entered = False

    def _model(self):
        def client_factory():
            delegate = (
                self._transport_factory()
                if self._transport_factory
                else httpx.HTTPTransport(retries=0, trust_env=False)
            )
            http = httpx.Client(
                transport=AcceptanceTransport(self.limiter, delegate),
                follow_redirects=False,
                trust_env=False,
                event_hooks={"request": [bounded_request], "response": [bounded_retry_response]},
            )
            options = {**gemini_http_options(), "httpx_client": http, "base_url": ORIGIN}
            options.pop("client_args", None)
            try:
                return genai.Client(api_key=self._key, vertexai=False, http_options=options)
            except Exception:
                http.close()
                raise

        return GeminiModel(model=self.config.model, client_factory=client_factory)

    def execute(self, case, limiter):
        if not self._entered:
            raise RunnerUnavailable("execution_failed")
        started = monotonic()
        if case.fixture == "tool_selection":
            if self.config.mode == "offline":
                return CaseResult(
                    case_id=case.id, status="not_run", reason="provider_evidence_missing", evidence_layer="not_run"
                )
            return self._agent(case, self._model(), injected=False)
        if case.fixture == "provider_failure":
            with offline_network_guard():
                return self._agent(case, InjectedFailureModel(), injected=True)
        selected = next(
            item for item in self._suite.cases if item.setup_fixture == case.fixture and item.language == case.language
        )
        with offline_network_guard(), WorkflowHarness(knowledge_v2_enabled=True) as h:

            def on_request(request):
                limiter.check()
                if request.method == "POST" and request.url.path.endswith("/messages"):
                    limiter.user_turn()

            h.client.event_hooks["request"].append(on_request)
            h._request(
                "PUT",
                "/api/me/preferences",
                json={"preferred_language": selected.language, "timezone": selected.timezone},
            )
            before = clinical(h.snapshot())
            values = execute(selected, h)
            unchanged = clinical(h.snapshot()) == before
            values["facts"]["clinical_unchanged"] = unchanged
            values["effects"]["clinical_writes"] = values["effects"].get("clinical_writes", 0) + int(not unchanged)
            observed = ObservedRun(case_id=selected.id, model_requests=0, **values)
        result = grade(selected, observed)
        checks = {
            "manual_enrollment": {"draft_ready": observed.facts.get("ready_for_review") is True},
            "name_confirmation": {"has_name_choice": observed.facts.get("asked_confirmation") is True},
            "photo_failure": {"original_retained": observed.facts.get("original_retained") is True},
            "native_observation": {"independent_receipt": result.task_complete and observed.receipt_count > 0},
        }[case.fixture]
        # Local deterministic/replay evidence cannot become a provider pass.
        status = result.status if self.config.mode == "offline" or result.status == "failed" else "not_run"
        return CaseResult(
            case_id=case.id,
            status=status,
            application_status=result.status,
            reason="objective_not_met"
            if status == "failed"
            else "provider_evidence_missing"
            if status == "not_run"
            else None,
            evidence_layer="local_memory",
            checks=checks,
            latency_ms=(monotonic() - started) * 1000,
        )

    def _agent(self, case, model, *, injected):
        started = monotonic()
        before_models, before_wire, before_real = (
            self.limiter.model_requests,
            self.limiter.wire_attempts,
            self.limiter.real_requests,
        )
        counted = CountedModel(model, self.limiter)
        executions = AgentExecutionService(MemoryRunRepository(MemoryWorkflowState()))
        with WorkflowHarness(knowledge_v2_enabled=True) as h:
            h.container.ai_agent = QuotaAgent(
                repository=MemoryQuota(clock=h.clock, nonce_factory=lambda: str(uuid4()), limit=20),
                conversation=ConversationService(
                    model=counted,
                    tools=ModelTools(
                        registry=h.container.registry,
                        fallback=h.container.orchestrator,
                        medication_understanding=h.container.medication_understanding,
                        clock=h.clock,
                    ),
                    fallback=h.container.orchestrator,
                    sessions=InMemoryAgentSessionRepository(h.container.store),
                    ids=h.container.ids,
                ),
                fallback=h.container.orchestrator,
            )
            session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})
            run_id = uuid4()
            executions.start(h.owner_ids["A"], run_id)
            before = clinical(h.snapshot())

            def ask():
                with global_execution(self.limiter):
                    self.limiter.user_turn()
                    return h._request(
                        "POST",
                        "/api/agent/messages",
                        json={
                            "session_id": session["session_id"],
                            "client_turn_id": str(uuid4()),
                            "text": (
                                "Inspect my active entries using the available lookup function "
                                "and report only the returned display names."
                            ),
                        },
                    )

            try:
                reply = executions.execute(h.owner_ids["A"], run_id, ask)
            except Exception:
                # A TestClient exception wrapper must not hide a runner stop.
                self.limiter.check()
                if self.limiter.wire_attempts >= self.limiter.budget.max_requests and not injected:
                    from .assistant_acceptance import RunnerStopped

                    raise RunnerStopped("request_limit") from None
                raise
            unchanged = clinical(h.snapshot()) == before
            selected = len(reply["tool_traces"]) == 1 and all(
                row["tool_name"] == "list_active_medications" and row["status"] == "success"
                for row in reply["tool_traces"]
            )
            model_success = (
                not injected
                and not self.simulated
                and self.limiter.real_requests > before_real
                and reply["mode"] == "gemini"
                and counted.returned_model is not None
            )
            if injected:
                checks = {"fallback_honest": reply["mode"] != "gemini", "clinical_unchanged": unchanged}
                status = "degraded" if all(checks.values()) else "failed"
            else:
                checks = {"tool_selected": selected, "clinical_unchanged": unchanged}
                status = "failed" if not all(checks.values()) else "passed" if model_success else "not_run"
            return CaseResult(
                case_id=case.id,
                status=status,
                reason="objective_not_met"
                if status == "failed"
                else "provider_evidence_missing"
                if status in {"degraded", "not_run"}
                else None,
                evidence_layer="fault_injection"
                if injected
                else "provider_memory"
                if model_success
                else "recording_port",
                model_success=model_success,
                checks=checks,
                model_requests=self.limiter.model_requests - before_models,
                wire_attempts=self.limiter.wire_attempts - before_wire,
                real_requests=self.limiter.real_requests - before_real,
                returned_model=counted.returned_model,
                usage=counted.usage,
                latency_ms=(monotonic() - started) * 1000,
            )
