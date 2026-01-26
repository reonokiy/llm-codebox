"""Kernel session manager - main entry point for kernel operations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from structlog.stdlib import get_logger

from .channels import KernelChannelsCache
from .executor import JupyterExecutor, strip_ansi
from .gateway_http import KernelGatewayClient
from .models import ExecuteResult
from .sessions import SessionRegistry
from .state_persistence import StatePersistence

if TYPE_CHECKING:
    from .types import RedisClientProtocol

logger = get_logger(__name__)


class KernelSessionManager:
    """Main entry point for managing Jupyter kernel sessions.

    Coordinates between gateway client, channels cache, executor,
    session registry, and state persistence.
    """

    def __init__(
        self,
        gateway: KernelGatewayClient | None = None,
    ) -> None:
        self._gateway = gateway or KernelGatewayClient()
        self._channels_cache = KernelChannelsCache(
            gateway_ws_url=self._gateway.ws_url,
            auth_headers=self._gateway._auth_headers(),
        )
        self._executor = JupyterExecutor()
        self._persistence = StatePersistence(self._executor)
        self._sessions = SessionRegistry(
            gateway=self._gateway,
            channels_cache=self._channels_cache,
            executor=self._executor,
            persistence=self._persistence,
        )

    def get_sessions_info(self) -> dict[str, Any]:
        """Get information about all active sessions."""
        return self._sessions.get_sessions_info()

    def clear_session(self, session_id: str) -> None:
        """Clear a session and its associated kernel."""
        self._sessions.clear_session_sync(session_id)

    async def execute(
        self,
        redis_client: RedisClientProtocol | Any,
        session_id: str,
        code: str,
        timeout: float,
    ) -> ExecuteResult:
        """Execute code and return unified result format.

        This is the single execution method. API layer handles
        format conversion to V1/V2 as needed.
        """
        kernel_id = await self._sessions.get_kernel_id(session_id, redis_client)

        logger.info(
            "executing code",
            session_id=session_id,
            kernel_id=kernel_id,
        )
        if logging.getLogger(__name__).isEnabledFor(logging.DEBUG):
            logger.debug(
                "code input",
                session_id=session_id,
                kernel_id=kernel_id,
                code=code,
            )

        channels = await self._channels_cache.get(kernel_id)
        result = await self._executor.execute(code, timeout, channels)

        stdout = strip_ansi(result.stdout)
        stderr = strip_ansi(result.stderr)

        has_error = bool(stderr)
        has_result = result.result is not None
        logger.info(
            "execution done",
            session_id=session_id,
            kernel_id=kernel_id,
            result=has_result,
            stdout_bytes=len(stdout),
            stderr_bytes=len(stderr),
            images=len(result.images),
            error=has_error,
        )
        if logging.getLogger(__name__).isEnabledFor(logging.DEBUG):
            logger.debug(
                "execution output",
                session_id=session_id,
                kernel_id=kernel_id,
                result=result.result,
                stdout=stdout,
                stderr=stderr,
                images=len(result.images),
                error=has_error,
            )

        return result
