"""Shared pytest fixtures for integration tests."""

import os
from typing import Generator

import httpx
import pytest


def _base_url() -> str:
    return os.environ.get("CODEBOX_BASE_URL", "http://localhost:12345").rstrip("/")


def _is_reachable(url: str) -> bool:
    try:
        with httpx.Client(timeout=2.0) as client:
            resp = client.get(f"{url}/health")
            return resp.status_code == 200
    except Exception:
        return False


def _clear_all_test_sessions(url: str) -> None:
    """Clear all sessions with 'itest' prefix."""
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{url}/sessions")
        if resp.status_code != 200:
            return
        data = resp.json()
        for session in data.get("sessions", []):
            session_id = session.get("session_id", "")
            if session_id.startswith("itest"):
                client.post(f"{url}/clear_session", json={"session_id": session_id})


@pytest.fixture(scope="session")
def base_url() -> str:
    """Fixture providing the base URL for API tests.

    Skips all tests if the server is not reachable.
    Set CODEBOX_BASE_URL environment variable to override the default.
    """
    url = _base_url()
    if not _is_reachable(url):
        pytest.skip(f"server not reachable at {url} (set CODEBOX_BASE_URL)")
    return url


@pytest.fixture
def clean_server(base_url: str) -> Generator[str, None, None]:
    """Fixture that ensures a clean server state (no active sessions).

    Clears all test sessions before and after the test.
    """
    _clear_all_test_sessions(base_url)
    yield base_url
    _clear_all_test_sessions(base_url)
