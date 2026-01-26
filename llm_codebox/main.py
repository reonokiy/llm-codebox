"""FastAPI application for Jupyter code execution sandbox."""

from __future__ import annotations

import argparse
import asyncio

import redis
import uvicorn
from fastapi import FastAPI

from . import config
from .api import create_router
from .logging_setup import configure_logging

configure_logging(config.LOG_LEVEL)

app = FastAPI()


def _init_redis() -> redis.Redis:  # type: ignore[type-arg]
    url = config.REDIS_URL
    if url:
        return redis.Redis.from_url(url)
    return redis.Redis(
        host=config.REDIS_HOST,
        port=config.REDIS_PORT,
        db=config.REDIS_DB,
    )


redis_client = _init_redis()
semaphore = asyncio.Semaphore(max(1, config.MAX_CONCURRENT_RUNS))

app.include_router(create_router(redis_client, semaphore))


@app.on_event("startup")
def _configure_logging_on_startup() -> None:
    configure_logging(config.LOG_LEVEL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FastAPI server for code sandbox.")
    parser.add_argument(
        "--port",
        type=int,
        default=config.PORT,
        help="Port to run the FastAPI server on.",
    )
    args = parser.parse_args()

    uvicorn.run(
        "llm_codebox.main:app",
        host="0.0.0.0",
        port=args.port,
        reload=False,
        log_config=None,
    )
