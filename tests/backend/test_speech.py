"""VERIFIED LOCAL, SIMULATED Tencent I/O. No live speech claim."""

import base64
import io
import json
import wave
from datetime import UTC, datetime

import httpx
import pytest
from app.application.speech import SpeechService
from app.domain.errors import ProviderUnavailableError, ValidationError
from app.infrastructure.memory_repos import SequentialIdGenerator
from app.infrastructure.tencent_speech import TencentRpcTransport, TencentSpeechProvider, validate_wav
from app.transport.app_factory import create_app
from app.transport.container import build_container
from fastapi.testclient import TestClient


class FixedClock:
    def now(self):
        return datetime(2026, 10, 14, tzinfo=UTC)


def synthetic_wav(seconds=1, sample_rate=16000, channels=1):
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(b"\x00\x00" * sample_rate * channels * seconds)
    return output.getvalue()


def provider(handler):
    transport = TencentRpcTransport(
        secret_id="SIMULATED-id",
        secret_key="SIMULATED-key",
        clock=FixedClock(),
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return TencentSpeechProvider(transport=transport, ids=SequentialIdGenerator(), voice_type=1001)


@pytest.mark.parametrize("language,voice,primary", [("en", 1050, 2), ("zh", 1001, 1)])
def test_selected_language_sets_standard_tts_voice_not_asr(language, voice, primary):
    def handler(request):
        payload = json.loads(request.content)
        assert request.headers["X-TC-Action"] == "TextToVoice"
        assert payload["VoiceType"] == voice and payload["PrimaryLanguage"] == primary
        return httpx.Response(
            200,
            json={
                "Response": {
                    "Audio": base64.b64encode(synthetic_wav()).decode(),
                    "SessionId": payload["SessionId"],
                    "RequestId": "DEMO",
                }
            },
        )

    transport = TencentRpcTransport(
        secret_id="SIMULATED-id",
        secret_key="SIMULATED-key",
        clock=FixedClock(),
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    speech = TencentSpeechProvider(transport=transport, ids=SequentialIdGenerator(), voice_type=1050)
    assert speech.synthesize("DEMO", language=language).startswith(b"RIFF")


@pytest.mark.parametrize(
    "utterance",
    [
        "What medicine should I take tonight?",
        "Did I already take my evening medicine?",
        "I took it.",
        "I'm not sure whether I took it.",
        "What is this pill?",
    ],
)
def test_asr_returns_reviewable_transcript_without_authority(utterance):
    def handler(request):
        payload = json.loads(request.content)
        assert payload["EngSerViceType"] == "16k_en" and payload["SourceType"] == 1
        assert "Url" not in payload and payload["DataLen"] == len(synthetic_wav())
        assert request.headers["X-TC-Action"] == "SentenceRecognition"
        return httpx.Response(
            200, json={"Response": {"Result": utterance, "AudioDuration": 1000, "RequestId": "DEMO-request"}}
        )

    transcript = provider(handler).transcribe(synthetic_wav())
    assert transcript.text == utterance and transcript.review_required and transcript.confidence is None


def test_tts_validates_session_and_real_audio_signature():
    def handler(request):
        payload = json.loads(request.content)
        assert payload["Codec"] == "wav" and payload["Text"] == "DEMO response"
        return httpx.Response(
            200,
            json={
                "Response": {
                    "Audio": base64.b64encode(synthetic_wav()).decode(),
                    "SessionId": payload["SessionId"],
                    "RequestId": "DEMO-request",
                }
            },
        )

    assert provider(handler).synthesize("DEMO response") == synthetic_wav()


@pytest.mark.parametrize(
    "audio",
    [b"html", synthetic_wav(31), synthetic_wav(sample_rate=8000), synthetic_wav(channels=2), synthetic_wav()[:-100]],
    ids=["bad-signature", "too-long", "wrong-rate", "stereo", "truncated"],
)
def test_invalid_audio_is_refused_before_provider_call(audio):
    with pytest.raises(ValidationError):
        provider(lambda _: pytest.fail("Invalid audio must never reach provider")).transcribe(audio)


@pytest.mark.parametrize(
    "status,body",
    [
        (503, {}),
        (429, {}),
        (400, {}),
        (200, {"Response": {"Error": {"Code": "SIMULATED", "Message": "private transcript"}}}),
        (200, {"Response": {"Result": 42, "AudioDuration": 1000, "RequestId": "DEMO"}}),
    ],
)
def test_provider_failure_never_becomes_a_successful_transcript(status, body):
    with pytest.raises(ProviderUnavailableError) as refused:
        provider(lambda _: httpx.Response(status, json=body)).transcribe(synthetic_wav())
    assert "private transcript" not in str(refused.value)


def test_provider_timeout_no_retry_or_secret_exception():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("SIMULATED-key")

    with pytest.raises(ProviderUnavailableError) as refused:
        provider(handler).transcribe(synthetic_wav())
    assert len(calls) == 1 and "SIMULATED-key" not in str(refused.value)


def test_international_site_uses_documented_endpoint_and_region():
    def handler(request):
        assert request.url.host == "tts.intl.tencentcloudapi.com"
        assert request.headers["X-TC-Region"] == "ap-singapore"
        return httpx.Response(200, json={"Response": {"Error": {"Code": "UnsupportedRegion"}}})

    transport = TencentRpcTransport(
        secret_id="SIMULATED-id",
        secret_key="SIMULATED-key",
        clock=FixedClock(),
        site="international",
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ProviderUnavailableError, match="UnsupportedRegion"):
        transport.call("tts", "TextToVoice", {"Text": "DEMO"})


def test_provider_error_diagnostics_do_not_expose_arbitrary_code_or_message():
    with pytest.raises(ProviderUnavailableError) as refused:
        provider(
            lambda _: httpx.Response(
                200,
                json={
                    "Response": {
                        "Error": {
                            "Code": "Bearer private token",
                            "Message": "private credential",
                        }
                    }
                },
            )
        ).transcribe(synthetic_wav())
    assert "UnknownProviderError" in str(refused.value)
    assert "private" not in str(refused.value)


def test_arbitrary_speech_site_is_rejected():
    with pytest.raises(ValidationError):
        TencentRpcTransport(secret_id="SIMULATED", secret_key="SIMULATED", clock=FixedClock(), site="untrusted.example")


def test_empty_asr_is_not_silently_submitted():
    with pytest.raises(ValidationError):
        provider(
            lambda _: httpx.Response(
                200, json={"Response": {"Result": " ", "AudioDuration": 1000, "RequestId": "DEMO"}}
            )
        ).transcribe(synthetic_wav())


def test_speech_requires_consent_and_enforces_bounded_budget():
    instance = provider(
        lambda _: httpx.Response(200, json={"Response": {"Result": "DEMO", "AudioDuration": 1000, "RequestId": "DEMO"}})
    )
    service = SpeechService(provider=instance, clock=FixedClock(), available=True)
    with pytest.raises(ValidationError):
        service.transcribe(synthetic_wav(), consent=False)
    for _ in range(20):
        service.transcribe(synthetic_wav(), consent=True)
    with pytest.raises(ProviderUnavailableError):
        service.transcribe(synthetic_wav(), consent=True)


def test_http_voice_unavailable_and_auth_failure_preserve_typed_flow():
    container = build_container()
    client = TestClient(create_app(container))
    assert client.get("/api/speech/capabilities").status_code == 401
    assert client.get("/api/speech/capabilities?client_id=DEMO").json()["available"] is False
    assert client.get("/api/speech/capabilities?client_id=DEMO").json()["stt_provider"] == "browser"
    invalid = client.post(
        "/api/speech/transcribe?client_id=DEMO", content=b"html", headers={"Content-Type": "text/html"}
    )
    assert invalid.status_code == 422
    unavailable = client.post(
        "/api/speech/transcribe?client_id=DEMO",
        content=synthetic_wav(),
        headers={"Content-Type": "audio/wav", "X-Speech-Consent": "true"},
    )
    assert unavailable.status_code == 503
    assert not container.store.events
    validate_wav(synthetic_wav())


def test_inactive_standalone_stt_does_not_call_provider():
    speech = SpeechService(
        provider=provider(lambda _: pytest.fail("Inactive ASR must not call Tencent")),
        clock=FixedClock(),
        available=True,
        active_stt=False,
    )
    with pytest.raises(ProviderUnavailableError, match="inactive"):
        speech.transcribe(synthetic_wav(), consent=True)


def test_default_tts_denies_cloud_even_with_credentials_and_consent():
    speech = SpeechService(
        provider=provider(lambda _: pytest.fail("Default TTS must not call Tencent")),
        clock=FixedClock(),
        available=True,
    )
    with pytest.raises(ProviderUnavailableError, match="disabled"):
        speech.synthesize("DEMO", consent=True)


def test_composition_defaults_cloud_tts_off_despite_legacy_approval():
    from app.config import Settings
    from app.transport.container import build_speech_service

    settings = Settings(
        database_url=None,
        supabase_url=None,
        supabase_publishable_key=None,
        supabase_secret_key=None,
        app_env="test",
        app_origin=None,
        vision_api_base_url=None,
        enable_demo_seed=False,
        persistence="in_memory",
        auth_mode="demo",
        source="test",
        enable_speech=True,
        tencent_speech_approved=True,
        tencent_secret_id="DEMO-ID",
        tencent_secret_key="DEMO-KEY",
        tencent_voice_type=1050,
    )
    service = build_speech_service(settings=settings, clock=FixedClock(), ids=SequentialIdGenerator())
    assert service.available is True
    assert service.active_tts is False
    assert service.active_stt is False
    with pytest.raises(ProviderUnavailableError, match="disabled"):
        service.synthesize("DEMO", consent=True)


def test_cloud_tts_requires_explicit_provider_and_server_permission():
    container = build_container()
    container.speech = SpeechService(
        provider=provider(
            lambda request: httpx.Response(
                200,
                json={
                    "Response": {
                        "Audio": base64.b64encode(synthetic_wav()).decode(),
                        "RequestId": "DEMO",
                        "SessionId": json.loads(request.content)["SessionId"],
                    }
                },
            )
        ),
        clock=FixedClock(),
        available=True,
        active_tts=False,
    )
    client = TestClient(create_app(container))
    payload = {"text": "DEMO", "consent": True, "language": "en"}
    assert client.post("/api/speech/synthesize?client_id=DEMO", json=payload).status_code == 422
    payload["provider"] = "tencent"
    assert client.post("/api/speech/synthesize?client_id=DEMO", json=payload).status_code == 503
    assert client.get("/api/speech/capabilities?client_id=DEMO").json()["cloud_tts_allowed"] is False
    container.speech.active_tts = True
    assert client.post("/api/speech/synthesize?client_id=DEMO", json=payload).status_code == 200
    assert not container.store.events
