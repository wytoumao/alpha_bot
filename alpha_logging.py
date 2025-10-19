from __future__ import annotations

import logging
from typing import Any, Optional

import structlog

_CONFIGURED = False


def configure(level: str = "INFO", *, json_format: bool = True, force: bool = False) -> None:
    """
    Configure structlog + stdlib logging once.
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    processors = [
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    if json_format:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
    )
    _CONFIGURED = True


def get_logger(name: Optional[str] = None, **initial_values: Any) -> structlog.stdlib.BoundLogger:
    if not _CONFIGURED:
        configure()
    logger = structlog.get_logger(name) if name else structlog.get_logger()
    if initial_values:
        return logger.bind(**initial_values)
    return logger
