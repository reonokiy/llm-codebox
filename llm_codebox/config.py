import os


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_str(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    return value


KERNEL_GATEWAY_URL = _get_str("KERNEL_GATEWAY_URL", "").rstrip("/")
KERNEL_GATEWAY_TOKEN = _get_str("KERNEL_GATEWAY_TOKEN", "")

REDIS_URL = _get_str("REDIS_URL", "")
REDIS_HOST = _get_str("REDIS_HOST", "valkey")
REDIS_PORT = _get_int("REDIS_PORT", 6379)
REDIS_DB = _get_int("REDIS_DB", 0)

APP_PORT = _get_int("APP_PORT", 12345)
MAX_CONCURRENT_RUNS = _get_int("MAX_CONCURRENT_RUNS", 4)
