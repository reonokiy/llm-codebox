"""Tests for health check endpoint."""

import httpx


def test_health(base_url: str):
    """Test that health endpoint returns ok status."""
    with httpx.Client(timeout=5.0) as client:
        resp = client.get(f"{base_url}/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
