"""structlog configuration shared by the API and the worker.

Call `configure_logging()` once, at process startup. stdlib `logging`
(uvicorn, apscheduler, sqlalchemy) is routed through the same
`structlog.stdlib.ProcessorFormatter`, so every line -- ours and theirs --
renders as one JSON object, not JSON lines interleaved with stdlib's plain
text.
"""

from __future__ import annotations

import logging

import structlog
from structlog.typing import FilteringBoundLogger

__all__ = ["FilteringBoundLogger", "configure_logging", "get_logger"]


def configure_logging(*, json: bool = True, level: int = logging.INFO) -> None:
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )

    renderer = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def get_logger(name: str) -> FilteringBoundLogger:
    logger: FilteringBoundLogger = structlog.get_logger(name)
    return logger
