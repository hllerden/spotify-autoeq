"""Single entry point for logging configuration."""

from __future__ import annotations

import logging
import sys
from typing import IO, Optional

ROOT_LOGGER = "spotify_autoeq"
_JOURNAL_FORMAT = "%(levelname)s %(name)s: %(message)s"
_CONSOLE_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class _ShortNameFormatter(logging.Formatter):
    """Drops the package prefix from logger names to keep lines short."""

    def format(self, record: logging.LogRecord) -> str:
        prefix = ROOT_LOGGER + "."
        if record.name.startswith(prefix):
            record.name = record.name[len(prefix):]
        return super().format(record)


def configure_logging(level: str = "INFO", journal: bool = True,
                      stream: Optional[IO[str]] = None) -> logging.Logger:
    """Configure the package logger; safe to call repeatedly (SIGHUP reload).

    Only the ``spotify_autoeq`` logger is touched, never the root logger.
    journald adds its own timestamps, so ``journal`` omits them.
    """
    logger = logging.getLogger(ROOT_LOGGER)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(_ShortNameFormatter(_JOURNAL_FORMAT if journal else _CONSOLE_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    logger.propagate = False
    return logger
