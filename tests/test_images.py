"""Tests for image output (matplotlib plots)."""

import base64
import uuid

import httpx


def test_matplotlib_image_output(base_url: str):
    """Test that matplotlib plots are returned as images in V2 format."""
    session_id = f"itest-plot-{uuid.uuid4().hex[:8]}"

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{base_url}/run_jupyter",
            json={
                "session_id": session_id,
                "code": """
%matplotlib inline
import matplotlib.pyplot as plt

plt.figure(figsize=(4, 3))
plt.plot([1, 2, 3, 4], [1, 4, 2, 3])
plt.title('Test Plot')
plt.show()
""",
                "timeout": 30.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert len(data["output"]["images"]) >= 1
        # V2 format includes data URI prefix
        assert data["output"]["images"][0].startswith("data:image/png;base64,")


def test_matplotlib_image_v1_format(base_url: str):
    """Test that V1 endpoint returns images as pure base64."""
    session_id = f"itest-plot-v1-{uuid.uuid4().hex[:8]}"

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{base_url}/jupyter_sandbox",
            json={
                "session_id": session_id,
                "code": """
%matplotlib inline
import matplotlib.pyplot as plt

plt.figure(figsize=(4, 3))
plt.bar(['A', 'B', 'C'], [3, 7, 5])
plt.title('Bar Chart')
plt.show()
""",
                "timeout": 30.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert len(data["output"]["images"]) >= 1
        # V1 format is pure base64 without data URI prefix
        img = data["output"]["images"][0]
        assert not img.startswith("data:")
        # Should be valid base64
        decoded = base64.b64decode(img)
        # PNG magic bytes
        assert decoded[:8] == b"\x89PNG\r\n\x1a\n"


def test_multiple_plots(base_url: str):
    """Test generating multiple plots in one execution."""
    session_id = f"itest-multi-plot-{uuid.uuid4().hex[:8]}"

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{base_url}/run_jupyter",
            json={
                "session_id": session_id,
                "code": """
%matplotlib inline
import matplotlib.pyplot as plt

# First plot
plt.figure()
plt.plot([1, 2, 3])
plt.title('Plot 1')
plt.show()

# Second plot
plt.figure()
plt.scatter([1, 2, 3], [3, 1, 2])
plt.title('Plot 2')
plt.show()
""",
                "timeout": 30.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert len(data["output"]["images"]) >= 2
