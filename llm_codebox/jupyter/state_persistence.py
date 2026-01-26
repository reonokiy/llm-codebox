"""Kernel state persistence via Redis."""

from __future__ import annotations

import contextlib
import re
from typing import TYPE_CHECKING

from structlog.stdlib import get_logger

from .internal_states import DUMP_VARS_CODE, LOAD_VARS_CODE

if TYPE_CHECKING:
    from .channels import KernelChannels
    from .executor import JupyterExecutor
    from .types import RedisClientProtocol

logger = get_logger(__name__)

REDIS_STATE_PREFIX = "jupyter_state:"
REDIS_STATE_TTL = 3600 * 6


class StatePersistence:
    """Handles kernel state serialization and restoration."""

    def __init__(self, executor: JupyterExecutor) -> None:
        self._executor = executor

    async def dump_state(
        self,
        session_id: str,
        channels: KernelChannels,
        timeout: float = 30.0,
    ) -> str | None:
        """Dump kernel state to base64-encoded string."""
        try:
            result = await self._executor.execute(DUMP_VARS_CODE, timeout, channels)
            state_b64 = self._extract_state(result.stdout, result.result)

            if state_b64:
                logger.info(
                    "state dumped",
                    session_id=session_id,
                    state_size_bytes=len(state_b64),
                )
                return state_b64

            if result.stderr:
                logger.warning(
                    "dump returned empty state",
                    session_id=session_id,
                    stderr_preview=result.stderr[:500],
                )
            else:
                logger.warning("dump returned empty state", session_id=session_id)
            return None
        except Exception as e:
            logger.exception("dump failed", session_id=session_id, error=str(e))
            return None

    async def load_state(
        self,
        session_id: str,
        channels: KernelChannels,
        state_b64: str,
        timeout: float = 30.0,
    ) -> bool:
        """Load kernel state from base64-encoded string."""
        try:
            code = LOAD_VARS_CODE.format(state_b64=state_b64)
            await self._executor.execute(code, timeout, channels)
            logger.info(
                "state restored",
                session_id=session_id,
                state_size_bytes=len(state_b64),
            )
            return True
        except Exception as e:
            logger.exception("restore failed", session_id=session_id, error=str(e))
            return False

    def save_to_redis(
        self,
        redis_client: RedisClientProtocol,
        session_id: str,
        state_b64: str,
    ) -> bool:
        """Save state to Redis."""
        try:
            redis_client.set(
                f"{REDIS_STATE_PREFIX}{session_id}",
                state_b64,
                ex=REDIS_STATE_TTL,
            )
            return True
        except Exception:
            return False

    def load_from_redis(
        self,
        redis_client: RedisClientProtocol,
        session_id: str,
    ) -> str | None:
        """Load state from Redis."""
        with contextlib.suppress(Exception):
            state = redis_client.get(f"{REDIS_STATE_PREFIX}{session_id}")
            if state:
                if isinstance(state, bytes):
                    return state.decode("utf-8")
                return state
        return None

    def delete_from_redis(
        self,
        redis_client: RedisClientProtocol,
        session_id: str,
    ) -> None:
        """Delete state from Redis."""
        with contextlib.suppress(Exception):
            redis_client.delete(f"{REDIS_STATE_PREFIX}{session_id}")

    def _extract_state(self, stdout: str, result: str | None) -> str | None:
        """Extract base64 state from execution output."""
        if stdout:
            return stdout.strip()

        if isinstance(result, str) and result:
            raw = result.strip()
            # Remove quotes if present
            if (
                len(raw) >= 2
                and raw[0] == raw[-1]
                and raw[0] in {"'", '"'}
                and re.fullmatch(r"[A-Za-z0-9+/=]+", raw[1:-1] or "")
            ):
                raw = raw[1:-1]
            if re.fullmatch(r"[A-Za-z0-9+/=]+", raw):
                return raw
        return None
