"""Ephemeral conversational provider port, without patient identity authority."""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ..domain.errors import ProviderUnavailableError


class FunctionCall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=80, pattern=r"^[a-z_]+$")
    arguments: dict[str, object]


class ModelReply(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    text: str = Field(default="", max_length=2000)
    calls: list[FunctionCall] = Field(default_factory=list, max_length=8)
    # Opaque stateless replay only inside one bounded turn; never persisted.
    replay: list[dict[str, object]] = Field(default_factory=list, repr=False, max_length=32)


class ModelProviderError(ProviderUnavailableError):
    def __init__(self, category: Literal["quota", "timeout", "unavailable", "schema"], retry_after: int | None = None):
        super().__init__("Conversational provider temporarily unavailable")
        self.category, self.retry_after = category, retry_after


class ConversationalModel(Protocol):
    model: str

    def create(
        self, *, history: list[dict[str, object]], tools: list[dict[str, object]], instruction: str
    ) -> ModelReply: ...
