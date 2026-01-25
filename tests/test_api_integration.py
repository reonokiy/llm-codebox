import os
import time
import uuid

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


@pytest.fixture(scope="session")
def base_url() -> str:
    url = _base_url()
    if not _is_reachable(url):
        pytest.skip(f"server not reachable at {url} (set CODEBOX_BASE_URL)")
    return url


def test_health(base_url: str):
    with httpx.Client(timeout=5.0) as client:
        resp = client.get(f"{base_url}/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_run_jupyter_smoke(base_url: str):
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


def test_jupyter_sandbox_v1_smoke(base_url: str):
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
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{base_url}/jupyter_sandbox",
            json={"session_id": "itest-v1-error", "code": "1/0", "timeout": 10.0},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "ZeroDivisionError" in data["output"]["stderr"]


def test_sessions_schema(base_url: str):
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{base_url}/sessions")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data.get("active_sessions"), int)
    assert isinstance(data.get("max_sessions"), int)
    assert isinstance(data.get("sessions"), list)
    for s in data["sessions"]:
        assert "session_id" in s
        assert "status" in s
        assert "kernel_id" in s
        assert "idle_seconds" in s
        if s["status"] == "persisted":
            assert s["kernel_id"] is None
            assert s["idle_seconds"] is None


def test_clear_session(base_url: str):
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{base_url}/run_jupyter",
            json={"session_id": "itest-clear", "code": "x = 1", "timeout": 10.0},
        )
        assert resp.status_code == 200

        resp = client.post(
            f"{base_url}/clear_session",
            json={"session_id": "itest-clear"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"status": "success"}


def test_session_eviction_lru(base_url: str):
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{base_url}/sessions")
        assert resp.status_code == 200
        info = resp.json()

    if info["active_sessions"] != 0:
        pytest.skip("eviction test requires a clean server (active_sessions==0)")

    max_sessions = int(info["max_sessions"])
    if max_sessions <= 0:
        pytest.skip("max_sessions is not positive")

    prefix = f"itest-evict-{uuid.uuid4().hex[:8]}-"
    session_ids = [f"{prefix}{i}" for i in range(max_sessions + 2)]

    with httpx.Client(timeout=30.0) as client:
        for sid in session_ids:
            resp = client.post(
                f"{base_url}/run_jupyter",
                json={"session_id": sid, "code": "a = 1\na", "timeout": 10.0},
            )
            assert resp.status_code == 200

    time.sleep(0.2)

    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{base_url}/sessions")
        assert resp.status_code == 200
        data = resp.json()

    ours = [s for s in data["sessions"] if s.get("session_id", "").startswith(prefix)]
    ours_by_id = {s["session_id"]: s for s in ours}
    for sid in session_ids:
        assert sid in ours_by_id

    active = [s for s in ours if s["status"] == "active"]
    persisted = [s for s in ours if s["status"] == "persisted"]

    assert len(active) == max_sessions
    assert len(persisted) == 2
    for s in persisted:
        assert s["kernel_id"] is None
        assert s["idle_seconds"] is None
