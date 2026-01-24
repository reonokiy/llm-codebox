# llm-codebox

A lightweight code-execution sandbox that exposes a FastAPI service backed by a
Jupyter Kernel Gateway and Redis (Valkey). The current codebase is adapted from
https://github.com/ChenShawn/MultiModal-Jupyter-Sandbox.

## Architecture

- `app`: FastAPI server (`llm_codebox.main`) that forwards code to Jupyter.
- `jupyter`: Jupyter Kernel Gateway for executing Python code (with GPU support).
- `valkey`: Redis-compatible store for session markers.

Default setup uses the [Jupyter Kernel Gateway](https://github.com/jupyter-server/kernel_gateway). If you need scalable compute,
deploy your own [enterprise gateway](https://github.com/jupyter-server/enterprise_gateway) and point `KERNEL_GATEWAY_URL` to it.

## Quick start (Docker Compose)

```bash
docker compose up --build
```

The API will be available at `http://localhost:12345`.

### GPU Support

The jupyter container is configured to use all available NVIDIA GPUs. Prerequisites:

1. NVIDIA driver installed on host
2. Install nvidia-container-toolkit:
   ```bash
   sudo apt install nvidia-container-toolkit
   sudo systemctl restart docker
   ```

To use specific GPUs, edit `docker-compose.yaml`:

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 2              # use 2 GPUs
          # or
          device_ids: ["0", "2"] # use specific GPUs
          capabilities: [gpu]
```

### Pre-installed Packages

The Jupyter container comes with common data science packages pre-installed (numpy, pandas, matplotlib, scikit-learn, torch, etc.). See [`jupyter-gateway/requirements.txt`](./jupyter-gateway/requirements.txt) for the full list.

## API

### `POST /jupyter_sandbox` (V1)

Execute Python code with structured output (separates result, stdout, stderr, images).

Request body:
```json
{
  "session_id": "optional-session-id",
  "code": "x = 42\nprint('hello')\nx",
  "timeout": 5.0
}
```

Response body:
```json
{
  "output": {
    "result": "42",
    "stdout": "hello\n",
    "stderr": "",
    "images": ["iVBORw0KGgo..."],
    "debug_info": {"msg": ""}
  },
  "status": "success",
  "execution_time": 0.123
}
```

| Field | Description |
|-------|-------------|
| `result` | Last expression value (like Jupyter cell output) |
| `stdout` | print() output |
| `stderr` | Error messages / tracebacks |
| `images` | Base64-encoded images from matplotlib, etc. |

### `POST /run_jupyter` (V2)

Execute Python code with combined output format.

Request body:
```json
{
  "session_id": "optional-session-id",
  "code": "print('hello')",
  "timeout": 5.0
}
```

Response body:
```json
{
  "output": {
    "stdout": "hello\n42\n",
    "stderr": "",
    "stdout_raw": "hello\n42\n",
    "stderr_raw": "",
    "images": ["data:image/png;base64,iVBORw0KGgo..."]
  },
  "status": "success",
  "execution_time": 0.123
}
```

| Field | Description |
|-------|-------------|
| `stdout` | Combined print() output + expression values (ANSI stripped) |
| `stderr` | Error messages (ANSI stripped) |
| `stdout_raw` | Raw stdout with ANSI codes |
| `stderr_raw` | Raw stderr with ANSI codes |
| `images` | Images with data URI prefix |

### V1 vs V2 Differences

| Feature | V1 (`/jupyter_sandbox`) | V2 (`/run_jupyter`) |
|---------|-------------------------|---------------------|
| `result` field | Yes (separate) | No (merged into stdout) |
| Image format | Pure base64 | Data URI (`data:image/png;base64,...`) |
| ANSI codes | Stripped | Both raw and stripped available |
| `debug_info` | Yes | No |

Notes:
- `session_id` defaults to `JupyterSandboxDefault` if omitted.
- `timeout` defaults to `5.0` seconds.

### `POST /clear_session`

Clear a kernel session and delete its marker from Redis.

Request body:
```json
{
  "session_id": "optional-session-id"
}
```

Response body:
```json
{
  "status": "success"
}
```

### `GET /health`

Health check endpoint.

Response body:
```json
{
  "status": "ok"
}
```

### `GET /sessions`

List all active and persisted sessions.

Response body:
```json
{
  "active_sessions": 2,
  "max_sessions": 16,
  "sessions": [
    {
      "session_id": "abc123",
      "kernel_id": "kernel-uuid-1",
      "status": "active",
      "idle_seconds": 45.2
    },
    {
      "session_id": "xyz789",
      "kernel_id": null,
      "status": "persisted",
      "idle_seconds": null
    }
  ]
}
```

| Status | Description |
|--------|-------------|
| `active` | Kernel is running, `kernel_id` and `idle_seconds` available |
| `persisted` | Kernel was evicted, state saved to Redis, will restore on next request |

## Configuration

Environment variables used by the FastAPI service:

- `KERNEL_GATEWAY_URL` (required): Base URL for the Jupyter Kernel Gateway.
- `KERNEL_GATEWAY_TOKEN` (optional): Token for the Kernel Gateway auth header.
- `REDIS_URL` (optional): Full Redis connection URL.
- `REDIS_HOST` (default: `valkey`)
- `REDIS_PORT` (default: `6379`)
- `REDIS_DB` (default: `0`)
- `APP_PORT` (default: `12345`)
- `MAX_CONCURRENT_RUNS` (default: `4`): Maximum concurrent code executions.
- `MAX_ACTIVE_SESSIONS` (default: `MAX_CONCURRENT_RUNS`): Maximum active kernel sessions. When exceeded, LRU session is evicted to Redis.

The provided `docker-compose.yaml` sets defaults for local usage.

## Local development (without Docker)

1. Ensure you have a running Jupyter Kernel Gateway and Redis-compatible server.
2. Set `KERNEL_GATEWAY_URL` and Redis settings.
3. Run:

```bash
uvicorn llm_codebox.main:app --host 0.0.0.0 --port 12345
```
