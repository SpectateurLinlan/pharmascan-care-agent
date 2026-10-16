"""SIMULATED SDK edge cases; never labelled real provider acceptance."""

from types import SimpleNamespace

import httpx
import pytest
from app.contracts.model import ModelProviderError
from app.infrastructure.gemini_model import GeminiModel
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


def test_non_provider_programming_failure_is_not_silently_downgraded():
    client = Client(failure=RuntimeError("local implementation failure"))
    with pytest.raises(RuntimeError, match="local implementation failure"):
        GeminiModel(model="gemini-3.5-flash-lite", client_factory=lambda: client).create(
            history=[], tools=[], instruction="Synthetic adapter test"
        )


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
