"""Secure account tasks never accept credentials or execute Auth operations."""

from uuid import uuid4

import pytest


@pytest.mark.parametrize("action", ["status", "login", "link", "password", "signout"])
def test_account_tasks_only_offer_the_original_secure_form(workflow, action):
    h = workflow
    task = h.start("account." + action)
    assert task["actions"] == [{"kind": "secure_account", "action": action}]
    assert task["result_ref"] is None and task["input_fields"] == {}
    with pytest.raises(AssertionError, match="422"):
        h.event(task["task_id"], "prepare_confirmation")


@pytest.mark.parametrize("field", ["email", "password", "code", "access_token", "patient_id"])
def test_account_tasks_reject_all_secret_or_identity_fields(workflow, field):
    h = workflow
    response = h.client.post("/api/agent/workflows/tasks", params={"client_id": "DEMO-workflow-A"}, json={
        "capability_id": "account.login", "workspace_id": h.workspace_id, "client_event_id": str(uuid4()),
        "save_mode": "allowed", "values": {field: "DEMO-secret-never-store"}})
    assert response.status_code == 422 and "DEMO-secret-never-store" not in str(h.snapshot())


ENTRIES = [
    ("preference.language", "change language", "修改语言"), ("preference.text", "change text size", "修改字号"),
    ("preference.voice", "change voice preferences", "修改语音偏好"),
    ("preference.reminder", "change reminder preferences", "修改提醒偏好"),
    ("preference.privacy", "change chat saving", "修改聊天保存设置"),
    ("preference.timezone", "change timezone", "修改时区"), ("profile.edit", "edit my profile", "修改个人资料"),
    ("profile.view", "show my profile", "查看个人资料"), ("caregiver.list", "show care contacts", "查看关怀联系人"),
    ("caregiver.add", "add care contact", "添加关怀联系人"), ("caregiver.edit", "edit care contact", "修改关怀联系人"),
    ("caregiver.delete", "remove care contact", "删除关怀联系人"),
    ("account.status", "show account status", "查看账户状态"), ("account.login", "sign in to my account", "登录账户"),
    ("account.link", "link my email", "关联邮箱"), ("account.password", "change my password", "修改账户密码"),
    ("account.signout", "sign out of my account", "退出账户"),
]


@pytest.mark.parametrize("capability,text", [(capability, text) for capability, en, zh in ENTRIES for text in (en, zh)])
def test_bilingual_settings_and_account_entries(workflow, capability, text):
    result = workflow._request("POST", "/api/agent/workflows/messages", json={"text": text,
        "workspace_id": workflow.workspace_id, "client_turn_id": str(uuid4())})
    assert result["workflow"]["capability_id"] == capability
