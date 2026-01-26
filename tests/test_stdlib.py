"""Tests for standard library and complex data structure handling."""

import uuid

import httpx


def test_import_and_use_stdlib(base_url: str):
    """Test importing and using standard library modules."""
    session_id = f"itest-stdlib-{uuid.uuid4().hex[:8]}"

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{base_url}/run_jupyter",
            json={
                "session_id": session_id,
                "code": """
import math
import random
random.seed(42)

print(f"Pi: {math.pi:.4f}")
print(f"Sqrt(2): {math.sqrt(2):.4f}")
print(f"Random: {random.randint(1, 100)}")
""",
                "timeout": 10.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "Pi: 3.141" in data["output"]["stdout"]
        assert "Sqrt(2): 1.4142" in data["output"]["stdout"]
        assert "Random:" in data["output"]["stdout"]


def test_complex_data_structures(base_url: str):
    """Test execution with complex nested data structures."""
    session_id = f"itest-complex-{uuid.uuid4().hex[:8]}"

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{base_url}/run_jupyter",
            json={
                "session_id": session_id,
                "code": """
import json
data = {
    'users': [
        {'name': 'Alice', 'scores': [95, 87, 92]},
        {'name': 'Bob', 'scores': [78, 85, 90]},
    ],
    'metadata': {'version': 1, 'created': '2024-01-01'}
}
print(json.dumps(data, indent=2))
""",
                "timeout": 10.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "Alice" in data["output"]["stdout"]
        assert "Bob" in data["output"]["stdout"]
        assert "scores" in data["output"]["stdout"]
