from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from app.assistant.models import (
    AssistantChatRequest,
    AssistantChatResponse,
    AssistantMessage,
    GroundingInfo,
    ToolCallInfo,
)
from app.assistant.session import SessionStore
from app.assistant.tool_registry import ToolRegistry


class AssistantProvider(ABC):
    @abstractmethod
    async def respond(
        self, messages: list[AssistantMessage], tools: list[dict[str, Any]]
    ) -> AssistantMessage:
        pass


class MockAssistantProvider(AssistantProvider):
    async def respond(
        self, messages: list[AssistantMessage], tools: list[dict[str, Any]]
    ) -> AssistantMessage:
        last_msg = messages[-1].content if messages else ""
        if isinstance(last_msg, list):
            # parse bedrock style text block if needed
            text_blocks = [blk.get("text", "") for blk in last_msg if "text" in blk]
            last_msg = " ".join(text_blocks)

        if "weather" in str(last_msg).lower() or "rainfall" in str(last_msg).lower():
            # mock tool call
            return AssistantMessage(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "toolUseId": "mock-tool-id-1",
                        "name": "get_environment_status",
                        "input": {"routeId": "mock"},
                    }
                ],
            )

        if "risk" in str(last_msg).lower():
            return AssistantMessage(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "toolUseId": "mock-tool-id-2",
                        "name": "get_route_risk",
                        "input": {"routeId": "mock"},
                    }
                ],
            )

        return AssistantMessage(role="assistant", content="This is a mocked grounded response.")


class AssistantService:
    def __init__(
        self,
        provider: AssistantProvider,
        session_store: SessionStore,
        tool_registry: ToolRegistry,
        max_tool_rounds: int = 5,
    ):
        self.provider = provider
        self.session_store = session_store
        self.tool_registry = tool_registry
        self.max_tool_rounds = max_tool_rounds

    async def handle_chat(
        self, request: AssistantChatRequest, user: Any = None
    ) -> AssistantChatResponse:
        session = await self.session_store.get_or_create(request.conversationId)
        if request.routeId:
            session.route_id = request.routeId

        session.messages.append(AssistantMessage(role="user", content=request.message))

        tools = [
            {
                "toolSpec": {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": {"json": t.input_schema},
                }
            }
            for t in self.tool_registry.get_all_definitions()
        ]

        tool_infos: list[ToolCallInfo] = []
        tools_used = set()

        for _ in range(self.max_tool_rounds):
            response_msg = await self.provider.respond(session.messages, tools)
            session.messages.append(response_msg)

            if not response_msg.tool_calls:
                break

            # Execute tool calls
            tool_results = []
            for tcall in response_msg.tool_calls:
                tool_name = tcall["name"]
                tool_input = tcall["input"]
                tool_use_id = tcall["toolUseId"]

                tools_used.add(tool_name)

                exec_result = await self.tool_registry.execute(tool_name, tool_input, user=user)

                tool_infos.append(
                    ToolCallInfo(
                        tool_name=tool_name,
                        tool_input=tool_input,
                        tool_status="success" if exec_result.success else "error",
                    )
                )

                content = exec_result.data if exec_result.success else {"error": exec_result.error}
                tool_results.append(
                    {
                        "toolResult": {
                            "toolUseId": tool_use_id,
                            "content": [{"json": content}],
                            "status": "success" if exec_result.success else "error",
                        }
                    }
                )

            # Append tool results as user message (Bedrock converse API style)
            session.messages.append(AssistantMessage(role="user", content=tool_results))
        await self.session_store.save(session)

        grounding = GroundingInfo(
            toolsUsed=list(tools_used),
            generatedAt=datetime.now(UTC),
            routeId=session.route_id,
        )

        final_text = response_msg.content if isinstance(response_msg.content, str) else ""
        if isinstance(response_msg.content, list):
            text_blocks = [blk.get("text", "") for blk in response_msg.content if "text" in blk]
            final_text = " ".join(text_blocks)

        if not final_text and not response_msg.tool_calls:
            final_text = "I'm sorry, I couldn't generate a response."

        return AssistantChatResponse(
            answer=final_text,
            conversationId=session.conversation_id,
            toolCalls=tool_infos,
            grounding=grounding,
        )
