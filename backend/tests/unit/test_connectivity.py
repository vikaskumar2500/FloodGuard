import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.session import get_session
from app.services.health import check_database, check_redis


def fake_engine(*, error=None, version="3.5.0"):
    connection = MagicMock()
    result = MagicMock()
    result.scalar_one.return_value = version
    connection.execute = AsyncMock(return_value=result, side_effect=error)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=connection)
    context.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.connect.return_value = context
    return engine, connection, context


async def test_database_helper_queries_postgis_and_releases_connection():
    engine, connection, context = fake_engine()
    result = await check_database(engine, 1, "test")
    assert all(item.status == "healthy" for item in result.values())
    assert [str(call.args[0]) for call in connection.execute.call_args_list] == [
        "SELECT 1",
        "SELECT PostGIS_Version()",
    ]
    context.__aexit__.assert_awaited_once()


async def test_database_failure_is_sanitized():
    engine, _, _ = fake_engine(error=ConnectionError("password-secret@private-host"))
    result = await check_database(engine, 1, "test")
    assert result["postgres"].status == "unavailable"
    assert "password-secret" not in str(result)
    assert "private-host" not in str(result)


async def test_postgis_failure_keeps_database_status_separate():
    engine, connection, _ = fake_engine()
    connection.execute.side_effect = [MagicMock(), RuntimeError("extension not installed")]
    result = await check_database(engine, 1, "test")
    assert result["postgres"].status == "healthy"
    assert result["postgis"].status == "unavailable"


async def test_database_timeout_is_bounded():
    engine, connection, _ = fake_engine()

    async def slow(*args):
        await asyncio.sleep(0.1)

    connection.execute.side_effect = slow
    result = await check_database(engine, 0.001, "test")
    assert result["postgres"].status == "unavailable"


async def test_redis_helper_ping():
    client = MagicMock(ping=AsyncMock(return_value=True))
    assert (await check_redis(client, 1, "test")).status == "healthy"
    client.ping.assert_awaited_once()


async def test_redis_failure_is_sanitized():
    client = MagicMock(ping=AsyncMock(side_effect=ConnectionError("password-secret")))
    result = await check_redis(client, 1, "test")
    assert result.status == "unavailable"
    assert "password-secret" not in result.message


async def test_redis_timeout_is_bounded():
    async def slow():
        await asyncio.sleep(0.1)

    client = MagicMock(ping=slow)
    assert (await check_redis(client, 0.001, "test")).status == "unavailable"


async def test_request_session_is_closed_on_error():
    state = {"closed": False}

    @asynccontextmanager
    async def sessions():
        try:
            yield "session"
        finally:
            state["closed"] = True

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(database=SimpleNamespace(sessions=sessions)))
    )
    dependency = get_session(request)
    assert await anext(dependency) == "session"
    with pytest.raises(RuntimeError, match="consumer failed"):
        await dependency.athrow(RuntimeError("consumer failed"))
    assert state["closed"] is True
