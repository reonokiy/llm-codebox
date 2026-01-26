"""Jupyter kernel management package.

This package provides a clean interface for managing Jupyter kernels,
executing code, and handling session state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .manager import KernelSessionManager
from .models import ExecuteResult

if TYPE_CHECKING:
    from .types import RedisClientProtocol

__all__ = [
    "ExecuteResult",
    "run_jupyter_code",
    "clear_session",
    "get_sessions_info",
]

_manager: KernelSessionManager | None = None


def _get_manager() -> KernelSessionManager:
    global _manager
    if _manager is None:
        _manager = KernelSessionManager()
    return _manager


async def run_jupyter_code(
    redis_client: RedisClientProtocol | Any,
    session_id: str,
    code: str,
    timeout: float,
) -> ExecuteResult:
    """Execute code in a Jupyter kernel."""
    return await _get_manager().execute(redis_client, session_id, code, timeout)


def clear_session(session_id: str) -> None:
    """Clear a session and its associated kernel."""
    _get_manager().clear_session(session_id)


def get_sessions_info() -> dict[str, Any]:
    """Get information about all active sessions."""
    return _get_manager().get_sessions_info()
