"""Bounded, ephemeral speech calls, with no autonomous medication actions."""

from collections import deque
from threading import Lock
from typing import Literal

from ..contracts.ports import Clock
from ..contracts.speech import SpeechPort, TranscriptDTO
from ..domain.errors import ProviderUnavailableError, ValidationError


class SpeechService:
    def __init__(
        self,
        *,
        provider: SpeechPort,
        clock: Clock,
        available: bool = False,
        active_stt: bool = True,
        active_tts: bool = False,
    ) -> None:
        self._provider, self._clock = provider, clock
        self.active_tts = active_tts
        self.active_stt = active_stt
        self.available = available
        self._calls: deque[float] = deque()
        self._lock = Lock()

    def _budget(self, consent: bool) -> None:
        if not consent:
            raise ValidationError("Explicit consent is required before sending speech to a provider")
        with self._lock:
            now = self._clock.now().timestamp()
            while self._calls and self._calls[0] <= now - 60:
                self._calls.popleft()
            if len(self._calls) >= 20:
                raise ProviderUnavailableError("Voice request limit reached; use text for now")
            self._calls.append(now)

    def transcribe(self, audio: bytes, *, consent: bool) -> TranscriptDTO:
        if not self.active_stt:
            raise ProviderUnavailableError("Browser speech recognition is active; standalone transcription is inactive")
        self._budget(consent)
        return self._provider.transcribe(audio)

    def synthesize(self, text: str, *, consent: bool, language: Literal["en", "zh"] = "en") -> bytes:
        if not self.active_tts:
            raise ProviderUnavailableError("Cloud TTS is disabled; use browser speech or visible text")
        self._budget(consent)
        return self._provider.synthesize(text, language=language)
