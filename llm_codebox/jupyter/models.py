"""Pydantic models for Jupyter execution results."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExecuteResult(BaseModel):
    """Internal unified execution result.

    This is the single format used throughout the jupyter package.
    API layer converts this to specific response formats as needed.
    """

    result: str | None = None
    stdout: str = ""
    stderr: str = ""
    images: list[str] = Field(default_factory=list)


class SessionInfo(BaseModel):
    """Information about an active session."""

    session_id: str
    kernel_id: str
    status: str = "active"
    idle_seconds: float = 0.0


class SessionsInfo(BaseModel):
    """Aggregated sessions information."""

    active_sessions: int
    max_sessions: int
    sessions: list[SessionInfo] = Field(default_factory=list)
