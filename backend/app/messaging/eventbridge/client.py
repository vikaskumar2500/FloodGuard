"""Small asynchronous adapter for the AWS PutEvents API."""

import asyncio
from typing import Any, Protocol


class EventBridgeClient(Protocol):
    async def put_events(self, *, Entries: list[dict[str, Any]]) -> dict[str, Any]: ...


class Boto3EventBridgeClient:
    def __init__(self, region_name: str, endpoint_url: str | None = None) -> None:
        import boto3

        self.client = boto3.client("events", region_name=region_name, endpoint_url=endpoint_url)

    async def put_events(self, *, Entries: list[dict[str, Any]]) -> dict[str, Any]:
        return await asyncio.to_thread(self.client.put_events, Entries=Entries)
