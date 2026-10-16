import pytest

from app.assistant.models import AssistantChatRequest
from app.assistant.service import AssistantService, MockAssistantProvider
from app.assistant.session import SessionStore
from app.assistant.tool_registry import ToolDefinition, ToolExecutionResult, ToolRegistry


@pytest.mark.asyncio
async def test_mock_provider_and_session():
    store = SessionStore()
    provider = MockAssistantProvider()

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="get_route_summary", description="test", input_schema={}),
        lambda **kwargs: ToolExecutionResult(success=True, data={"res": "ok"}),
    )

    service = AssistantService(provider, store, registry)

    req = AssistantChatRequest(message="Hello")
    resp = await service.handle_chat(req)

    assert resp.answer == "This is a mocked grounded response."
    assert resp.conversationId is not None

    # Test session bounding
    session = await store.get_or_create(resp.conversationId)
    assert len(session.messages) == 2  # 1 user, 1 assistant


@pytest.mark.asyncio
async def test_mock_provider_tool_call():
    store = SessionStore()
    provider = MockAssistantProvider()

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="get_environment_status", description="test", input_schema={}),
        lambda **kwargs: ToolExecutionResult(success=True, data={"rainfall": 0.0}),
    )

    service = AssistantService(provider, store, registry)

    req = AssistantChatRequest(message="What is the rainfall?")
    resp = await service.handle_chat(req)

    assert resp.conversationId is not None
    assert len(resp.toolCalls) > 0
    assert resp.toolCalls[0].tool_name == "get_environment_status"
    assert "get_environment_status" in resp.grounding.toolsUsed
