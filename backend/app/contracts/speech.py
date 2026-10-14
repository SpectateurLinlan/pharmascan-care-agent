"""Speech is an input/output capability; it has no medication write authority."""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict


class TranscriptDTO(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    text: str
    provider: Literal["tencent"] = "tencent"
    request_id: str
    confidence: None = None  # SentenceRecognition does not declare confidence.
    review_required: Literal[True] = True


class SpeechPort(Protocol):
    def transcribe(self, audio: bytes) -> TranscriptDTO: ...
    def synthesize(self, text: str, *, language: Literal["en", "zh"] = "en") -> bytes: ...
