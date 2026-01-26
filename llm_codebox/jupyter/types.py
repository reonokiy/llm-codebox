"""Type definitions for Jupyter protocol messages and interfaces."""

from __future__ import annotations

from typing import Any, NotRequired, Protocol, TypedDict


class JupyterHeader(TypedDict):
    """Jupyter message header."""

    msg_id: str
    msg_type: str
    username: NotRequired[str]
    session: NotRequired[str]
    date: NotRequired[str]
    version: NotRequired[str]


class JupyterMessage(TypedDict):
    """Jupyter protocol message structure."""

    header: JupyterHeader
    parent_header: NotRequired[dict[str, str]]
    metadata: NotRequired[dict[str, Any]]
    content: NotRequired[dict[str, Any]]
    channel: NotRequired[str]
    buffers: NotRequired[list[Any]]


class StreamContent(TypedDict):
    """Content for stream message type."""

    name: str  # 'stdout' | 'stderr'
    text: str


class ErrorContent(TypedDict):
    """Content for error message type."""

    ename: str
    evalue: str
    traceback: NotRequired[list[str]]


class DisplayDataContent(TypedDict):
    """Content for display_data/execute_result message types."""

    data: dict[str, Any]
    metadata: NotRequired[dict[str, Any]]


class StatusContent(TypedDict):
    """Content for status message type."""

    execution_state: str  # 'busy' | 'idle' | 'starting'


class RedisClientProtocol(Protocol):
    """Protocol for Redis client interface."""

    def get(self, key: str) -> bytes | str | None: ...
    def set(
        self,
        key: str,
        value: str | bytes,
        ex: int | None = None,
    ) -> Any: ...
    def delete(self, *keys: str) -> Any: ...
    def keys(self, pattern: str = "*") -> list[bytes]: ...
