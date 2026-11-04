"""SIMULATED SDK edge cases; never labelled real provider acceptance."""

from types import SimpleNamespace

import httpx
import pytest
from app.contracts.model import ModelProviderError
from app.infrastructure.gemini_model import GeminiModel, bounded_retry_response, gemini_http_options
from google import genai
from google.genai import errors, types


class Client:
    def __init__(self, output=None, failure=None):
        self.interactions = self
        self.output, self.failure, self.calls = output, failure, []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure:
            raise self.failure
        return self.output


def test_sdk_uses_stateless_low_thinking_and_preserves_call_id():
    step = SimpleNamespace(
        model_dump=lambda **_: {"type": "function_call", "name": "get_dose_status", "id": "call-123", "arguments": {}}
    )
    client = Client(SimpleNamespace(steps=[step], output_text=""))
    model = GeminiModel(model="gemini-3.5-flash-lite", client_factory=lambda: client)
    result = model.create(history=[{"type": "user_input", "content": []}], tools=[], instruction="Bounded safety")
    assert result.calls[0].id == "call-123"
    request = client.calls[0]
    assert request["model"] == "gemini-3.5-flash-lite" and request["store"] is False
    assert request["generation_config"]["thinking_level"] == "low"
    assert "previous_interaction_id" not in request
    assert all(key not in request["generation_config"] for key in ["temperature", "top_p", "top_k"])


def test_actual_usage_returned_model_and_remaining_timeout():
    from uuid import uuid4

    from app.application.agent_execution import AgentExecutionService
    from app.contracts.agent_execution import execution_step
    from app.infrastructure.memory_agent_runs import MemoryRunRepository
    from app.infrastructure.memory_workflows import MemoryWorkflowState

    now = [0.0]
    service = AgentExecutionService(MemoryRunRepository(MemoryWorkflowState()), monotonic=lambda: now[0])
    owner, run = uuid4(), uuid4()
    client = Client(
        SimpleNamespace(
            steps=[],
            output_text="",
            model="gemini-returned",
            usage=SimpleNamespace(
                total_input_tokens=9, total_output_tokens=3, total_tokens=12, total_cached_tokens=None
            ),
        )
    )
    model = GeminiModel(model="gemini-configured", client_factory=lambda: client)
    service.start(owner, run)

    def work():
        now[0] = 42
        with execution_step("model"):
            return model.create(history=[], tools=[], instruction="DEMO instructions")

    reply = service.execute(owner, run, work)
    assert client.calls[0]["timeout"] == 3
    assert reply.usage.total_tokens == 12
    assert reply.usage.cached_input_tokens is None
    assert reply.returned_model == "gemini-returned"
    assert service.read(owner, run).metadata.usage.total_tokens == 12


def test_real_sdk_retry_counts_are_separate_and_each_attempt_rechecks_budget():
    from uuid import uuid4

    from app.application.agent_execution import AgentExecutionService
    from app.infrastructure.memory_agent_runs import MemoryRunRepository
    from app.infrastructure.memory_workflows import MemoryWorkflowState

    now, timeouts = [0.0], []
    service = AgentExecutionService(MemoryRunRepository(MemoryWorkflowState()), monotonic=lambda: now[0])
    owner, run = uuid4(), uuid4()

    def respond(request):
        timeouts.append(request.extensions["timeout"]["read"])
        if len(timeouts) == 1:
            now[0] = 42
            return httpx.Response(503, json={"error": {"message": "DEMO unavailable"}})
        return httpx.Response(
            200,
            json={
                "id": "DEMO",
                "status": "completed",
                "model": "gemini-returned",
                "steps": [],
                "usage": {"total_input_tokens": 9, "total_output_tokens": 3, "total_tokens": 12},
            },
        )

    options = gemini_http_options()
    options["base_url"] = "https://sdk.example.invalid"
    options["client_args"] = {**options["client_args"], "transport": httpx.MockTransport(respond)}
    model = GeminiModel(
        model="gemini-configured", client_factory=lambda: genai.Client(api_key="DEMO", http_options=options)
    )
    service.start(owner, run)
    service.execute(owner, run, lambda: model.create(history=[], tools=[], instruction="DEMO"))
    metadata = service.read(owner, run).metadata
    assert timeouts == [12, 3]
    assert metadata.model_requests == 1 and metadata.sdk_attempts == 2 and metadata.sdk_retries == 1
    assert metadata.provider == "gemini" and metadata.returned_model == "gemini-returned"
    assert metadata.usage.total_tokens == 12 and metadata.usage.cached_input_tokens is None
    assert metadata.instruction_hash and metadata.schema_hash


@pytest.mark.parametrize(
    "failure,category",
    [
        (errors.ClientError(429, {"error": {"message": "PRIVATE_PROVIDER_DETAIL"}}), "quota"),
        (httpx.ReadTimeout("PRIVATE_PROVIDER_DETAIL"), "timeout"),
        (errors.ServerError(503, {"error": {"message": "PRIVATE_PROVIDER_DETAIL"}}), "unavailable"),
    ],
)
def test_provider_failures_are_categorized_and_scrubbed(failure, category):
    client = Client(failure=failure)
    model = GeminiModel(model="gemini-3.5-flash-lite", client_factory=lambda: client)
    with pytest.raises(ModelProviderError) as raised:
        model.create(history=[], tools=[], instruction="safe")
    assert raised.value.category == category
    assert "PRIVATE_PROVIDER_DETAIL" not in str(raised.value)
    assert len(client.calls) == 1


def test_malformed_function_call_is_not_executable():
    step = SimpleNamespace(
        model_dump=lambda **_: {
            "type": "function_call",
            "name": "get_dose_status",
            "id": "bad",
            "arguments": "not an object",
        }
    )
    client = Client(SimpleNamespace(steps=[step], output_text=""))
    with pytest.raises(ModelProviderError) as raised:
        GeminiModel(model="gemini-3.5-flash-lite", client_factory=lambda: client).create(
            history=[], tools=[], instruction="safe"
        )
    assert raised.value.category == "schema"


def test_schema_refusal_keeps_actual_sdk_usage_and_returned_model():
    from uuid import uuid4

    from app.application.agent_execution import AgentExecutionService
    from app.infrastructure.memory_agent_runs import MemoryRunRepository
    from app.infrastructure.memory_workflows import MemoryWorkflowState

    step = SimpleNamespace(
        model_dump=lambda **_: {
            "type": "function_call",
            "name": "get_dose_status",
            "id": "DEMO",
            "arguments": "invalid",
        }
    )
    client = Client(
        SimpleNamespace(
            steps=[step],
            output_text="",
            model="gemini-returned",
            usage=SimpleNamespace(
                total_input_tokens=2, total_output_tokens=1, total_tokens=3, total_cached_tokens=None
            ),
        )
    )
    service = AgentExecutionService(MemoryRunRepository(MemoryWorkflowState()))
    owner, run = uuid4(), uuid4()
    service.start(owner, run)
    with pytest.raises(ModelProviderError):
        service.execute(
            owner,
            run,
            lambda: GeminiModel(model="gemini-demo", client_factory=lambda: client).create(
                history=[], tools=[], instruction="DEMO"
            ),
        )
    metadata = service.read(owner, run).metadata
    assert metadata.usage is not None, "Actual usage was lost during content refusal"
    assert metadata.usage.total_tokens == 3 and metadata.returned_model == "gemini-returned"
    assert metadata.usage_responses == 1


def test_non_provider_programming_failure_is_not_silently_downgraded():
    client = Client(failure=RuntimeError("local implementation failure"))
    with pytest.raises(RuntimeError, match="local implementation failure"):
        GeminiModel(model="gemini-3.5-flash-lite", client_factory=lambda: client).create(
            history=[], tools=[], instruction="Synthetic adapter test"
        )


@pytest.mark.parametrize("recover", [True, False])
def test_sdk_owns_one_bounded_503_retry_without_replaying_tools(recover, caplog):
    requests = []

    def respond(request):
        requests.append(request.content)
        if recover and len(requests) == 2:
            return httpx.Response(200, json={"id": "DEMO-interaction", "status": "completed", "steps": []})
        return httpx.Response(503, json={"error": {"message": "PRIVATE_PROVIDER_DETAIL"}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        options = {**gemini_http_options(), "httpx_client": http, "base_url": "https://sdk.example.invalid"}
        model = GeminiModel(
            model="gemini-3.5-flash-lite", client_factory=lambda: genai.Client(api_key="DEMO-key", http_options=options)
        )
        if recover:
            result = model.create(history=[], tools=[], instruction="DEMO")
            assert result.calls == []
        else:
            with pytest.raises(ModelProviderError) as error:
                model.create(history=[], tools=[], instruction="DEMO")
            assert error.value.category == "unavailable"
        assert len(requests) == 2 and requests[0] == requests[1]
        assert "PRIVATE_PROVIDER_DETAIL" not in caplog.text
        assert options["timeout"] == 12000 and options["retry_options"]["attempts"] == 1


@pytest.mark.parametrize(
    "headers",
    [
        {"Retry-After": "120"},
        {"retry-after-ms": "120000"},
        {"Date": "Mon, 19 Oct 2026 00:00:00 GMT", "Retry-After": "Mon, 19 Oct 2026 00:02:00 GMT"},
    ],
)
def test_real_sdk_defers_long_cooldown_without_sleeping_or_retrying(headers):
    calls = []

    def respond(request):
        calls.append(request.method)
        return httpx.Response(503, headers=headers, json={"error": {"message": "PRIVATE"}})

    options = gemini_http_options()
    options["base_url"] = "https://sdk.example.invalid"
    options["client_args"] = {**options["client_args"], "transport": httpx.MockTransport(respond)}
    model = GeminiModel(
        model="gemini-3.5-flash-lite",
        client_factory=lambda: genai.Client(api_key="DEMO-only", http_options=options),
    )
    with pytest.raises(ModelProviderError) as error:
        model.create(history=[], tools=[], instruction="DEMO retry deadline")
    assert error.value.category == "unavailable"
    assert calls == ["POST"]


def test_short_cooldown_is_left_to_sdk_without_overriding_server_backoff():
    bounded_retry_response(httpx.Response(503, headers={"Retry-After": "1"}))


@pytest.mark.parametrize("status,category", [(429, "quota"), (503, "unavailable"), (None, "timeout")])
def test_real_interactions_sdk_exceptions_are_scrubbed(status, category):
    calls = []

    def respond(request):
        calls.append(request.method)
        if status is None:
            raise httpx.ReadTimeout("PRIVATE_PROVIDER_DETAIL", request=request)
        return httpx.Response(status, json={"error": {"message": "PRIVATE_PROVIDER_DETAIL", "code": status}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        model = GeminiModel(
            model="gemini-3.5-flash-lite",
            client_factory=lambda: genai.Client(
                api_key="DEMO-not-a-real-key",
                http_options=types.HttpOptions(
                    httpx_client=http,
                    base_url="https://sdk.example.invalid",
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            ),
        )
        with pytest.raises(ModelProviderError) as raised:
            model.create(history=[], tools=[], instruction="Synthetic adapter failure test")
        assert raised.value.category == category
        assert "PRIVATE_PROVIDER_DETAIL" not in str(raised.value)
        # The pinned Interactions SDK retries a retryable HTTP response once;
        # a timeout from this injected transport is not retried.
        assert calls == (["POST"] if status is None else ["POST", "POST"])
