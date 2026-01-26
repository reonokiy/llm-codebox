"""API endpoints for Jupyter code execution."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from . import config
from .jupyter import (
    ExecuteResult,
    clear_session,
    get_sessions_info,
    run_jupyter_code,
)
from .jupyter.executor import strip_ansi
from .jupyter.state_persistence import REDIS_STATE_PREFIX

if TYPE_CHECKING:
    import redis


class RunJupyterRequest(BaseModel):
    """Request model for code execution."""

    session_id: str = Field(default="JupyterSandboxDefault")
    code: str
    timeout: float = Field(default=5.0, gt=0)

    @field_validator("code")
    @classmethod
    def _non_empty_code(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("code must not be empty")
        return value


class JupyterOutputV2(BaseModel):
    """V2 output format with raw outputs."""

    stdout: str = ""
    stderr: str = ""
    stdout_raw: str = ""
    stderr_raw: str = ""
    images: list[str] = Field(default_factory=list)


class RunJupyterResponse(BaseModel):
    """Response model for V2 code execution."""

    output: JupyterOutputV2
    status: str
    execution_time: float


class JupyterOutputV1(BaseModel):
    """V1 output format with result field."""

    result: str | None = None
    stdout: str = ""
    stderr: str = ""
    images: list[str] = Field(default_factory=list)
    debug_info: dict[str, str] = Field(default_factory=lambda: {"msg": ""})


class RunJupyterResponseV1(BaseModel):
    """Response model for V1 code execution."""

    output: JupyterOutputV1
    status: str
    execution_time: float


class ClearSessionRequest(BaseModel):
    """Request model for clearing a session."""

    session_id: str = Field(default="JupyterSandboxDefault")


class ClearSessionResponse(BaseModel):
    """Response model for session clearing."""

    status: str


class HealthResponse(BaseModel):
    """Health check response."""

    status: str


class SessionInfo(BaseModel):
    """Information about a single session."""

    session_id: str
    kernel_id: str | None = None
    status: str
    idle_seconds: float | None = None


class SessionsResponse(BaseModel):
    """Response model for sessions listing."""

    active_sessions: int
    max_sessions: int
    sessions: list[SessionInfo]


def _to_output_v1(result: ExecuteResult) -> JupyterOutputV1:
    """Convert unified ExecuteResult to V1 output format."""
    return JupyterOutputV1(
        result=result.result,
        stdout=strip_ansi(result.stdout),
        stderr=strip_ansi(result.stderr),
        images=[img.split(",", 1)[-1] if "," in img else img for img in result.images],
        debug_info={"msg": ""},
    )


def _to_output_v2(result: ExecuteResult) -> JupyterOutputV2:
    """Convert unified ExecuteResult to V2 output format.

    V2 format includes result in stdout (with newline if needed).
    """
    stdout_raw = result.stdout
    if result.result is not None:
        text = result.result
        stdout_raw += text if text.endswith("\n") else f"{text}\n"

    return JupyterOutputV2(
        stdout=strip_ansi(stdout_raw),
        stderr=strip_ansi(result.stderr),
        stdout_raw=stdout_raw,
        stderr_raw=result.stderr,
        images=result.images,
    )


def create_router(
    redis_client: redis.Redis,  # type: ignore[type-arg]
    semaphore: asyncio.Semaphore,
) -> APIRouter:
    """Create API router with injected dependencies."""
    router = APIRouter()

    @router.post("/run_jupyter", response_model=RunJupyterResponse)
    async def run_jupyter_endpoint(request: RunJupyterRequest) -> RunJupyterResponse:
        """Execute Python code in a Jupyter kernel (V2 format)."""
        start_time = time.time()
        async with semaphore:
            result = await run_jupyter_code(
                redis_client,
                request.session_id,
                request.code,
                request.timeout,
            )
        execution_time = time.time() - start_time

        return RunJupyterResponse(
            output=_to_output_v2(result),
            status="success",
            execution_time=execution_time,
        )

    @router.post("/jupyter_sandbox", response_model=RunJupyterResponseV1)
    async def jupyter_sandbox_v1(request: RunJupyterRequest) -> RunJupyterResponseV1:
        """Execute Python code in a Jupyter kernel (V1 format)."""
        start_time = time.time()
        async with semaphore:
            result = await run_jupyter_code(
                redis_client,
                request.session_id,
                request.code,
                request.timeout,
            )
        execution_time = time.time() - start_time

        return RunJupyterResponseV1(
            output=_to_output_v1(result),
            status="success",
            execution_time=execution_time,
        )

    @router.post("/clear_session", response_model=ClearSessionResponse)
    async def clear_session_endpoint(
        request: ClearSessionRequest,
    ) -> ClearSessionResponse:
        """Clear a session and its associated kernel."""
        clear_session(request.session_id)
        with contextlib.suppress(Exception):
            redis_client.delete(f"{REDIS_STATE_PREFIX}{request.session_id}")
        return ClearSessionResponse(status="success")

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        """Health check endpoint."""
        return HealthResponse(status="ok")

    @router.get("/sessions", response_model=SessionsResponse)
    async def list_sessions() -> SessionsResponse:
        """List all active and persisted sessions."""
        info = get_sessions_info()
        sessions = [SessionInfo(**s) for s in info["sessions"]]

        with contextlib.suppress(Exception):
            keys: list[bytes] = redis_client.keys(f"{REDIS_STATE_PREFIX}*")  # type: ignore[assignment]
            prefix_len = len(REDIS_STATE_PREFIX)
            active_ids = {s.session_id for s in sessions}
            for k in keys:
                key_str = k.decode("utf-8") if isinstance(k, bytes) else k
                session_id = key_str[prefix_len:]
                if session_id not in active_ids:
                    sessions.append(
                        SessionInfo(
                            session_id=session_id,
                            kernel_id=None,
                            status="persisted",
                            idle_seconds=None,
                        )
                    )

        return SessionsResponse(
            active_sessions=info["active_sessions"],
            max_sessions=info["max_sessions"],
            sessions=sessions,
        )

    return router
