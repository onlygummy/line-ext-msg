"""Shared pytest fixtures for line-ext-msg tests (never launches a browser).

The fixtures are thin wrappers so tests can request helpers by name;
`tests/helpers.py` holds the plain functions for direct imports too.
"""

import logging

import pytest

from tests.helpers import make_settings, patch_selectors

PACKAGE_LOGGER = "line_ext_msg"


@pytest.fixture(autouse=True)
def _reset_package_logger():
    """Restore the package logger so one test cannot leak handlers/level."""
    logger = logging.getLogger(PACKAGE_LOGGER)
    handlers = list(logger.handlers)
    propagate = logger.propagate
    level = logger.level
    yield
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    for handler in handlers:
        logger.addHandler(handler)
    logger.propagate = propagate
    logger.setLevel(level)


@pytest.fixture
def settings():
    """Quiet Settings factory: settings(rooms_scroll_ms=0)."""
    return make_settings


@pytest.fixture
def selectors():
    """Selector swapper: original = selectors(module, message_item='msg')."""
    return patch_selectors
