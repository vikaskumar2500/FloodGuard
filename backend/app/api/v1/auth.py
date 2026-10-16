from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_rate_limiter, require_authenticated_user
from app.core.auth import create_access_token, create_sse_token
from app.core.config import get_settings
from app.core.security import verify_password
from app.db.session import get_session
from app.models.user import User

settings = get_settings()

router = APIRouter(prefix="", tags=["auth"])


class Token(BaseModel):
    access_token: str
    token_type: str


class SSEToken(BaseModel):
    token: str


@router.post(
    "/login",
    response_model=Token,
    dependencies=[
        Depends(
            get_rate_limiter(
                "login",
                settings.rate_limit_login_requests,
                settings.rate_limit_login_window_seconds,
            )
        )
    ],
)
async def login_access_token(
    db: Annotated[AsyncSession, Depends(get_session)],
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    stmt = select(User).where(User.email == form_data.username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not user.hashed_password:
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    access_token = create_access_token(subject=user.id)
    return Token(access_token=access_token, token_type="bearer")


@router.post("/routes/{route_id}/stream-token", response_model=SSEToken)
async def get_stream_token(
    route_id: str, current_user: Annotated[User, Depends(require_authenticated_user)]
) -> SSEToken:
    # Basic permission check if needed could be here, or just let authenticated users get tokens
    if not current_user.has_permission("read:routes"):
        raise HTTPException(status_code=403, detail="Not enough permissions")

    token = create_sse_token(subject=current_user.id, route_id=route_id)
    return SSEToken(token=token)
