import asyncio
import contextlib
import datetime as _dt
import json
import logging
import re
import time
import uuid
from typing import Any

import httpx
import websockets

from . import config
from .internal_states import DUMP_VARS_CODE, LOAD_VARS_CODE

logger = logging.getLogger(__name__)


def _strip_ansi(s: str) -> str:
    ansi_escape = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
    return ansi_escape.sub("", s)


_BASE_URL = config.KERNEL_GATEWAY_URL
_TOKEN = config.KERNEL_GATEWAY_TOKEN

_KERNELS: dict[str, str] = {}
_KERNEL_LAST_USED: dict[str, float] = {}
_LOCKS: dict[str, asyncio.Lock] = {}
_CLEANUP_TASK: asyncio.Task | None = None

SESSION_TIMEOUT_SECONDS = 3600
MAX_ACTIVE_SESSIONS = config.MAX_ACTIVE_SESSIONS
REDIS_STATE_PREFIX = "jupyter_state:"
REDIS_STATE_TTL = 3600 * 6


def get_sessions_info() -> dict[str, Any]:
    now = time.monotonic()
    sessions = []
    for session_id, kernel_id in _KERNELS.items():
        last_used = _KERNEL_LAST_USED.get(session_id, now)
        idle_seconds = now - last_used
        sessions.append(
            {
                "session_id": session_id,
                "kernel_id": kernel_id,
                "status": "active",
                "idle_seconds": round(idle_seconds, 1),
            }
        )
    return {
        "active_sessions": len(sessions),
        "max_sessions": MAX_ACTIVE_SESSIONS,
        "sessions": sessions,
    }


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
    _KERNEL_LAST_USED.pop(session_id, None)
    _LOCKS.pop(session_id, None)
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


async def _dump_kernel_state(
    session_id: str, kernel_id: str, timeout: float = 30.0
) -> str | None:
    try:
        result = await _execute_v1(DUMP_VARS_CODE, timeout, kernel_id)
        stdout = result.get("stdout", "")
        if stdout:
            logger.info(
                f"[session={session_id}] dumped state, size={len(stdout)} bytes"
            )
            return stdout
        logger.warning(f"[session={session_id}] dump returned empty state")
        return None
    except Exception as e:
        logger.error(f"[session={session_id}] dump failed: {e}")
        return None


async def _load_kernel_state(
    session_id: str, kernel_id: str, state_b64: str, timeout: float = 30.0
) -> bool:
    try:
        code = LOAD_VARS_CODE.format(state_b64=state_b64)
        await _execute_v1(code, timeout, kernel_id)
        logger.info(
            f"[session={session_id}] restored state, size={len(state_b64)} bytes"
        )
        return True
    except Exception as e:
        logger.error(f"[session={session_id}] restore failed: {e}")
        return False


async def _evict_lru_session(redis_client: Any) -> None:
    if not _KERNEL_LAST_USED:
        return

    lru_session = min(_KERNEL_LAST_USED.items(), key=lambda x: x[1])[0]
    kernel_id = _KERNELS.get(lru_session)

    if kernel_id:
        logger.info(f"[session={lru_session}] evicting LRU session, kernel={kernel_id}")
        state = await _dump_kernel_state(lru_session, kernel_id)
        if state and redis_client:
            with contextlib.suppress(Exception):
                redis_client.set(
                    f"{REDIS_STATE_PREFIX}{lru_session}",
                    state,
                    ex=REDIS_STATE_TTL,
                )

    clear_session(lru_session)


async def _cleanup_expired_sessions() -> None:
    while True:
        await asyncio.sleep(60)
        now = time.monotonic()
        expired = [
            sid
            for sid, last_used in _KERNEL_LAST_USED.items()
            if now - last_used > SESSION_TIMEOUT_SECONDS
        ]
        for sid in expired:
            clear_session(sid)


def _ensure_cleanup_task() -> None:
    global _CLEANUP_TASK
    if _CLEANUP_TASK is None or _CLEANUP_TASK.done():
        try:
            loop = asyncio.get_running_loop()
            _CLEANUP_TASK = loop.create_task(_cleanup_expired_sessions())
        except RuntimeError:
            pass


async def _get_kernel_id(session_id: str, redis_client: Any = None) -> str:
    base_url = _require_base_url()
    lock = _LOCKS.setdefault(session_id, asyncio.Lock())

    async with lock:
        _KERNEL_LAST_USED[session_id] = time.monotonic()
        _ensure_cleanup_task()

        existing = _KERNELS.get(session_id)
        if existing:
            return existing

        if len(_KERNELS) >= MAX_ACTIVE_SESSIONS and redis_client:
            await _evict_lru_session(redis_client)

        async with httpx.AsyncClient(
            base_url=base_url, timeout=20, headers=_auth_headers()
        ) as client:
            resp = await client.post("/api/kernels", json={"name": "python3"})
            resp.raise_for_status()
            kernel_id = str(resp.json()["id"])
            _KERNELS[session_id] = kernel_id
            logger.info(f"[session={session_id}] started new kernel={kernel_id}")

            if redis_client:
                with contextlib.suppress(Exception):
                    state_b64 = redis_client.get(f"{REDIS_STATE_PREFIX}{session_id}")
                    if state_b64:
                        if isinstance(state_b64, bytes):
                            state_b64 = state_b64.decode("utf-8")
                        await _load_kernel_state(session_id, kernel_id, state_b64)
                        redis_client.delete(f"{REDIS_STATE_PREFIX}{session_id}")

            return kernel_id


async def _execute_v1(code: str, timeout: float, kernel_id: str) -> dict[str, Any]:
    """V1 format: result/stdout/stderr/images (pure base64)/debug_info."""
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
            "store_history": True,
            "user_expressions": {},
            "allow_stdin": False,
            "stop_on_error": False,
        },
        "channel": "shell",
        "buffers": [],
    }

    deadline = time.monotonic() + max(0.1, timeout)
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    images: list[str] = []
    result: str | None = None

    async with websockets.connect(
        ws_url,
        max_size=32 * 1024 * 1024,
        additional_headers=_auth_headers() or None,
    ) as sock:
        await sock.send(json.dumps(execute_request))

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                stderr_parts.append("Timed out waiting for Jupyter kernel output.\n")
                break

            try:
                raw = await asyncio.wait_for(sock.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                stderr_parts.append("Timed out waiting for Jupyter kernel output.\n")
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
                text = content.get("text", "")
                if text:
                    if content.get("name") == "stderr":
                        stderr_parts.append(text)
                    else:
                        stdout_parts.append(text)
            elif msg_type == "error":
                tb = content.get("traceback")
                if tb:
                    stderr_parts.append("\n".join(str(x) for x in tb))
                else:
                    ename = content.get("ename", "")
                    evalue = content.get("evalue", "")
                    stderr_parts.append(f"{ename}: {evalue}".strip())
            elif msg_type in {"execute_result", "display_data"}:
                data = content.get("data") or {}
                if "image/png" in data:
                    images.append(data["image/png"])
                elif "image/jpeg" in data:
                    images.append(data["image/jpeg"])
                elif "text/plain" in data:
                    if msg_type == "execute_result":
                        result = str(data["text/plain"])
                    else:
                        stdout_parts.append(str(data["text/plain"]))
            elif msg_type == "status" and content.get("execution_state") == "idle":
                break

    return {
        "result": result,
        "stdout": _strip_ansi("".join(stdout_parts)),
        "stderr": _strip_ansi("".join(stderr_parts)),
        "images": images,
        "debug_info": {"msg": ""},
    }


async def _execute(code: str, timeout: float, kernel_id: str) -> dict[str, Any]:
    """V2 format: stdout/stderr/stdout_raw/stderr_raw/images (with data URI prefix)."""
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
            "store_history": True,
            "user_expressions": {},
            "allow_stdin": False,
            "stop_on_error": False,
        },
        "channel": "shell",
        "buffers": [],
    }

    deadline = time.monotonic() + max(0.1, timeout)
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    images: list[str] = []

    async with websockets.connect(
        ws_url,
        max_size=32 * 1024 * 1024,
        additional_headers=_auth_headers() or None,
    ) as sock:
        await sock.send(json.dumps(execute_request))

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                stderr_parts.append("Timed out waiting for Jupyter kernel output.\n")
                break

            try:
                raw = await asyncio.wait_for(sock.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                stderr_parts.append("Timed out waiting for Jupyter kernel output.\n")
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
                text = content.get("text", "")
                if text:
                    if content.get("name") == "stderr":
                        stderr_parts.append(text)
                    else:
                        stdout_parts.append(text)
            elif msg_type == "error":
                tb = content.get("traceback")
                if tb:
                    stderr_parts.append("\n".join(str(x) for x in tb))
                else:
                    ename = content.get("ename", "")
                    evalue = content.get("evalue", "")
                    stderr_parts.append(f"{ename}: {evalue}".strip())
            elif msg_type in {"execute_result", "display_data"}:
                data = content.get("data") or {}
                if "image/png" in data:
                    images.append(f"data:image/png;base64,{data['image/png']}")
                elif "image/jpeg" in data:
                    images.append(f"data:image/jpeg;base64,{data['image/jpeg']}")
                elif "text/plain" in data:
                    text = data["text/plain"]
                    stdout_parts.append(text if text.endswith("\n") else f"{text}\n")
            elif msg_type == "status" and content.get("execution_state") == "idle":
                break

    stdout_raw = "".join(stdout_parts)
    stderr_raw = "".join(stderr_parts)

    return {
        "stdout": _strip_ansi(stdout_raw),
        "stderr": _strip_ansi(stderr_raw),
        "stdout_raw": stdout_raw,
        "stderr_raw": stderr_raw,
        "images": images,
    }


async def run_jupyter_code(
    redis_client: Any, session_id: str, code: str, timeout: float
) -> dict[str, Any]:
    kernel_id = await _get_kernel_id(session_id, redis_client)
    code_preview = code[:200] + "..." if len(code) > 200 else code
    logger.info(f"[session={session_id}] executing code: {code_preview!r}")
    result = await _execute(code, timeout, kernel_id)
    has_error = bool(result.get("stderr"))
    logger.info(
        f"[session={session_id}] execution done, "
        f"stdout={len(result.get('stdout', ''))}b, "
        f"stderr={len(result.get('stderr', ''))}b, "
        f"images={len(result.get('images', []))}, "
        f"error={has_error}"
    )
    return result


async def run_jupyter_code_v1(
    redis_client: Any, session_id: str, code: str, timeout: float
) -> dict[str, Any]:
    kernel_id = await _get_kernel_id(session_id, redis_client)
    code_preview = code[:200] + "..." if len(code) > 200 else code
    logger.info(f"[session={session_id}] executing code (v1): {code_preview!r}")
    result = await _execute_v1(code, timeout, kernel_id)
    has_error = bool(result.get("stderr"))
    has_result = result.get("result") is not None
    logger.info(
        f"[session={session_id}] execution done (v1), "
        f"result={has_result}, "
        f"stdout={len(result.get('stdout', ''))}b, "
        f"stderr={len(result.get('stderr', ''))}b, "
        f"images={len(result.get('images', []))}, "
        f"error={has_error}"
    )
    return result
