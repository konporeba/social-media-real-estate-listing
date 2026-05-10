"""structlog configuration and optional Langfuse client initialisation."""

import logging
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from langfuse import Langfuse

_langfuse: "Langfuse | None" = None


def get_langfuse() -> "Langfuse | None":
    """Return the active Langfuse client, or None if not configured."""
    return _langfuse


def configure_logging(level: str = "INFO") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", level=log_level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )


def init_langfuse() -> "Langfuse | None":
    """Initialise Langfuse client if env vars are set; store in module global."""
    global _langfuse
    from config import get_settings

    settings = get_settings()
    if not settings.langfuse_enabled:
        return None
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host or None,
        )
        _langfuse = client
        return client
    except Exception:
        return None
