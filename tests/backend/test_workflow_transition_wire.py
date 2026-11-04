"""Recording transport only: not real SQL, RLS or device evidence."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from app.contracts.dto import AgentSessionDTO
from app.contracts.workflow_conversation_transactions import ConversationTransition
from app.contracts.workflow_notification_transactions import NotificationTransition
from app.domain.errors import AuthenticationRequiredError, ProviderUnavailableError
from app.infrastructure.supabase_data import SupabaseDataClient
from app.infrastructure.workflow_conversation_transactions import SupabaseConversationTransitions
from app.infrastructure.workflow_notification_transactions import SupabaseNotificationTransitions


def wire(owner, response):
    calls = []

    def reply(request):
        calls.append(request)
        if isinstance(response, Exception):
            raise response
        return httpx.Response(200, json=response)

    data = SupabaseDataClient(
        base_url="https://demo.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-current-patient",
        patient_id=owner,
        client=httpx.Client(transport=httpx.MockTransport(reply)),
    )
    return data, calls


def command(capability="conversation.new", **kwargs):
    return ConversationTransition(
        task_id=uuid4(),
        revision=2,
        capability_id=capability,
        action_key=uuid4(),
        session_id=uuid4(),
        confirmed=True,
        **kwargs,
    )


def native_session(owner, cmd):
    now = datetime(2026, 10, 30, tzinfo=UTC)
    return AgentSessionDTO(
        id=cmd.session_id,
        patient_id=owner,
        intent=None,
        state="collecting",
        updated_at=now,
        expires_at=now + timedelta(hours=2),
        conversation_id=cmd.target,
    )


@pytest.mark.parametrize("capability", ["conversation.new", "conversation.resume", "conversation.clear"])
def test_conversation_wire_is_fixed_owned_and_uses_actual_native_result(capability):
    owner = uuid4()
    cmd = command(capability, target=uuid4() if capability == "conversation.resume" else None)
    native = native_session(owner, cmd) if capability != "conversation.clear" else None
    data, calls = wire(owner, {"session": native.model_dump(mode="json") if native else None})
    result = SupabaseConversationTransitions(data).execute(owner, cmd)
    assert result.session == native
    assert len(calls) == 1 and calls[0].url.path == "/rest/v1/rpc/assistant_conversation_transition"
    assert calls[0].headers["Authorization"] == "Bearer DEMO-current-patient"
    assert "patient_id" not in json.loads(calls[0].content)["p_command"]
    with pytest.raises(AuthenticationRequiredError):
        SupabaseConversationTransitions(data).execute(uuid4(), cmd)
    assert len(calls) == 1


@pytest.mark.parametrize("wrong", ["owner", "session", "conversation", "missing"])
def test_conversation_wire_rejects_unbound_or_missing_native_result(wrong):
    owner = uuid4()
    cmd = command("conversation.resume", target=uuid4())
    native = native_session(owner, cmd)
    if wrong == "owner":
        native = native.model_copy(update={"patient_id": uuid4()})
    if wrong == "session":
        native = native.model_copy(update={"id": uuid4()})
    if wrong == "conversation":
        native = native.model_copy(update={"conversation_id": uuid4()})
    data, _ = wire(owner, {"session": None if wrong == "missing" else native.model_dump(mode="json")})
    with pytest.raises(ProviderUnavailableError):
        SupabaseConversationTransitions(data).execute(owner, cmd)


def test_native_transition_timeout_never_retries_a_mutation():
    owner = uuid4()
    data, calls = wire(owner, httpx.ReadTimeout("DEMO outcome unknown"))
    with pytest.raises(ProviderUnavailableError):
        SupabaseConversationTransitions(data).execute(owner, command())
    assert len(calls) == 1


def test_unsubscription_wire_has_no_sender_and_never_calls_a_native_callback():
    owner = uuid4()
    target = uuid4()
    data, calls = wire(owner, {"subscription": None})
    cmd = NotificationTransition(
        task_id=uuid4(),
        revision=2,
        capability_id="notification.unsubscribe",
        action_key=uuid4(),
        confirmed=True,
        subscription_id=target,
    )
    assert SupabaseNotificationTransitions(data).execute(owner, cmd) is None
    assert calls[0].url.path == "/rest/v1/rpc/assistant_notification_transition"
    assert calls[0].headers["Authorization"] == "Bearer DEMO-current-patient"
    assert json.loads(calls[0].content)["p_command"]["subscription_id"] == str(target)
    with pytest.raises(AuthenticationRequiredError):
        SupabaseNotificationTransitions(data).execute(uuid4(), cmd)
    assert len(calls) == 1


@pytest.mark.parametrize("confirmed", [False, 1, "true", None])
def test_transition_contracts_never_coerce_patient_confirmation(confirmed):
    with pytest.raises(ValueError):
        ConversationTransition(
            task_id=uuid4(),
            revision=2,
            capability_id="conversation.clear",
            action_key=uuid4(),
            session_id=uuid4(),
            confirmed=confirmed,
        )
    with pytest.raises(ValueError):
        NotificationTransition(
            task_id=uuid4(),
            revision=2,
            capability_id="notification.unsubscribe",
            action_key=uuid4(),
            subscription_id=uuid4(),
            confirmed=confirmed,
        )
