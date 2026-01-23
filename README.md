# llm-codebox

A lightweight code-execution sandbox that exposes a FastAPI service backed by a
Jupyter Kernel Gateway and Redis (Valkey). The current codebase is adapted from
https://github.com/ChenShawn/MultiModal-Jupyter-Sandbox.

## Architecture

- `app`: FastAPI server (`llm_codebox.main`) that forwards code to Jupyter.
- `jupyter`: Jupyter Kernel Gateway for executing Python code.
- `valkey`: Redis-compatible store for session markers.

Default setup uses the [Jupyter Kernel Gateway](https://github.com/jupyter-server/kernel_gateway). If you need scalable compute,
deploy your own [enterprise gateway](https://github.com/jupyter-server/enterprise_gateway) and point `KERNEL_GATEWAY_URL` to it.

## Quick start (Docker Compose)

```bash
docker compose up --build
```

The API will be available at `http://localhost:12345`.

## API

### `POST /run_jupyter`

Execute Python code in a Jupyter kernel.

Request body:
```json
{
  "session_id": "optional-session-id",
  "code": "print('hello')",
  "timeout": 5.0
}
```

Response body (success):
```json
{
  "output": "hello",
  "status": "success",
  "execution_time": 0.123
}
```

Response body (no code):
```json
{
  "output": "Error: No code provided",
  "status": "error",
  "execution_time": 0.0
}
```

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

## Configuration

Environment variables used by the FastAPI service:

- `KERNEL_GATEWAY_URL` (required): Base URL for the Jupyter Kernel Gateway.
- `KERNEL_GATEWAY_TOKEN` (optional): Token for the Kernel Gateway auth header.
- `REDIS_URL` (optional): Full Redis connection URL.
- `REDIS_HOST` (default: `redis`)
- `REDIS_PORT` (default: `6379`)
- `REDIS_DB` (default: `0`)
- `APP_PORT` (default: `12345`)
- `MAX_CONCURRENT_RUNS` (default: `4`)

The provided `docker-compose.yaml` sets defaults for local usage.

## Local development (without Docker)

1. Ensure you have a running Jupyter Kernel Gateway and Redis-compatible server.
2. Set `KERNEL_GATEWAY_URL` and Redis settings.
3. Run:

```bash
uvicorn llm_codebox.main:app --host 0.0.0.0 --port 12345
```
