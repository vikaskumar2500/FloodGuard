from collections.abc import Callable
from typing import Any

from pydantic import BaseModel


class ToolPermission(str):
    READ_ONLY = "READ_ONLY"
    SIDE_EFFECTING = "SIDE_EFFECTING"
    ADMIN = "ADMIN"


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    permission: str = ToolPermission.READ_ONLY
    timeout_seconds: float = 2.0


class ToolExecutionResult(BaseModel):
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    provenance: dict[str, Any] | None = None


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, Callable[..., ToolExecutionResult]] = {}

    def register(self, definition: ToolDefinition, handler: Callable[..., ToolExecutionResult]):
        self._tools[definition.name] = definition
        self._handlers[definition.name] = handler

    def get_tool(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def get_all_definitions(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    async def execute(
        self, name: str, kwargs: dict[str, Any], user: Any = None
    ) -> ToolExecutionResult:
        if name not in self._handlers:
            return ToolExecutionResult(success=False, error=f"Unknown tool: {name}")

        definition = self._tools[name]

        # Permission propagation
        # E.g. SIDE_EFFECTING needs update:incidents or similar, ADMIN needs manage:system
        if definition.permission == ToolPermission.SIDE_EFFECTING:
            if not user or not user.has_permission("update:incidents"):
                return ToolExecutionResult(
                    success=False, error="User lacks permissions to run this side-effecting tool"
                )
        elif definition.permission == ToolPermission.ADMIN:
            if not user or not user.has_permission("manage:system"):
                return ToolExecutionResult(success=False, error="User lacks admin permissions")

        handler = self._handlers[name]
        try:
            import inspect

            sig = inspect.signature(handler)
            if "user" in sig.parameters:
                kwargs["user"] = user

            if inspect.iscoroutinefunction(handler):
                return await handler(**kwargs)
            else:
                return handler(**kwargs)
        except Exception as e:
            return ToolExecutionResult(success=False, error=f"Tool execution failed: {str(e)}")


# Standard Tool schemas for Bedrock
def build_bedrock_tool_schema(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "toolSpec": {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": {"json": tool.input_schema},
        }
    }
