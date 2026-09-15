"""Shared pytest fixtures for line-ext-msg tests (never launches a browser).

The fixtures are thin wrappers so tests can request helpers by name;
`tests/helpers.py` holds the plain functions for direct imports too.
"""

import pytest

from tests.helpers import make_settings, patch_selectors


@pytest.fixture
def settings():
    """Quiet Settings factory: settings(rooms_scroll_ms=0)."""
    return make_settings


@pytest.fixture
def selectors():
    """Selector swapper: original = selectors(module, message_item='msg')."""
    return patch_selectors
