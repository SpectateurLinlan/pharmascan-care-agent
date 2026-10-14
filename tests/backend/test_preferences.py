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
