from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ToolCallInfo(BaseModel):
    tool_name: str
    tool_input: dict[str, Any]
    tool_status: str


class GroundingInfo(BaseModel):
    toolsUsed: list[str] = Field(default_factory=list)
    riskRevision: int | None = None
    routeId: str | None = None
    generatedAt: datetime | None = None


class AssistantChatRequest(BaseModel):
    message: str
    routeId: str | None = None
    conversationId: str | None = None


class AssistantChatResponse(BaseModel):
    answer: str
    conversationId: str
    toolCalls: list[ToolCallInfo] = Field(default_factory=list)
    grounding: GroundingInfo = Field(default_factory=GroundingInfo)


class AssistantMessage(BaseModel):
    role: str  # "user", "assistant", "tool"
    content: str | list[dict[str, Any]]
    tool_calls: list[dict[str, Any]] | None = None  # To record pending tool calls
    tool_result_id: str | None = None  # For tool result messages


class AssistantSession(BaseModel):
    conversation_id: str
    messages: list[AssistantMessage] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    route_id: str | None = None
