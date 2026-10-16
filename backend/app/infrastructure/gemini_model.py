"""Official Google GenAI Interactions adapter; no retained Google conversation."""

import json
from collections.abc import Callable

import httpx
from google import genai
from google.genai import errors
from pydantic import ValidationError

from ..contracts.model import FunctionCall, ModelProviderError, ModelReply


class GeminiModel:
    def __init__(self, *, model: str, client_factory: Callable[[], genai.Client]):
        self.model, self._factory = model, client_factory

    def create(
        self, *, history: list[dict[str, object]], tools: list[dict[str, object]], instruction: str
    ) -> ModelReply:
        try:
            with self._factory() as client:
                result = client.interactions.create(
                    model=self.model,
                    input=history,
                    tools=tools,
                    system_instruction=instruction,
                    store=False,
                    generation_config={"thinking_level": "low", "max_output_tokens": 1024},
                    timeout=20,
                )
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
                return ModelReply(text=result.output_text or "", calls=calls, replay=replay)
        except errors.APIError as exc:
            category = "quota" if exc.code == 429 else "unavailable"
            headers = getattr(getattr(exc, "response", None), "headers", {})
            retry = headers.get("Retry-After", "") if headers else ""
            seconds = int(retry) if isinstance(retry, str) and retry.isdigit() and int(retry) <= 3600 else None
            # Never expose provider Message, URL, response body or credentials.
            raise ModelProviderError(category, seconds) from None
        except (httpx.TimeoutException, TimeoutError):
            raise ModelProviderError("timeout") from None
        except (httpx.NetworkError, OSError):
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
            category = "timeout" if timeout else "quota" if status == 429 else "unavailable"
            raise ModelProviderError(category) from None


def build_gemini_model(*, key: str, model: str) -> GeminiModel:
    return GeminiModel(
        model=model,
        client_factory=lambda: genai.Client(
            api_key=key, http_options={"api_version": "v1", "timeout": 20000, "retry_options": {"attempts": 1}}
        ),
    )
