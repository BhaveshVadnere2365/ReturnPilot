"""Provider-mocked coverage of the bounded conversation boundary."""

from __future__ import annotations

import asyncio
import logging
from functools import wraps
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.genai import errors, types

from app import conversation
from app.config import Settings
from app.domain_errors import DomainError
from app.main import app
from app.models import DemoUser
from app.security import resolve_demo_user


def run_async(test):
    @wraps(test)
    def wrapper(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))
    return wrapper


class FakeModels:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.configs = []

    async def generate_content(self, **kwargs):
        self.configs.append(kwargs["config"])
        return next(self.responses)


class FakeClient:
    def __init__(self, responses):
        self.aio = SimpleNamespace(models=FakeModels(responses))


def call(name, args):
    return SimpleNamespace(name=name, args=args)


def response(calls=()):
    return SimpleNamespace(
        function_calls=list(calls),
        candidates=[SimpleNamespace(content=types.Content(role="model", parts=[]))],
    )


def settings(**overrides):
    return Settings(_env_file=None, gemini_api_key="server-test-key", **overrides)


@pytest.fixture
def user():
    return DemoUser(id=uuid.uuid4(), display_name="Test", session_key_hash="unused")


@run_async
async def test_sequential_tools_are_allowlisted_and_ground_result(monkeypatch, user):
    invoked = []

    async def invoke(user_id, name, args):
        invoked.append((user_id, name, args))
        if name == "find_order":
            return {"matches": [{"order_id": str(uuid.uuid4()), "external_order_ref": "ORD-1", "items": []}]}
        return {"order": {"order_id": str(uuid.uuid4()), "items": []}}

    monkeypatch.setattr(conversation, "_invoke_mcp", invoke)
    client = FakeClient([response([call("find_order", {"query": "ORD-1"})]), response([call("get_order_details", {"order_id": str(uuid.uuid4())})]), response()])
    result = await conversation.handle_conversation(user, "Where is ORD-1?", settings=settings(), client=client)

    assert len(invoked) == 2
    assert all(entry[0] == user.id for entry in invoked)
    assert [entry[1] for entry in invoked] == ["find_order", "get_order_details"]
    assert "create_return_request" not in str(client.aio.models.configs[0].tools)
    assert result.status == "answered"
    assert len(result.tool_events) == 2


@run_async
async def test_ambiguous_order_gets_clarification(monkeypatch, user):
    async def invoke(*_):
        return {"matches": [
            {"order_id": str(uuid.uuid4()), "external_order_ref": "A", "items": []},
            {"order_id": str(uuid.uuid4()), "external_order_ref": "B", "items": []},
        ]}

    monkeypatch.setattr(conversation, "_invoke_mcp", invoke)
    result = await conversation.handle_conversation(user, "Find my order", settings=settings(), client=FakeClient([response([call("find_order", {"query": "mug"})]), response()]))
    assert result.status == "needs_clarification"
    assert "Which one" in result.reply


@run_async
async def test_ambiguous_items_get_clarification(monkeypatch, user):
    async def invoke(*_):
        return {"matches": [{
            "order_id": str(uuid.uuid4()),
            "external_order_ref": "A",
            "items": [
                {"order_item_id": str(uuid.uuid4()), "product_name": "Blue Widget", "sku": "W-1"},
                {"order_item_id": str(uuid.uuid4()), "product_name": "Blue Widget", "sku": "W-2"},
            ],
        }]}

    monkeypatch.setattr(conversation, "_invoke_mcp", invoke)
    result = await conversation.handle_conversation(
        user,
        "Please replace the Blue Widget",
        settings=settings(),
        client=FakeClient([response([call("find_order", {"query": "Blue Widget"})]), response()]),
    )
    assert result.status == "needs_clarification"
    assert "Which one" in result.reply


@run_async
async def test_tool_call_iteration_limit(monkeypatch, user):
    invoked = []

    async def invoke(*args):
        invoked.append(args)
        return {"matches": []}

    monkeypatch.setattr(conversation, "_invoke_mcp", invoke)
    calls = [response([call("find_order", {"query": "x"})]) for _ in range(5)]
    result = await conversation.handle_conversation(user, "x", settings=settings(gemini_max_iterations=2), client=FakeClient(calls))
    assert len(invoked) == 2
    assert result.status == "needs_clarification"


@run_async
async def test_malformed_arguments_rejected_before_mcp(monkeypatch, user):
    async def forbidden_call(*_):
        pytest.fail("invalid arguments reached MCP")

    monkeypatch.setattr(conversation, "open_authenticated_mcp_client", forbidden_call)
    result = await conversation._invoke_mcp(user.id, "get_order_details", {"order_id": "not-a-uuid", "owner_id": str(user.id)})
    assert result["error"]["code"] == "invalid_arguments"


@run_async
async def test_unexpected_consequential_tool_never_invokes_mcp(monkeypatch, user):
    async def forbidden_call(*_):
        pytest.fail("unexpected tool reached MCP")

    monkeypatch.setattr(conversation, "_invoke_mcp", forbidden_call)
    result = await conversation.handle_conversation(user, "Please do it", settings=settings(), client=FakeClient([response([call("create_return_request", {})]), response()]))
    assert result.tool_events[0]["tool"] == "unsupported"
    assert result.proposal is None


@run_async
async def test_missing_key_returns_safe_error(user):
    with pytest.raises(DomainError) as exc:
        await conversation.handle_conversation(user, "Help", settings=Settings(_env_file=None))
    assert exc.value.code == "provider_not_configured"
    assert "key" not in exc.value.message.lower()


def test_provider_errors_are_sanitized(monkeypatch, user, caplog):
    class FailedModels:
        async def generate_content(self, **_):
            raise RuntimeError("secret provider response containing API_KEY and session-cookie")

    fake = SimpleNamespace(aio=SimpleNamespace(models=FailedModels()))
    monkeypatch.setattr(conversation, "_provider", lambda _settings: fake)
    app.dependency_overrides[resolve_demo_user] = lambda: user
    caplog.set_level(logging.ERROR, logger="app.conversation")
    try:
        response = TestClient(app).post("/api/conversation", json={"message": "Help"})
    finally:
        app.dependency_overrides.pop(resolve_demo_user, None)

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "provider_error",
            "message": "The assistant could not complete this message.",
        }
    }
    messages = [record.getMessage() for record in caplog.records if record.name == "app.conversation"]
    assert messages == ["gemini_provider_failure exception_type=RuntimeError"]
    assert "secret provider response" not in caplog.text
    assert "API_KEY" not in caplog.text
    assert "session-cookie" not in caplog.text


@pytest.mark.parametrize(
    ("api_code", "expected_status", "expected_code", "expected_message"),
    [
        (503, 503, "provider_unavailable", "The assistant is temporarily unavailable."),
        (429, 429, "provider_rate_limited", "The assistant is busy. Please try again shortly."),
    ],
)
def test_gemini_api_errors_are_sanitized(monkeypatch, user, caplog, api_code, expected_status, expected_code, expected_message):
    exception_text = "sensitive provider message API_KEY session-cookie grant"

    class FailedModels:
        async def generate_content(self, **_):
            raise errors.APIError(api_code, {"error": {"message": exception_text}})

    monkeypatch.setattr(
        conversation,
        "_provider",
        lambda _settings: SimpleNamespace(aio=SimpleNamespace(models=FailedModels())),
    )
    app.dependency_overrides[resolve_demo_user] = lambda: user
    caplog.set_level(logging.ERROR, logger="app.conversation")
    try:
        response = TestClient(app).post("/api/conversation", json={"message": "Help"})
    finally:
        app.dependency_overrides.pop(resolve_demo_user, None)

    assert response.status_code == expected_status
    assert response.json() == {"detail": {"code": expected_code, "message": expected_message}}
    messages = [record.getMessage() for record in caplog.records if record.name == "app.conversation"]
    assert messages == [f"gemini_api_error exception_type=APIError api_code={api_code}"]
    assert exception_text not in caplog.text
    assert "API_KEY" not in caplog.text
    assert "session-cookie" not in caplog.text
    assert "grant" not in caplog.text


def test_conversation_route_requires_demo_session():
    response = TestClient(app).post("/api/conversation", json={"message": "Find order"})
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "unauthenticated"


def test_authenticated_conversation_uses_session_identity(monkeypatch, user):
    observed = []

    async def fake_handler(resolved_user, message):
        observed.append((resolved_user.id, message))
        return conversation.ConversationOutput(status="answered", reply="Checked.")

    monkeypatch.setattr("app.main.handle_conversation", fake_handler)
    app.dependency_overrides[resolve_demo_user] = lambda: user
    try:
        response = TestClient(app).post("/api/conversation", json={"message": "Check my order"})
    finally:
        app.dependency_overrides.pop(resolve_demo_user, None)
    assert response.status_code == 200
    assert observed == [(user.id, "Check my order")]


@run_async
async def test_proposal_requires_explicit_intent_matching_item_and_positive_check(monkeypatch, user):
    order_id, item_id = uuid.uuid4(), uuid.uuid4()
    created = []
    invoked = []

    async def invoke(user_id, name, args):
        invoked.append(name)
        assert user_id == user.id
        if name == "find_order":
            return {"matches": [{
                "order_id": str(order_id),
                "external_order_ref": "ORD-42",
                "items": [{"order_item_id": str(item_id), "sku": "SKU-9", "product_name": "Blue kettle"}],
            }]}
        if name == "check_return_eligibility":
            return {"eligibility": {"eligible": True, "reasons": [], "policy_version": "demo-1"}}
        pytest.fail(f"unexpected tool {name}")

    def create(_db, owner_id, selected_order, selected_item, resolution):
        created.append((owner_id, selected_order, selected_item, resolution))
        return {"proposal_id": uuid.uuid4(), "state": "pending", "action_snapshot": {"order_id": str(order_id), "order_item_id": str(item_id)}}

    monkeypatch.setattr(conversation, "_invoke_mcp", invoke)
    monkeypatch.setattr(conversation, "create_proposal", create)
    fake = FakeClient([
        response([call("find_order", {"query": "ORD-42"})]),
        response([call("check_return_eligibility", {"order_id": str(order_id), "order_item_id": str(item_id)})]),
        response(),
    ])
    result = await conversation.handle_conversation(
        user,
        "I want a replacement for this damaged Blue kettle in ORD-42",
        settings=settings(),
        client=fake,
    )
    assert result.status == "proposal_created"
    assert result.proposal is not None
    assert created == [(user.id, order_id, item_id, "replacement")]
    assert result.proposal["state"] == "pending"
    assert "request_id" not in result.proposal
    assert "create_return_request" not in invoked


@run_async
@pytest.mark.parametrize(
    "message",
    [
        "Check replacement eligibility",
        "Is this item eligible for a replacement?",
    ],
)
async def test_eligibility_question_does_not_create_proposal(monkeypatch, user, message):
    order_id, item_id = uuid.uuid4(), uuid.uuid4()
    invoked = []

    async def invoke(_user_id, name, _args):
        invoked.append(name)
        if name == "find_order":
            return {"matches": [{"order_id": str(order_id), "items": [{"order_item_id": str(item_id), "product_name": "Lamp"}]}]}
        return {"eligibility": {"eligible": True, "reasons": []}}

    monkeypatch.setattr(conversation, "_invoke_mcp", invoke)
    monkeypatch.setattr(conversation, "create_proposal", lambda *_: pytest.fail("proposal created without explicit intent"))
    fake = FakeClient([
        response([call("find_order", {"query": "ORD"})]),
        response([call("check_return_eligibility", {"order_id": str(order_id), "order_item_id": str(item_id)})]),
        response(),
    ])
    result = await conversation.handle_conversation(user, message, settings=settings(), client=fake)
    assert result.proposal is None
    assert result.status != "proposal_created"
    assert "create_return_request" not in invoked
