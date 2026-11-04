"""Official Google GenAI Interactions adapter; no retained Google conversation."""

import json
import logging
from collections.abc import Callable
from email.utils import parsedate_to_datetime

import httpx
from google import genai
from google.genai import errors
from pydantic import ValidationError

from ..contracts.agent_execution import ProviderUsage, bounded_timeout, current_execution, tracked_step
from ..contracts.model import FunctionCall, ModelProviderError, ModelReply

LOGGER = logging.getLogger(__name__)


def bounded_request(request: httpx.Request) -> None:
    if control := current_execution.get():
        control.sdk_attempt()
        remaining = control.remaining(12)
        request.extensions["timeout"] = {
            key: min(value, remaining) if value is not None else remaining
            for key, value in request.extensions.get(
                "timeout",
                {
                    "connect": 12,
                    "read": 12,
                    "write": 12,
                    "pool": 12,
                },
            ).items()
        }


def bounded_retry_response(response: httpx.Response) -> None:
    """Honor a long server cooldown by deferring, never sleeping past the UI budget.

    SDK attempt-count retry ignores max_delay for Retry-After headers. Raising a
    domain error in the public HTTP hook is not a transport error and is not retried.
    HTTP-date delays use the server Date header, not a guessed patient clock.
    """
    if response.status_code not in {429, 502, 503, 504}:
        return
    header = response.headers.get("retry-after")
    milliseconds = response.headers.get("retry-after-ms")
    if not header and not milliseconds:
        return
    try:
        if milliseconds:
            delay = float(milliseconds) / 1000
        elif header and header.isdigit():
            delay = float(header)
        elif header and response.headers.get("date"):
            delay = (parsedate_to_datetime(header) - parsedate_to_datetime(response.headers["date"])).total_seconds()
        else:
            delay = float("inf")
    except (ValueError, TypeError, OverflowError):
        delay = float("inf")
    if not 0 <= delay <= 2:
        LOGGER.warning("Gemini server cooldown deferred status=%s", response.status_code)
        raise ModelProviderError("quota" if response.status_code == 429 else "unavailable")


def gemini_http_options() -> dict:
    """One SDK-owned retry, never an orchestration/tool replay.

    Pinned Interactions maps attempts=1 to one retry (two HTTP attempts).
    """
    return {
        "api_version": "v1",
        "timeout": 12000,
        "client_args": {"event_hooks": {"request": [bounded_request], "response": [bounded_retry_response]}},
        "retry_options": {
            "attempts": 1,
            "initial_delay": 0.75,
            "max_delay": 2,
            "exp_base": 2,
            "jitter": 0.2,
            "http_status_codes": [429, 502, 503, 504],
        },
    }


class GeminiModel:
    def __init__(self, *, model: str, client_factory: Callable[[], genai.Client]):
        self.model, self._factory = model, client_factory

    @tracked_step("model")
    def create(
        self, *, history: list[dict[str, object]], tools: list[dict[str, object]], instruction: str
    ) -> ModelReply:
        control = current_execution.get()
        if control:
            control.model_started(self.model, instruction, tools)
        try:
            with self._factory() as client:
                result = client.interactions.create(
                    model=self.model,
                    input=history,
                    tools=tools,
                    system_instruction=instruction,
                    store=False,
                    generation_config={"thinking_level": "low", "max_output_tokens": 1024},
                    timeout=bounded_timeout(12),
                )
                sdk_usage = getattr(result, "usage", None)
                usage = (
                    ProviderUsage(
                        input_tokens=getattr(sdk_usage, "total_input_tokens", None),
                        output_tokens=getattr(sdk_usage, "total_output_tokens", None),
                        total_tokens=getattr(sdk_usage, "total_tokens", None),
                        cached_input_tokens=getattr(sdk_usage, "total_cached_tokens", None),
                    )
                    if sdk_usage is not None
                    else None
                )
                from ..application.agent_runtime_metadata import model_name

                returned_model = model_name(getattr(result, "model", None))
                if control:
                    control.model_returned(returned_model, usage)
                replay = [step.model_dump(mode="json", exclude_none=True) for step in result.steps]
                calls = [
                    FunctionCall.model_validate(
                        {"id": step["id"], "name": step["name"], "arguments": step["arguments"]}
                    )
                    for step in replay
                    if step.get("type") == "function_call"
                ]
                if len(json.dumps(replay)) > 30000:
                    raise ModelProviderError("schema")
                return ModelReply(
                    text=result.output_text or "",
                    calls=calls,
                    replay=replay,
                    usage=usage,
                    returned_model=returned_model,
                )
        except errors.APIError as exc:
            LOGGER.warning("Gemini request failed model=%s status=%s", self.model, exc.code)
            category = "quota" if exc.code == 429 else "unavailable"
            headers = getattr(getattr(exc, "response", None), "headers", {})
            retry = headers.get("Retry-After", "") if headers else ""
            seconds = int(retry) if isinstance(retry, str) and retry.isdigit() and int(retry) <= 3600 else None
            # Never expose provider Message, URL, response body or credentials.
            raise ModelProviderError(category, seconds) from None
        except (httpx.TimeoutException, TimeoutError):
            LOGGER.warning("Gemini request failed model=%s category=timeout", self.model)
            raise ModelProviderError("timeout") from None
        except (httpx.NetworkError, OSError):
            LOGGER.warning("Gemini request failed model=%s category=network", self.model)
            raise ModelProviderError("unavailable") from None
        except (ValidationError, KeyError, TypeError, AttributeError, ValueError):
            raise ModelProviderError("schema") from None
        except Exception as exc:
            # Interactions in pinned google-genai 2.30.1 raises a separate SDK
            # exception hierarchy not exported by google.genai.errors. Normalize
            # it here without importing SDK-private modules or leaking bodies.
            if not type(exc).__module__.startswith("google.genai."):
                raise
            timeout = any(base.__name__ == "APITimeoutError" for base in type(exc).__mro__)
            status = getattr(exc, "status_code", None)
            LOGGER.warning("Gemini request failed model=%s status=%s timeout=%s", self.model, status, timeout)
            category = "timeout" if timeout else "quota" if status == 429 else "unavailable"
            raise ModelProviderError(category) from None


def build_gemini_model(*, key: str, model: str) -> GeminiModel:
    return GeminiModel(
        model=model,
        client_factory=lambda: genai.Client(api_key=key, http_options=gemini_http_options()),
    )
