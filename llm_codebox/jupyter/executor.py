"""Jupyter code execution logic."""

from __future__ import annotations

import asyncio
import datetime as dt
import re
import time
import uuid
from typing import Any, cast

from .channels import KernelChannels
from .models import ExecuteResult
from .types import JupyterMessage


def strip_ansi(s: str) -> str:
    """Remove ANSI escape sequences from string."""
    ansi_escape = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
    return ansi_escape.sub("", s)


def _build_execute_request(code: str) -> tuple[str, JupyterMessage]:
    """Build a Jupyter execute_request message.

    Returns tuple of (msg_id, message).
    """
    msg_id = uuid.uuid4().hex
    session = uuid.uuid4().hex
    now = dt.datetime.now(tz=dt.timezone.utc).isoformat()

    message: JupyterMessage = {
        "header": {
            "msg_id": msg_id,
            "username": "",
            "session": session,
            "date": now,
            "msg_type": "execute_request",
            "version": "5.3",
        },
        "parent_header": {},
        "metadata": {},
        "content": {
            "code": code,
            "silent": False,
            "store_history": True,
            "user_expressions": {},
            "allow_stdin": False,
            "stop_on_error": False,
        },
        "channel": "shell",
        "buffers": [],
    }
    return msg_id, message


class ExecutionCollector:
    """Collects output from Jupyter kernel messages."""

    def __init__(self) -> None:
        self.stdout_parts: list[str] = []
        self.stderr_parts: list[str] = []
        self.images: list[str] = []
        self.result: str | None = None
        self._completed = False

    @property
    def completed(self) -> bool:
        return self._completed

    def process_message(self, msg: dict[str, Any]) -> None:
        """Process a single Jupyter message and extract output."""
        if msg.get("_ws_error"):
            self.stderr_parts.append(
                "WebSocket disconnected while waiting for output.\n"
            )
            self._completed = True
            return

        header = msg.get("header") or {}
        msg_type = header.get("msg_type")
        content = msg.get("content") or {}

        if msg_type == "stream":
            self._handle_stream(content)
        elif msg_type == "error":
            self._handle_error(content)
        elif msg_type in {"execute_result", "display_data"}:
            self._handle_display_data(content, msg_type)
        elif msg_type == "status" and content.get("execution_state") == "idle":
            self._completed = True

    def _handle_stream(self, content: dict[str, Any]) -> None:
        text = content.get("text", "")
        if text:
            if content.get("name") == "stderr":
                self.stderr_parts.append(text)
            else:
                self.stdout_parts.append(text)

    def _handle_error(self, content: dict[str, Any]) -> None:
        tb = content.get("traceback")
        if tb:
            self.stderr_parts.append("\n".join(str(x) for x in tb))
        else:
            ename = content.get("ename", "")
            evalue = content.get("evalue", "")
            self.stderr_parts.append(f"{ename}: {evalue}".strip())

    def _handle_display_data(
        self,
        content: dict[str, Any],
        msg_type: str,
    ) -> None:
        data = content.get("data") or {}

        if "image/png" in data:
            self.images.append(f"data:image/png;base64,{data['image/png']}")
        elif "image/jpeg" in data:
            self.images.append(f"data:image/jpeg;base64,{data['image/jpeg']}")
        elif "text/plain" in data:
            text = str(data["text/plain"])
            if msg_type == "execute_result":
                self.result = text
            else:
                self.stdout_parts.append(text)

    def to_result(self) -> ExecuteResult:
        """Convert collected output to unified result format."""
        return ExecuteResult(
            result=self.result,
            stdout="".join(self.stdout_parts),
            stderr="".join(self.stderr_parts),
            images=self.images,
        )


class JupyterExecutor:
    """Executes code on Jupyter kernels via WebSocket channels."""

    async def execute(
        self,
        code: str,
        timeout: float,
        channels: KernelChannels,
    ) -> ExecuteResult:
        """Execute code and return unified result format."""
        msg_id, request = _build_execute_request(code)
        deadline = time.monotonic() + max(0.1, timeout)
        collector = ExecutionCollector()

        queue = await channels.register_and_send(msg_id, cast(dict[str, Any], request))
        try:
            while not collector.completed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    collector.stderr_parts.append(
                        "Timed out waiting for Jupyter kernel output.\n"
                    )
                    break

                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=remaining)
                except asyncio.TimeoutError:
                    collector.stderr_parts.append(
                        "Timed out waiting for Jupyter kernel output.\n"
                    )
                    break

                collector.process_message(msg)
        finally:
            channels.unregister(msg_id)

        return collector.to_result()
