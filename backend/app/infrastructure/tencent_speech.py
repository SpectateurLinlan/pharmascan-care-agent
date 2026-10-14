"""Bounded Tencent SentenceRecognition/TextToVoice adapter.

Contract: official TencentCloud Python ASR v20190614 and TTS v20190823 models.
Live availability depends on the account's activation for each speech product.
No provider response, audio, text, signing material or token is logged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import re
import wave
from collections.abc import Callable
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as SchemaError

from ..contracts.ports import Clock, IdGenerator
from ..contracts.speech import TranscriptDTO
from ..domain.errors import ProviderUnavailableError, ValidationError


def validate_wav(audio: bytes) -> None:
    if not 44 < len(audio) <= 960_044:
        raise ValidationError("Audio must be a bounded WAV recording of up to 30 seconds")
    try:
        with wave.open(io.BytesIO(audio), "rb") as reader:
            if (reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getcomptype()) != (
                1,
                2,
                16000,
                "NONE",
            ):
                raise ValidationError("Use mono 16-bit 16kHz PCM WAV audio")
            frames = reader.getnframes()
            if not 0 < frames <= 480_000 or len(reader.readframes(frames)) != frames * 2:
                raise ValidationError("Invalid or excessive WAV duration")
    except (wave.Error, EOFError):
        raise ValidationError("Invalid WAV content signature") from None


class TencentRpcTransport:
    """TC3 signing over fixed service/action allowlists; no automatic retries."""

    def __init__(
        self,
        *,
        secret_id: str,
        secret_key: str,
        clock: Clock,
        site: str = "domestic",
        client_factory: Callable[[], httpx.Client] = httpx.Client,
    ) -> None:
        self._secret_id, self._secret_key = secret_id, secret_key
        self._clock, self._client_factory = clock, client_factory
        if site not in {"domestic", "international"}:
            raise ValidationError("Unsupported Tencent speech site")
        self._site = site

    def call(self, service: str, action: str, payload: dict) -> dict:
        versions = {("asr", "SentenceRecognition"): "2019-06-14", ("tts", "TextToVoice"): "2019-08-23"}
        version = versions.get((service, action))
        if version is None:
            raise ValidationError("Speech operation is not allowed")
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        moment = self._clock.now()
        timestamp, date = str(int(moment.timestamp())), moment.strftime("%Y-%m-%d")
        suffix = "intl.tencentcloudapi.com" if self._site == "international" else "tencentcloudapi.com"
        host = f"{service}.{suffix}"
        canonical = (
            f"POST\n/\n\ncontent-type:application/json\nhost:{host}\n\n"
            f"content-type;host\n{hashlib.sha256(body).hexdigest()}"
        )
        scope = f"{date}/{service}/tc3_request"
        to_sign = f"TC3-HMAC-SHA256\n{timestamp}\n{scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}"

        def digest(key: bytes, message: str) -> bytes:
            return hmac.new(key, message.encode(), hashlib.sha256).digest()

        signing_key = digest(digest(digest(("TC3" + self._secret_key).encode(), date), service), "tc3_request")
        signature = hmac.new(signing_key, to_sign.encode(), hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "Host": host,
            "X-TC-Action": action,
            "X-TC-Version": version,
            "X-TC-Timestamp": timestamp,
            "X-TC-Region": "ap-singapore" if self._site == "international" else "ap-guangzhou",
            "Authorization": f"TC3-HMAC-SHA256 Credential={self._secret_id}/{scope}, "
            f"SignedHeaders=content-type;host, Signature={signature}",
        }
        try:
            with (
                self._client_factory() as client,
                client.stream(
                    "POST",
                    f"https://{host}/",
                    content=body,
                    headers=headers,
                    timeout=15,
                    follow_redirects=False,
                ) as response,
            ):
                if response.status_code >= 500 or response.status_code == 429:
                    raise ProviderUnavailableError("Speech provider temporarily unavailable")
                if response.status_code != 200 or "application/json" not in response.headers.get("content-type", ""):
                    raise ProviderUnavailableError("Speech provider rejected the request")
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 3_000_000:
                        raise ProviderUnavailableError("Speech response exceeded its size limit")
                envelope = json.loads(content)
        except (httpx.HTTPError, ValueError):
            raise ProviderUnavailableError("Speech provider request failed") from None
        if not isinstance(envelope, dict) or not isinstance(envelope.get("Response"), dict):
            raise ProviderUnavailableError("Invalid speech response envelope")
        result = envelope["Response"]
        if "Error" in result:
            error = result["Error"]
            code = error.get("Code") if isinstance(error, dict) else None
            if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9.]{0,100}", code):
                code = "UnknownProviderError"
            # Provider messages may contain submitted text or credentials. Retain
            # only the bounded documented error code for operational diagnosis.
            raise ProviderUnavailableError(f"Speech provider error ({code}); use text instead")
        return result


class AsrResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    Result: str
    RequestId: str
    AudioDuration: int


class TtsResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    Audio: str
    SessionId: str
    RequestId: str


class TencentSpeechProvider:
    def __init__(self, *, transport: TencentRpcTransport, ids: IdGenerator, voice_type: int) -> None:
        self._transport, self._ids, self._voice_type = transport, ids, voice_type

    def transcribe(self, audio: bytes) -> TranscriptDTO:
        validate_wav(audio)
        response = self._transport.call(
            "asr",
            "SentenceRecognition",
            {
                "EngSerViceType": "16k_en",
                "SourceType": 1,
                "VoiceFormat": "wav",
                "SubServiceType": 2,
                "ProjectId": 0,
                "UsrAudioKey": str(self._ids.new_id()),
                "Data": base64.b64encode(audio).decode(),
                "DataLen": len(audio),
            },
        )
        try:
            result = AsrResponse.model_validate(response)
        except SchemaError:
            raise ProviderUnavailableError("Speech transcript contract mismatch") from None
        if not result.Result.strip() or not 0 < result.AudioDuration <= 30_000:
            raise ValidationError("No usable short transcript; please repeat or type instead")
        return TranscriptDTO(text=result.Result.strip(), request_id=result.RequestId)

    def synthesize(self, text: str, *, language: Literal["en", "zh"] = "en") -> bytes:
        if not text.strip() or len(text.encode()) > 450:
            raise ValidationError("Spoken response must be short and nonempty")
        session = str(self._ids.new_id())
        response = self._transport.call(
            "tts",
            "TextToVoice",
            {
                "Text": text,
                "SessionId": session,
                "ModelType": 1,
                "VoiceType": 1001 if language == "zh" else self._voice_type,
                "PrimaryLanguage": 1 if language == "zh" else 2,
                "SampleRate": 16000,
                "Codec": "wav",
            },
        )
        try:
            result = TtsResponse.model_validate(response)
            if result.SessionId != session:
                raise ValueError("Mismatched session")
            audio = base64.b64decode(result.Audio, validate=True)
        except (SchemaError, ValueError):
            raise ProviderUnavailableError("Speech audio contract mismatch") from None
        validate_wav(audio)
        return audio


class UnavailableSpeechProvider:
    def transcribe(self, audio: bytes) -> TranscriptDTO:
        raise ProviderUnavailableError("Voice transcription is unavailable; type your message instead")

    def synthesize(self, text: str, *, language: Literal["en", "zh"] = "en") -> bytes:
        raise ProviderUnavailableError("Spoken playback is unavailable; the response remains visible")
