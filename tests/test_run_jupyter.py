"""Tests for /run_jupyter endpoint (V2 format)."""

import uuid

import httpx


def test_run_jupyter_smoke(base_url: str):
    """Test basic code execution with print output."""
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{base_url}/run_jupyter",
            json={"session_id": "itest-run", "code": "print('hi')", "timeout": 10.0},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "output" in data
    assert "stdout" in data["output"]
    assert "stderr" in data["output"]
    assert "images" in data["output"]
    assert "hi" in data["output"]["stdout"]


def test_run_jupyter_includes_result_in_stdout(base_url: str):
    """Test that expression results are included in stdout."""
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{base_url}/run_jupyter",
            json={"session_id": "itest-result", "code": "1 + 1", "timeout": 10.0},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["output"]["stderr"] == ""
    assert "2" in data["output"]["stdout"]


def test_run_jupyter_error_in_stderr(base_url: str):
    """Test that errors are captured in stderr."""
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{base_url}/run_jupyter",
            json={"session_id": "itest-error", "code": "1/0", "timeout": 10.0},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "ZeroDivisionError" in data["output"]["stderr"]


def test_run_jupyter_timeout(base_url: str):
    """Test that timeout is properly enforced."""
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{base_url}/run_jupyter",
            json={
                "session_id": "itest-timeout",
                "code": "import time\ntime.sleep(2)",
                "timeout": 0.2,
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "Timed out waiting for Jupyter kernel output" in data["output"]["stderr"]


def test_empty_code_rejected(base_url: str):
    """Test that empty code is rejected with validation error."""
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            f"{base_url}/run_jupyter",
            json={"session_id": "test-empty", "code": "   ", "timeout": 5.0},
        )
        assert resp.status_code == 422


def test_large_output(base_url: str):
    """Test handling of large output."""
    session_id = f"itest-large-{uuid.uuid4().hex[:8]}"

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{base_url}/run_jupyter",
            json={
                "session_id": session_id,
                "code": "print('x' * 10000)",
                "timeout": 10.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert len(data["output"]["stdout"]) >= 10000


def test_multiline_output(base_url: str):
    """Test execution with multiline output."""
    session_id = f"itest-multiline-{uuid.uuid4().hex[:8]}"

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{base_url}/run_jupyter",
            json={
                "session_id": session_id,
                "code": "for i in range(5):\n    print(f'Line {i}')",
                "timeout": 10.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        stdout = data["output"]["stdout"]
        for i in range(5):
            assert f"Line {i}" in stdout


def test_exception_traceback(base_url: str):
    """Test that exception tracebacks are properly captured."""
    session_id = f"itest-traceback-{uuid.uuid4().hex[:8]}"

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{base_url}/run_jupyter",
            json={
                "session_id": session_id,
                "code": """
def outer():
    inner()

def inner():
    raise ValueError("Something went wrong")

outer()
""",
                "timeout": 10.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        stderr = data["output"]["stderr"]
        assert "ValueError" in stderr
        assert "Something went wrong" in stderr
        assert "outer" in stderr
        assert "inner" in stderr
