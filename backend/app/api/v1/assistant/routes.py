import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.assistant.bedrock.client import BedrockAssistantProvider
from app.assistant.factory import create_assistant_tool_registry
from app.assistant.models import AssistantChatRequest, AssistantChatResponse
from app.assistant.service import AssistantService, MockAssistantProvider
from app.assistant.session import SessionStore

logger = logging.getLogger("floodguard.api.assistant")
router = APIRouter(prefix="/assistant", tags=["assistant"])


def get_assistant_service(request: Request) -> AssistantService:
    config = request.app.state.settings

    # Store session store on app state to persist between requests
    if not hasattr(request.app.state, "assistant_session_store"):
        request.app.state.assistant_session_store = SessionStore(
            ttl_seconds=getattr(config, "assistant_session_ttl", 3600),
            max_messages=getattr(config, "assistant_max_messages", 20),
        )

    session_store = request.app.state.assistant_session_store
    runtime = request.app.state.runtime
    env_service = request.app.state.environmental_service

    registry = create_assistant_tool_registry(runtime, env_service)

    provider_name = getattr(config, "assistant_provider", "MOCK").upper()
    if provider_name == "BEDROCK":
        import boto3

        bedrock_client = boto3.client(
            "bedrock-runtime", region_name=getattr(config, "aws_region", "us-east-1")
        )
        provider = BedrockAssistantProvider(
            client=bedrock_client,
            model_id=getattr(config, "bedrock_model_id", "anthropic.claude-3-haiku-20240307-v1:0"),
            temperature=getattr(config, "bedrock_temperature", 0.1),
            max_tokens=getattr(config, "bedrock_max_tokens", 1024),
            timeout=getattr(config, "bedrock_timeout_seconds", 10.0),
        )
    else:
        provider = MockAssistantProvider()

    return AssistantService(
        provider=provider,
        session_store=session_store,
        tool_registry=registry,
        max_tool_rounds=getattr(config, "assistant_max_tool_rounds", 5),
    )


from app.api.dependencies import get_rate_limiter, require_authenticated_user
from app.models.user import User


@router.post(
    "/chat",
    response_model=AssistantChatResponse,
    dependencies=[Depends(get_rate_limiter("assistant_chat", 20, 60))],
)
async def chat(
    chat_request: AssistantChatRequest,
    current_user: User = Depends(require_authenticated_user),
    service: AssistantService = Depends(get_assistant_service),
):
    try:
        response = await service.handle_chat(chat_request, user=current_user)
        return response
    except Exception:
        logger.error("assistant_chat_error", exc_info=True)
        raise HTTPException(status_code=500, detail="Assistant temporarily unavailable")
