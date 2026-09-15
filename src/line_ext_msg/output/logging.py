"""Logging setup for the CLI. The library never configures logging itself.

Importing the package emits nothing: ``line_ext_msg`` carries a
NullHandler until a caller runs ``configure`` (the CLI does). Applications
that embed the library can call ``configure`` too, or attach their own
handlers to the ``line_ext_msg`` logger.
"""

from __future__ import annotations

import logging
import os
import sys

LOGGER_NAME = "line_ext_msg"
# Short for the console, richer for a file where timing matters.
CONSOLE_FORMAT = "%(levelname)s %(message)s"
FILE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def configure(level: int = logging.INFO, stream=None, log_file: str | None = None):
    """Attach console (and optional file) handlers to the package logger.

    Returns the configured logger. Existing handlers are replaced, so
    calling it twice does not duplicate output.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    console = logging.StreamHandler(stream or sys.stderr)
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT))
    logger.addHandler(console)

    if log_file:
        parent = os.path.dirname(log_file)
        if parent:
            os.makedirs(parent, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(FILE_FORMAT))
        logger.addHandler(file_handler)
    return logger
