"""HTTP client for Jupyter Kernel Gateway REST API."""

from __future__ import annotations

import httpx
from structlog.stdlib import get_logger

from .. import config

logger = get_logger(__name__)


class KernelGatewayClient:
    """HTTP client for Jupyter Kernel Gateway operations."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
    ) -> None:
        self._base_url = (base_url or config.KERNEL_GATEWAY_URL).rstrip("/")
        self._token = token if token is not None else config.KERNEL_GATEWAY_TOKEN

    @property
    def base_url(self) -> str:
        if not self._base_url:
            raise RuntimeError("KERNEL_GATEWAY_URL is not set")
        return self._base_url

    @property
    def ws_url(self) -> str:
        """Convert HTTP URL to WebSocket URL."""
        url = self.base_url
        if url.startswith("https://"):
            return "wss://" + url.removeprefix("https://")
        if url.startswith("http://"):
            return "ws://" + url.removeprefix("http://")
        return url

    def _auth_headers(self) -> dict[str, str]:
        if not self._token:
            return {}
        return {"Authorization": f"token {self._token}"}

    async def create_kernel(self, name: str = "python3") -> str:
        """Create a new kernel and return its ID."""
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=20,
            headers=self._auth_headers(),
        ) as client:
            resp = await client.post("/api/kernels", json={"name": name})
            resp.raise_for_status()
            kernel_id = str(resp.json()["id"])
            return kernel_id

    async def delete_kernel(self, kernel_id: str) -> bool:
        """Delete a kernel. Returns True if successful."""
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=10,
            headers=self._auth_headers(),
        ) as client:
            try:
                resp = await client.delete(f"/api/kernels/{kernel_id}")
                resp.raise_for_status()
                return True
            except Exception as e:
                logger.warning(
                    "failed to delete kernel",
                    kernel_id=kernel_id,
                    error=str(e),
                )
                return False
