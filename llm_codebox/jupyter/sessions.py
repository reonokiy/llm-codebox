"""Session-to-kernel mapping and lifecycle management."""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from structlog.stdlib import get_logger

from .. import config

if TYPE_CHECKING:
    from .channels import KernelChannelsCache
    from .executor import JupyterExecutor
    from .gateway_http import KernelGatewayClient
    from .state_persistence import StatePersistence
    from .types import RedisClientProtocol

logger = get_logger(__name__)

SESSION_TIMEOUT_SECONDS = 3600
MAX_ACTIVE_SESSIONS = config.MAX_ACTIVE_SESSIONS


@dataclass
class SessionEntry:
    """Represents an active session with its kernel."""

    kernel_id: str
    last_used: float = field(default_factory=time.monotonic)


class SessionRegistry:
    """Manages session-to-kernel mappings with LRU eviction."""

    def __init__(
        self,
        gateway: KernelGatewayClient,
        channels_cache: KernelChannelsCache,
        executor: JupyterExecutor,
        persistence: StatePersistence,
        max_sessions: int = MAX_ACTIVE_SESSIONS,
        session_timeout: float = SESSION_TIMEOUT_SECONDS,
    ) -> None:
        self._gateway = gateway
        self._channels_cache = channels_cache
        self._executor = executor
        self._persistence = persistence
        self._max_sessions = max_sessions
        self._session_timeout = session_timeout

        self._sessions: dict[str, SessionEntry] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None

    def get_sessions_info(self) -> dict[str, Any]:
        """Get information about all active sessions."""
        now = time.monotonic()
        sessions = [
            {
                "session_id": sid,
                "kernel_id": entry.kernel_id,
                "status": "active",
                "idle_seconds": round(now - entry.last_used, 1),
            }
            for sid, entry in self._sessions.items()
        ]
        return {
            "active_sessions": len(sessions),
            "max_sessions": self._max_sessions,
            "sessions": sessions,
        }

    async def get_kernel_id(
        self,
        session_id: str,
        redis_client: RedisClientProtocol | None = None,
    ) -> str:
        """Get or create a kernel for the session."""
        lock = self._locks.setdefault(session_id, asyncio.Lock())

        async with lock:
            self._ensure_cleanup_task()

            if entry := self._sessions.get(session_id):
                entry.last_used = time.monotonic()
                return entry.kernel_id

            async with self._global_lock:
                # Double-check after acquiring global lock
                if entry := self._sessions.get(session_id):
                    entry.last_used = time.monotonic()
                    return entry.kernel_id

                # Evict if at capacity
                while len(self._sessions) >= self._max_sessions:
                    await self._evict_lru(redis_client)

                # Create new kernel
                kernel_id = await self._gateway.create_kernel()
                self._sessions[session_id] = SessionEntry(kernel_id=kernel_id)
                logger.info(
                    "kernel started",
                    session_id=session_id,
                    kernel_id=kernel_id,
                )

                # Restore state from Redis if available
                if redis_client:
                    await self._try_restore_state(session_id, kernel_id, redis_client)

                return kernel_id

    async def clear_session(self, session_id: str) -> None:
        """Clear a session and delete its kernel."""
        entry = self._sessions.pop(session_id, None)
        self._locks.pop(session_id, None)

        if entry:
            await self._delete_kernel(session_id, entry.kernel_id)

    def clear_session_sync(self, session_id: str) -> None:
        """Clear a session synchronously (schedules async cleanup)."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.clear_session(session_id))
        except RuntimeError:
            asyncio.run(self.clear_session(session_id))

    async def _evict_lru(self, redis_client: RedisClientProtocol | None) -> None:
        """Evict the least recently used session."""
        if not self._sessions:
            return

        lru_session = min(
            self._sessions.items(),
            key=lambda x: x[1].last_used,
        )[0]
        entry = self._sessions.get(lru_session)

        if entry:
            logger.info(
                "evicting lru session",
                session_id=lru_session,
                kernel_id=entry.kernel_id,
            )

            # Dump state before eviction
            if redis_client:
                channels = await self._channels_cache.get(entry.kernel_id)
                state = await self._persistence.dump_state(lru_session, channels)
                if state:
                    self._persistence.save_to_redis(redis_client, lru_session, state)

        await self.clear_session(lru_session)

    async def _delete_kernel(self, session_id: str, kernel_id: str) -> None:
        """Delete a kernel from the gateway."""
        await self._channels_cache.close(kernel_id)
        success = await self._gateway.delete_kernel(kernel_id)
        if success:
            logger.info("kernel deleted", session_id=session_id, kernel_id=kernel_id)

    async def _try_restore_state(
        self,
        session_id: str,
        kernel_id: str,
        redis_client: RedisClientProtocol,
    ) -> None:
        """Try to restore session state from Redis."""
        with contextlib.suppress(Exception):
            state_b64 = self._persistence.load_from_redis(redis_client, session_id)
            if state_b64:
                channels = await self._channels_cache.get(kernel_id)
                await self._persistence.load_state(session_id, channels, state_b64)
                self._persistence.delete_from_redis(redis_client, session_id)

    def _ensure_cleanup_task(self) -> None:
        """Start cleanup task if not already running."""
        if self._cleanup_task is None or self._cleanup_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._cleanup_task = loop.create_task(self._cleanup_loop())
            except RuntimeError:
                pass

    async def _cleanup_loop(self) -> None:
        """Background task to clean up expired sessions."""
        while True:
            await asyncio.sleep(60)
            now = time.monotonic()
            expired = [
                sid
                for sid, entry in self._sessions.items()
                if now - entry.last_used > self._session_timeout
            ]
            for sid in expired:
                await self.clear_session(sid)
