"""Local typed boundaries; live ownership is tested separately."""

from app.transport.app_factory import create_app
from app.transport.container import build_container
from fastapi.testclient import TestClient


def test_preferences_survive_request_and_are_owned_not_llm_identity():
    client = TestClient(create_app(build_container()))
    a = "/api/me/preferences?client_id=DEMO-A"
    b = "/api/me/preferences?client_id=DEMO-B"
    result = client.put(a, json={"preferred_language": "zh", "text_size": "large", "reminder_lead_minutes": 15})
    assert result.status_code == 200
    assert result.json()["speech_locale"] == "zh-CN"
    assert client.get(a).json()["text_size"] == "large"
    assert client.get(b).json()["preferred_language"] == "en"
    assert client.get(b).json()["speech_locale"] == "en-SG"
    assert client.put(a, json={"patient_id": result.json()["patient_id"]}).status_code == 422
    assert client.put(a, json={"reminder_lead_minutes": -1}).status_code == 422
    assert client.put(a, json={"speech_locale": "en-SG"}).status_code == 422


def test_numeric_font_preference_persists_is_owned_and_rejects_invalid_scales():
    client = TestClient(create_app(build_container()))
    a = "/api/me/preferences?client_id=DEMO-font-A"
    b = "/api/me/preferences?client_id=DEMO-font-B"
    assert client.put(a, json={"text_scale_percent": 133}).status_code == 200
    assert client.get(a).json()["text_scale_percent"] == 133
    assert client.get(a).json()["text_size"] == "large"
    assert client.get(b).json()["text_scale_percent"] == 100
    for value in [99, 151, True, 120.5, "130"]:
        assert client.put(a, json={"text_scale_percent": value}).status_code == 422
    assert client.get(a).json()["text_scale_percent"] == 133
    assert client.put(a, json={"text_size": "standard"}).json()["text_scale_percent"] == 100
    assert client.put(a, json={"text_size": "large"}).json()["text_scale_percent"] == 125
