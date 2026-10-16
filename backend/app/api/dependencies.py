from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import decode_token
from app.core.config import get_settings
from app.db.session import get_session
from app.models.user import User

settings = get_settings()

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.api_v1_prefix}/login", scheme_name="JWT"
)


async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_session)],
    token: Annotated[str, Depends(reusable_oauth2)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except Exception:
        raise credentials_exception

    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


async def require_authenticated_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user


def require_permission(permission: str) -> Callable:
    def dependency(current_user: Annotated[User, Depends(require_authenticated_user)]) -> User:
        if not current_user.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
            )
        return current_user

    return dependency


async def rate_limit(
    request: Request,
    action: str = "default",
    max_requests: int = settings.rate_limit_requests,
    window_seconds: int = settings.rate_limit_window_seconds,
):
    redis_client = getattr(request.app.state, "redis", None)
    from app.core.rate_limit import check_rate_limit

    await check_rate_limit(request, redis_client, action, max_requests, window_seconds)


def get_rate_limiter(action: str, max_requests: int, window_seconds: int):
    async def dependency(request: Request):
        await rate_limit(request, action, max_requests, window_seconds)

    return dependency
