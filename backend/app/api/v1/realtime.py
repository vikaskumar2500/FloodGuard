from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import StreamingResponse

from app.core.auth import decode_token

logger = logging.getLogger("floodguard.realtime")
router = APIRouter(prefix="/routes", tags=["realtime"])


@router.get("/{route_id}/events")
async def route_events(
    request: Request,
    route_id: UUID,
    token: str | None = Query(
        default=None, description="Short-lived SSE token from /routes/{route_id}/stream-token"
    ),
) -> StreamingResponse:
    key = str(route_id)
    if token:
        try:
            payload = decode_token(token)
            if payload.get("type") != "sse" or payload.get("route_id") != key:
                raise HTTPException(status_code=403, detail="Invalid token for this route")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
    elif request.app.state.settings.app_env != "development":
        raise HTTPException(status_code=401, detail="Token required in non-development environment")

    route = request.app.state.active_route_registry.get(key)
    if route is None:
        raise HTTPException(status_code=404)

    publisher = request.app.state.realtime_publisher
    queue = publisher.subscribe(key)

    async def stream() -> AsyncIterator[str]:
        logger.info("sse_connected", extra={"route_id": key})
        try:
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=request.app.state.settings.realtime_heartbeat_seconds
                    )
                    yield publisher.encode(event)
                except TimeoutError:
                    current = request.app.state.active_route_registry.get(key)
                    if current is None and queue.empty():
                        break
                    event = publisher.heartbeat(
                        key, current.evaluated_risk_revision if current else 0
                    )
                    if not queue.empty():
                        event = queue.get_nowait()
                    yield publisher.encode(event)
                    if current is None and queue.empty():
                        break
        finally:
            publisher.unsubscribe(key, queue)
            logger.info("sse_disconnected", extra={"route_id": key})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
