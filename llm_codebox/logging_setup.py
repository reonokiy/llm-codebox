import logging
import sys

import structlog


def _coerce_level(level: int | str) -> int:
    if isinstance(level, int):
        return level

    raw = level.strip().upper()
    if raw == "WARN":
        raw = "WARNING"
    if raw.isdigit():
        return int(raw)

    mapping = logging.getLevelNamesMapping()
    return int(mapping.get(raw, logging.INFO))


def configure_logging(level: int | str = logging.INFO) -> None:
    coerced_level = _coerce_level(level)
    timestamper = structlog.processors.TimeStamper(fmt="iso")

    shared_processors: list[structlog.typing.Processor] = [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        timestamper,
    ]

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            timestamper,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.CallsiteParameterAdder(
                {
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                }
            ),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
        )
    )

    logging.basicConfig(
        level=coerced_level,
        handlers=[handler],
        format="%(message)s",
        force=True,
    )

    # Uvicorn CLI config installs its own handlers/formatters.
    # Force everything to propagate to the root handler (our ProcessorFormatter).
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        log = logging.getLogger(logger_name)
        log.handlers.clear()
        log.propagate = True
        log.setLevel(coerced_level)
