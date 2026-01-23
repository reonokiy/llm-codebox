import asyncio
import contextlib
import datetime as _dt
import json
import time
import uuid
from typing import Any

import httpx
import websockets

from . import config


_BASE_URL = config.KERNEL_GATEWAY_URL
_TOKEN = config.KERNEL_GATEWAY_TOKEN

_KERNELS: dict[str, str] = {}
_LOCKS: dict[str, asyncio.Lock] = {}


def _require_base_url() -> str:
    if not _BASE_URL:
        raise RuntimeError("KERNEL_GATEWAY_URL is not set")
    return _BASE_URL


def _auth_headers() -> dict[str, str]:
    # Jupyter Server accepts: Authorization: token <token>
    if not _TOKEN:
        return {}
    return {"Authorization": f"token {_TOKEN}"}


def _ws_url(http_url: str) -> str:
    if http_url.startswith("https://"):
        return "wss://" + http_url.removeprefix("https://")
    if http_url.startswith("http://"):
        return "ws://" + http_url.removeprefix("http://")
    return http_url


def clear_session(session_id: str) -> None:
    kernel_id = _KERNELS.pop(session_id, None)
    if not kernel_id:
        return

    base_url = _BASE_URL
    if not base_url:
        return

    async def _delete() -> None:
        async with httpx.AsyncClient(
            base_url=base_url, timeout=10, headers=_auth_headers()
        ) as client:
            with contextlib.suppress(Exception):
                await client.delete(f"/api/kernels/{kernel_id}")

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_delete())
    else:
        loop.create_task(_delete())


async def _get_kernel_id(session_id: str) -> str:
    base_url = _require_base_url()
    lock = _LOCKS.setdefault(session_id, asyncio.Lock())

    async with lock:
        existing = _KERNELS.get(session_id)
        if existing:
            return existing

        async with httpx.AsyncClient(
            base_url=base_url, timeout=20, headers=_auth_headers()
        ) as client:
            resp = await client.post("/api/kernels", json={"name": "python3"})
            resp.raise_for_status()
            kernel_id = str(resp.json()["id"])
            _KERNELS[session_id] = kernel_id
            return kernel_id


async def _execute(code: str, timeout: float, kernel_id: str) -> str:
    base_url = _require_base_url()
    ws = _ws_url(base_url)
    ws_url = f"{ws}/api/kernels/{kernel_id}/channels"

    msg_id = uuid.uuid4().hex
    session = uuid.uuid4().hex
    now = _dt.datetime.now(tz=_dt.timezone.utc).isoformat()

    execute_request = {
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
            "store_history": False,
            "user_expressions": {},
            "allow_stdin": False,
            "stop_on_error": True,
        },
        "channel": "shell",
        "buffers": [],
    }

    deadline = time.monotonic() + max(0.1, timeout)
    chunks: list[str] = []

    async with websockets.connect(
        ws_url,
        max_size=32 * 1024 * 1024,
        additional_headers=_auth_headers() or None,
    ) as sock:
        await sock.send(json.dumps(execute_request))

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                chunks.append("Error: execution timed out")
                break

            try:
                raw = await asyncio.wait_for(sock.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                chunks.append("Error: execution timed out")
                break

            try:
                msg = json.loads(raw)
            except Exception:
                continue

            parent = (msg.get("parent_header") or {}).get("msg_id")
            if parent != msg_id:
                continue

            msg_type = (msg.get("header") or {}).get("msg_type")
            content = msg.get("content") or {}

            if msg_type == "stream":
                text = content.get("text")
                if text:
                    chunks.append(str(text))
            elif msg_type in {"execute_result", "display_data"}:
                data = content.get("data") or {}
                if "text/plain" in data:
                    chunks.append(str(data["text/plain"]))
            elif msg_type == "error":
                tb = content.get("traceback") or []
                chunks.append("\n".join(str(x) for x in tb) or "Error")
            elif msg_type == "status" and content.get("execution_state") == "idle":
                break

    return "".join(chunks).strip()


async def run_jupyter_code(
    redis_client: Any, session_id: str, code: str, timeout: float
) -> str:
    # Best-effort: keep a marker in Redis so callers can observe sessions.
    with contextlib.suppress(Exception):
        redis_client.set(session_id, b"1", ex=3600)

    kernel_id = await _get_kernel_id(session_id)
    return await _execute(code, timeout, kernel_id)
