"""Logging setup: level, console handler, and optional file handler."""

import logging

from line_ext_msg.output import logging as logsetup


def test_configure_sets_level_and_console():
    logger = logsetup.configure(logging.DEBUG)
    assert logger is logging.getLogger(logsetup.LOGGER_NAME)
    assert logger.level == logging.DEBUG
    assert logger.propagate is False
    assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)


def test_configure_replaces_handlers(tmp_path):
    logsetup.configure(logging.INFO)
    count = len(logging.getLogger(logsetup.LOGGER_NAME).handlers)
    logsetup.configure(logging.INFO)
    assert len(logging.getLogger(logsetup.LOGGER_NAME).handlers) == count


def test_configure_writes_file(tmp_path):
    path = str(tmp_path / "line.log")
    logger = logsetup.configure(logging.INFO, log_file=path)
    logger.info("hello file")
    assert "hello file" in open(path, encoding="utf-8").read()
