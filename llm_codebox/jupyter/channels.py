"""WebSocket channel management for Jupyter kernel communication."""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from typing import Any

import websockets
from websockets import State


@dataclass
class PendingExecution:
    """Tracks a pending execution request."""

    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)


class KernelChannels:
    """Manages WebSocket connection to a Jupyter kernel.

    Handles message routing based on parent_header msg_id for tracking
    responses to specific execution requests.
    """

    def __init__(self, ws_url: str, headers: dict[str, str]) -> None:
        self._ws_url = ws_url
        self._headers = headers
        self._ws: Any = None
        self._recv_task: asyncio.Task[None] | None = None
        self._send_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._pending: dict[str, PendingExecution] = {}
        self._active_order: list[str] = []

    async def ensure_connected(self) -> None:
        """Ensure WebSocket connection is established."""
        async with self._state_lock:
            if self._ws is not None and self._ws.state == State.OPEN:
                return
            self._ws = await websockets.connect(
                self._ws_url,
                max_size=32 * 1024 * 1024,
                additional_headers=self._headers or None,
            )
            self._recv_task = asyncio.create_task(self._recv_loop())

    async def close(self) -> None:
        """Close the WebSocket connection."""
        async with self._state_lock:
            await self._fail_all(RuntimeError("kernel websocket closed"))
            ws = self._ws
            self._ws = None
            task = self._recv_task
            self._recv_task = None

        if task is not None:
            task.cancel()
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()

    async def register_and_send(
        self,
        msg_id: str,
        payload: dict[str, Any],
    ) -> asyncio.Queue[dict[str, Any]]:
        """Register an execution and send the request message.

        Returns a queue that will receive response messages.
        """
        await self.ensure_connected()
        pending = PendingExecution()
        self._pending[msg_id] = pending

        async with self._send_lock:
            assert self._ws is not None
            try:
                await self._ws.send(json.dumps(payload))
            except Exception:
                self._pending.pop(msg_id, None)
                raise
            self._active_order.append(msg_id)
        return pending.queue

    def unregister(self, msg_id: str) -> None:
        """Unregister a completed execution."""
        self._pending.pop(msg_id, None)
        with contextlib.suppress(ValueError):
            self._active_order.remove(msg_id)

    async def _fail_all(self, exc: Exception) -> None:
        """Signal error to all pending executions."""
        for pending in self._pending.values():
            with contextlib.suppress(Exception):
                pending.queue.put_nowait({"_ws_error": str(exc)})
        self._pending.clear()
        self._active_order.clear()

    async def _recv_loop(self) -> None:
        """Background task to receive and route messages."""
        assert self._ws is not None
        ws = self._ws
        try:
            while True:
                raw = await ws.recv()
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue

                self._route_message(msg)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self._fail_all(e)

    def _route_message(self, msg: dict[str, Any]) -> None:
        """Route a received message to the appropriate pending execution."""
        parent = (msg.get("parent_header") or {}).get("msg_id")
        header = msg.get("header") or {}
        msg_type = header.get("msg_type")
        content = msg.get("content") or {}

        # Route message to its parent execution if we're tracking it
        if parent and parent in self._pending:
            self._pending[parent].queue.put_nowait(msg)

            if msg_type == "status" and content.get("execution_state") == "idle":
                self._advance_fifo(parent)
            return

        # Handle status messages WITHOUT parent_header only
        # (some IOPub status messages don't include parent_header)
        if msg_type == "status" and not parent and self._active_order:
            current = self._active_order[0]
            if pending := self._pending.get(current):
                pending.queue.put_nowait(msg)
            if content.get("execution_state") == "idle":
                self._active_order.pop(0)

    def _advance_fifo(self, msg_id: str) -> None:
        """Advance the FIFO queue when an execution completes."""
        if self._active_order and self._active_order[0] == msg_id:
            self._active_order.pop(0)
        else:
            with contextlib.suppress(ValueError):
                self._active_order.remove(msg_id)


class KernelChannelsCache:
    """Cache for kernel WebSocket channels."""

    def __init__(self, gateway_ws_url: str, auth_headers: dict[str, str]) -> None:
        self._gateway_ws_url = gateway_ws_url
        self._auth_headers = auth_headers
        self._channels: dict[str, KernelChannels] = {}
        self._lock = asyncio.Lock()

    async def get(self, kernel_id: str) -> KernelChannels:
        """Get or create a channel for the given kernel."""
        async with self._lock:
            if existing := self._channels.get(kernel_id):
                return existing

            ws_url = f"{self._gateway_ws_url}/api/kernels/{kernel_id}/channels"
            channel = KernelChannels(ws_url=ws_url, headers=self._auth_headers)
            self._channels[kernel_id] = channel
            return channel

    async def close(self, kernel_id: str) -> None:
        """Close and remove a channel."""
        async with self._lock:
            channel = self._channels.pop(kernel_id, None)
        if channel is not None:
            await channel.close()

    async def close_all(self) -> None:
        """Close all channels."""
        async with self._lock:
            channels = list(self._channels.values())
            self._channels.clear()
        for channel in channels:
            await channel.close()
