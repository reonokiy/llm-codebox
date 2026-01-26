"""Tests for session management endpoints and behavior."""

import concurrent.futures
import time
import uuid

import httpx
import pytest


def test_sessions_schema(base_url: str):
    """Test that /sessions returns expected schema."""
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
    """Test clearing a session."""
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


def test_session_variable_persistence(base_url: str):
    """Test that variables persist across multiple executions in same session."""
    session_id = f"itest-persist-{uuid.uuid4().hex[:8]}"

    with httpx.Client(timeout=30.0) as client:
        # First execution: define variables
        resp = client.post(
            f"{base_url}/run_jupyter",
            json={
                "session_id": session_id,
                "code": "counter = 0\ndef increment():\n    global counter\n    counter += 1\n    return counter",
                "timeout": 10.0,
            },
        )
        assert resp.status_code == 200

        # Second execution: use the function
        resp = client.post(
            f"{base_url}/run_jupyter",
            json={
                "session_id": session_id,
                "code": "print(increment())\nprint(increment())\nprint(increment())",
                "timeout": 10.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "1" in data["output"]["stdout"]
        assert "2" in data["output"]["stdout"]
        assert "3" in data["output"]["stdout"]

        # Third execution: verify counter value
        resp = client.post(
            f"{base_url}/run_jupyter",
            json={
                "session_id": session_id,
                "code": "print(f'Final counter: {counter}')",
                "timeout": 10.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "Final counter: 3" in data["output"]["stdout"]


def test_class_definition_and_use(base_url: str):
    """Test defining and using a class across executions."""
    session_id = f"itest-class-{uuid.uuid4().hex[:8]}"

    with httpx.Client(timeout=30.0) as client:
        # Define a class
        resp = client.post(
            f"{base_url}/run_jupyter",
            json={
                "session_id": session_id,
                "code": """
class Counter:
    def __init__(self, start=0):
        self.value = start
    
    def increment(self, by=1):
        self.value += by
        return self.value
    
    def __repr__(self):
        return f"Counter({self.value})"

c = Counter(10)
""",
                "timeout": 10.0,
            },
        )
        assert resp.status_code == 200

        # Use the class
        resp = client.post(
            f"{base_url}/run_jupyter",
            json={
                "session_id": session_id,
                "code": "print(c.increment(5))\nprint(c.increment())\nprint(c)",
                "timeout": 10.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        stdout = data["output"]["stdout"]
        assert "15" in stdout
        assert "16" in stdout
        assert "Counter(16)" in stdout


def test_concurrent_sessions(base_url: str):
    """Test running multiple sessions concurrently."""
    prefix = f"itest-concurrent-{uuid.uuid4().hex[:8]}-"
    num_sessions = 3

    def run_session(session_num: int) -> dict:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{base_url}/run_jupyter",
                json={
                    "session_id": f"{prefix}{session_num}",
                    "code": f"result = {session_num} * 10\nprint(result)",
                    "timeout": 10.0,
                },
            )
            return {"session": session_num, "response": resp.json()}

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_sessions) as executor:
        futures = [executor.submit(run_session, i) for i in range(num_sessions)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    for result in results:
        session_num = result["session"]
        expected = str(session_num * 10)
        assert expected in result["response"]["output"]["stdout"]


def test_session_eviction_lru(clean_server: str):
    """Test LRU eviction when max sessions is reached."""
    base_url = clean_server
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{base_url}/sessions")
        assert resp.status_code == 200
        info = resp.json()

    assert info["active_sessions"] == 0, "clean_server fixture should clear sessions"

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


def test_state_persistence_after_eviction(clean_server: str):
    """Test that session state is preserved after eviction and restored on reuse."""
    base_url = clean_server
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{base_url}/sessions")
        assert resp.status_code == 200
        info = resp.json()

    assert info["active_sessions"] == 0, "clean_server fixture should clear sessions"

    max_sessions = int(info["max_sessions"])
    if max_sessions <= 0:
        pytest.skip("max_sessions is not positive")

    prefix = f"itest-state-{uuid.uuid4().hex[:8]}-"
    target_session = f"{prefix}target"

    with httpx.Client(timeout=30.0) as client:
        # Create target session with complex state
        resp = client.post(
            f"{base_url}/run_jupyter",
            json={
                "session_id": target_session,
                "code": "my_list = [1, 2, 3]\nmy_dict = {'a': 1, 'b': 2}\nmy_value = 42",
                "timeout": 10.0,
            },
        )
        assert resp.status_code == 200

        # Create enough sessions to evict the target
        for i in range(max_sessions + 1):
            resp = client.post(
                f"{base_url}/run_jupyter",
                json={
                    "session_id": f"{prefix}filler-{i}",
                    "code": "x = 1",
                    "timeout": 10.0,
                },
            )
            assert resp.status_code == 200

    time.sleep(0.3)

    # Verify target was evicted
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{base_url}/sessions")
        assert resp.status_code == 200
        data = resp.json()

    target_info = next(
        (s for s in data["sessions"] if s["session_id"] == target_session), None
    )
    assert target_info is not None
    assert target_info["status"] == "persisted"

    # Reactivate the target session and verify state was restored
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{base_url}/run_jupyter",
            json={
                "session_id": target_session,
                "code": "(my_list, my_dict, my_value)",
                "timeout": 10.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        # The restored state should have the variables
        stdout = data["output"]["stdout"]
        assert "[1, 2, 3]" in stdout
        assert "'a'" in stdout
        assert "42" in stdout
