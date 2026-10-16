import asyncio
import logging
from typing import Any

from app.assistant.models import AssistantMessage
from app.assistant.prompts import SYSTEM_PROMPT
from app.assistant.service import AssistantProvider

logger = logging.getLogger("floodguard.assistant.bedrock")


class BedrockAssistantProvider(AssistantProvider):
    def __init__(
        self,
        client: Any,
        model_id: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        timeout: float = 10.0,
    ):
        self.client = client
        self.model_id = model_id
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    async def respond(
        self, messages: list[AssistantMessage], tools: list[dict[str, Any]]
    ) -> AssistantMessage:

        bedrock_messages = []
        for msg in messages:
            content = msg.content
            if isinstance(content, str):
                content = [{"text": content}]

            # format for converse API
            bmsg = {"role": msg.role, "content": content}
            bedrock_messages.append(bmsg)

        system_config = [{"text": SYSTEM_PROMPT}]

        try:
            # boto3 is sync, so we wrap in asyncio.to_thread
            loop = asyncio.get_running_loop()

            kwargs = {
                "modelId": self.model_id,
                "messages": bedrock_messages,
                "system": system_config,
                "inferenceConfig": {"maxTokens": self.max_tokens, "temperature": self.temperature},
            }
            if tools:
                kwargs["toolConfig"] = {"tools": tools}

            response = await loop.run_in_executor(None, lambda: self.client.converse(**kwargs))

            output = response["output"]["message"]
            role = output["role"]
            content_blocks = output["content"]

            tool_calls = []
            final_content = []

            for block in content_blocks:
                if "toolUse" in block:
                    tool_calls.append(block["toolUse"])
                elif "text" in block:
                    final_content.append({"text": block["text"]})

            if not final_content and not tool_calls:
                final_content = [{"text": "I encountered an error generating a response."}]

            return AssistantMessage(
                role=role, content=final_content, tool_calls=tool_calls if tool_calls else None
            )

        except Exception as e:
            logger.error("bedrock_converse_failed", extra={"error": str(e)}, exc_info=True)
            return AssistantMessage(
                role="assistant", content="I'm temporarily unavailable to answer that right now."
            )
