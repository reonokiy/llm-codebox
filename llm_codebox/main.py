from fastapi import FastAPI
from pydantic import BaseModel, Field, field_validator

import asyncio
import argparse
import contextlib
import time

import uvicorn

from . import config
import redis
from .client import clear_session, run_jupyter_code, run_jupyter_code_v1


class RunJupyterRequest(BaseModel):
    session_id: str = Field(default="JupyterSandboxDefault")
    code: str
    timeout: float = Field(default=5.0, gt=0)

    @field_validator("code")
    @classmethod
    def _non_empty_code(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("code must not be empty")
        return value


class JupyterOutputV2(BaseModel):
    stdout: str = ""
    stderr: str = ""
    stdout_raw: str = ""
    stderr_raw: str = ""
    images: list[str] = Field(default_factory=list)


class RunJupyterResponse(BaseModel):
    output: JupyterOutputV2
    status: str
    execution_time: float


class JupyterOutputV1(BaseModel):
    result: str | None = None
    stdout: str = ""
    stderr: str = ""
    images: list[str] = Field(default_factory=list)
    debug_info: dict[str, str] = Field(default_factory=lambda: {"msg": ""})


class RunJupyterResponseV1(BaseModel):
    output: JupyterOutputV1
    status: str
    execution_time: float


class ClearSessionRequest(BaseModel):
    session_id: str = Field(default="JupyterSandboxDefault")


class ClearSessionResponse(BaseModel):
    status: str


class HealthResponse(BaseModel):
    status: str


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


@app.post("/run_jupyter", response_model=RunJupyterResponse)
async def run_jupyter(request: RunJupyterRequest) -> RunJupyterResponse:
    session_id = request.session_id
    code_str = request.code
    timeout = request.timeout
    start_time = time.time()
    async with semaphore:
        output_dict = await run_jupyter_code(
            redis_client, session_id, code_str, timeout
        )
    execution_time = float(time.time() - start_time)

    return RunJupyterResponse(
        output=JupyterOutputV2(**output_dict),
        status="success",
        execution_time=execution_time,
    )


@app.post("/jupyter_sandbox", response_model=RunJupyterResponseV1)
async def jupyter_sandbox_v1(request: RunJupyterRequest) -> RunJupyterResponseV1:
    session_id = request.session_id
    code_str = request.code
    timeout = request.timeout
    start_time = time.time()
    async with semaphore:
        output_dict = await run_jupyter_code_v1(
            redis_client, session_id, code_str, timeout
        )
    execution_time = float(time.time() - start_time)

    return RunJupyterResponseV1(
        output=JupyterOutputV1(**output_dict),
        status="success",
        execution_time=execution_time,
    )


@app.post("/clear_session", response_model=ClearSessionResponse)
async def jupyter_sandbox(request: ClearSessionRequest) -> ClearSessionResponse:
    clear_session(request.session_id)
    with contextlib.suppress(Exception):
        redis_client.delete(request.session_id)
    return ClearSessionResponse(status="success")


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


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
