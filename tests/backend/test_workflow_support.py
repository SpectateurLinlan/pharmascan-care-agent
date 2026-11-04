"""Local support/device/navigation intents never execute on preparation."""

from uuid import uuid4

import pytest


@pytest.mark.parametrize("capability,kind", [("speech.input", "device"), ("speech.playback", "device"),
    ("help.open", "navigate"), ("guide.start", "navigate")])
def test_support_prepares_only_static_patient_actions(workflow, capability, kind):
    h = workflow
    task = h.start(capability)
    assert task["actions"][0]["kind"] == kind and task["result_ref"] is None
    assert task["input_fields"] == {}


def test_navigation_only_accepts_native_routes_and_owned_typed_query_targets(workflow):
    from .test_workflow_medication_management import active_plan

    h = workflow
    med = active_plan(h)
    task = h.start("navigation.open", {"destination": {"kind": "navigate", "route": "medicine-detail"},
                                      "regimen_id": med["regimen_id"]})
    assert task["visible_fields"]["navigation_query"] == {"id": med["regimen_id"]}
    assert task["actions"] == [{"kind": "navigate", "route": "medicine-detail"}]
    with pytest.raises(AssertionError, match="404"):
        h.start("navigation.open", {"destination": {"kind": "navigate", "route": "medicine-detail"},
                                   "regimen_id": str(uuid4())})


@pytest.mark.parametrize("values", [{"destination": {"kind": "navigate", "route": "https://example.invalid"}},
    {"destination": {"kind": "navigate", "route": "today", "url": "DEMO-untrusted"}},
    {"url": "https://example.invalid"}, {"query": {"patient_id": "DEMO-other-owner"}}])
def test_navigation_rejects_arbitrary_urls_query_and_identity_fields(workflow, values):
    h = workflow
    response = h.client.post("/api/agent/workflows/tasks", params={"client_id": "DEMO-workflow-A"}, json={
        "capability_id": "navigation.open", "workspace_id": h.workspace_id, "client_event_id": str(uuid4()),
        "save_mode": "allowed", "values": values})
    assert response.status_code == 422


ENTRIES = [("conversation.list", "show my conversations", "查看我的会话"),
    ("conversation.view", "view a conversation", "查看某个会话"),
    ("conversation.resume", "resume a conversation", "恢复会话"),
    ("conversation.new", "start a new conversation", "开始新会话"),
    ("conversation.clear", "clear chat history", "清除聊天记录"),
    ("assistant.usage", "show assistant usage", "查看助手用量"),
    ("speech.input", "use voice input", "使用语音输入"),
    ("speech.playback", "read text aloud", "朗读文字"),
    ("feedback.submit", "send app feedback", "提交应用反馈"),
    ("help.open", "open help", "打开帮助"), ("guide.start", "start app guide", "开始应用导览"),
    ("navigation.open", "open an app page", "打开应用页面")]


@pytest.mark.parametrize("capability,text", [(cap, text) for cap, en, zh in ENTRIES for text in (en, zh)])
def test_bilingual_support_entries(workflow, capability, text):
    result = workflow._request("POST", "/api/agent/workflows/messages", json={"text": text,
        "workspace_id": workflow.workspace_id, "client_turn_id": str(uuid4())})
    assert result["workflow"]["capability_id"] == capability
