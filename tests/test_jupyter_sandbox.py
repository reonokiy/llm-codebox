"""Tests for /jupyter_sandbox endpoint (V1 format)."""

import uuid

import httpx


def test_jupyter_sandbox_v1_smoke(base_url: str):
    """Test basic V1 execution with result field."""
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{base_url}/jupyter_sandbox",
            json={"session_id": "itest-v1", "code": "x = 21\nx * 2", "timeout": 10.0},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "output" in data
    assert "result" in data["output"]
    assert "stdout" in data["output"]
    assert "stderr" in data["output"]


def test_jupyter_sandbox_v1_returns_result_field(base_url: str):
    """Test that V1 returns expression value in result field."""
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{base_url}/jupyter_sandbox",
            json={"session_id": "itest-v1-result", "code": "1 + 1", "timeout": 10.0},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["output"]["result"] is not None
    assert "2" in str(data["output"]["result"])


def test_jupyter_sandbox_v1_error_in_stderr(base_url: str):
    """Test that V1 captures errors in stderr."""
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{base_url}/jupyter_sandbox",
            json={"session_id": "itest-v1-error", "code": "1/0", "timeout": 10.0},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "ZeroDivisionError" in data["output"]["stderr"]


def test_v1_v2_output_consistency(base_url: str):
    """Test that V1 and V2 endpoints return consistent data for same code."""
    session_v1 = f"itest-v1v2-v1-{uuid.uuid4().hex[:8]}"
    session_v2 = f"itest-v1v2-v2-{uuid.uuid4().hex[:8]}"
    code = "x = 123\nprint('hello')\nx"

    with httpx.Client(timeout=30.0) as client:
        resp_v1 = client.post(
            f"{base_url}/jupyter_sandbox",
            json={"session_id": session_v1, "code": code, "timeout": 10.0},
        )
        resp_v2 = client.post(
            f"{base_url}/run_jupyter",
            json={"session_id": session_v2, "code": code, "timeout": 10.0},
        )

    assert resp_v1.status_code == 200
    assert resp_v2.status_code == 200

    data_v1 = resp_v1.json()
    data_v2 = resp_v2.json()

    # Both should have hello in stdout
    assert "hello" in data_v1["output"]["stdout"]
    assert "hello" in data_v2["output"]["stdout"]

    # V1 should have result field with 123
    assert data_v1["output"]["result"] is not None
    assert "123" in str(data_v1["output"]["result"])

    # V2 should have 123 in stdout (result merged into stdout)
    assert "123" in data_v2["output"]["stdout"]
