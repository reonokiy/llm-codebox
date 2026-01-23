from fastapi import FastAPI, Request

import asyncio
import argparse
import contextlib
import time

import uvicorn

from . import config
import redis
from .client import clear_session, run_jupyter_code

app = FastAPI()

def _init_redis() -> redis.Redis:
    url = config.REDIS_URL
    if url:
        return redis.Redis.from_url(url)
    return redis.Redis(
        host=config.REDIS_HOST, port=config.REDIS_PORT, db=config.REDIS_DB
    )


redis_client = _init_redis()
semaphore = asyncio.Semaphore(max(1, config.MAX_CONCURRENT_RUNS))


@app.post("/run_jupyter")
async def query(request: Request):
    input_data = await request.json()
    session_id = str(input_data.get("session_id", "JupyterSandboxDefault"))
    code_str = str(input_data.get("code", ""))
    if code_str.strip() == "":
        return {
            "output": "Error: No code provided",
            "status": "error",
            "execution_time": 0.0,
        }

    timeout = float(input_data.get("timeout", 5.0))

    start_time = time.time()
    async with semaphore:
        jupyter_output = await run_jupyter_code(redis_client, session_id, code_str, timeout)
    execution_time = float(time.time() - start_time)

    response = {
        "output": jupyter_output,
        "status": "success",
        "execution_time": execution_time,
    }
    return response


@app.post("/clear_session")
async def jupyter_sandbox(request: Request):
    input_data = await request.json()
    session_id = str(input_data.get("session_id", "JupyterSandboxDefault"))
    clear_session(session_id)
    with contextlib.suppress(Exception):
        redis_client.delete(session_id)
    return {"status": "success"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FastAPI server for code sandbox.")
    parser.add_argument(
        "--port",
        type=int,
        default=config.APP_PORT,
        help="Port to run the FastAPI server on.",
    )
    args = parser.parse_args()

    uvicorn.run("llm_codebox.main:app", host="0.0.0.0", port=args.port, reload=False)
