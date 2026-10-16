import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from app.assistant.models import AssistantSession


class SessionStore:
    def __init__(self, ttl_seconds: int = 3600, max_messages: int = 20):
        self._store: dict[str, AssistantSession] = {}
        self.ttl_seconds = ttl_seconds
        self.max_messages = max_messages
        self._lock = asyncio.Lock()

    async def get_or_create(self, conversation_id: str | None = None) -> AssistantSession:
        async with self._lock:
            now = datetime.now(UTC)
            self._cleanup(now)

            if not conversation_id or conversation_id not in self._store:
                new_id = conversation_id or str(uuid4())
                session = AssistantSession(
                    conversation_id=new_id,
                    created_at=now,
                    updated_at=now,
                )
                self._store[new_id] = session
                return session

            session = self._store[conversation_id]
            session.updated_at = now
            return session

    async def save(self, session: AssistantSession) -> None:
        async with self._lock:
            # Enforce max messages limit (keep oldest system/context, drop middle, keep newest)
            # For simplicity, we just keep the last max_messages
            if len(session.messages) > self.max_messages:
                session.messages = session.messages[-self.max_messages :]

            session.updated_at = datetime.now(UTC)
            self._store[session.conversation_id] = session

    def _cleanup(self, now: datetime) -> None:
        # Caller must hold lock
        expired = [
            cid
            for cid, sess in self._store.items()
            if (now - sess.updated_at).total_seconds() > self.ttl_seconds
        ]
        for cid in expired:
            del self._store[cid]
