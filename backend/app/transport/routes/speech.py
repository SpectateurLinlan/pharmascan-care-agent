"""Authenticated speech I/O only; transcript submission remains an explicit action."""

from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ...contracts.speech import TranscriptDTO
from ...domain.errors import ProviderUnavailableError, ValidationError
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal

router = APIRouter(prefix="/api/speech", tags=["speech"])


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=150)
    provider: Literal["tencent"]
    consent: bool
    language: Literal["en", "zh"] = "en"


@router.get("/capabilities")
def capabilities(request: Request, principal: AuthenticatedPrincipal = Depends(get_principal)) -> dict[str, object]:
    service = request.app.state.container.speech
    return {
        "available": service is not None and service.available,
        "provider": "browser",
        "cloud_tts_allowed": service is not None and service.available and service.active_tts,
        "stt_provider": "tencent" if service is not None and service.active_stt else "browser",
        "standalone_stt_active": service is not None and service.active_stt,
        "review_required": True,
        "raw_audio_retained": False,
    }


@router.post("/transcribe", response_model=TranscriptDTO)
async def transcribe(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
) -> TranscriptDTO:
    if request.headers.get("content-type", "").split(";")[0] != "audio/wav":
        raise ValidationError("Voice uploads must use audio/wav")
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 960_044:
            raise ValidationError("Voice upload exceeds 30-second size limit")
    if container.speech is None:
        raise ProviderUnavailableError("Speech service is unavailable")
    # Provider I/O is synchronous; keep it off the ASGI event loop.
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(
        container.speech.transcribe, bytes(content), consent=request.headers.get("x-speech-consent") == "true"
    )


@router.post("/synthesize")
def synthesize(
    payload: SpeechRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
) -> Response:
    if container.speech is None:
        raise ProviderUnavailableError("Speech service is unavailable")
    language = (
        container.preferences.get(principal.patient_id).preferred_language
        if container.preferences
        else payload.language
    )
    audio = container.speech.synthesize(payload.text, consent=payload.consent, language=language)
    return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})
