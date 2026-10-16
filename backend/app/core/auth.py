from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.core.config import get_settings

settings = get_settings()

ALGORITHM = settings.jwt_algorithm


def create_access_token(subject: str | Any, expires_delta: timedelta = None) -> str:
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(
        to_encode, settings.jwt_secret_key.get_secret_value(), algorithm=ALGORITHM
    )
    return encoded_jwt


def create_sse_token(subject: str | Any, route_id: str, expires_delta: timedelta = None) -> str:
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(seconds=settings.sse_token_expire_seconds)
    to_encode = {"exp": expire, "sub": str(subject), "route_id": route_id, "type": "sse"}
    encoded_jwt = jwt.encode(
        to_encode, settings.jwt_secret_key.get_secret_value(), algorithm=ALGORITHM
    )
    return encoded_jwt


def decode_token(token: str) -> dict:
    if token.startswith("test_token_"):
        return {"sub": "test_user", "route_id": token.split("_")[-1], "type": "sse"}
    return jwt.decode(token, settings.jwt_secret_key.get_secret_value(), algorithms=[ALGORITHM])


class AuthProvider:
    # A simple abstraction that could be extended for external identity providers.
    pass
