"""Shared test helpers: quiet settings and selector patching (no browser).

Kept importable (not inside conftest) so every test module can reuse the
same construction without launching Playwright.
"""

from __future__ import annotations

from line_ext_msg.config.settings import Settings


def make_settings(**overrides) -> Settings:
    """Build a quiet Settings for tests; pass field overrides as kwargs."""
    overrides.setdefault("quiet", True)
    return Settings(**overrides)


def patch_selectors(module, **overrides) -> dict:
    """Swap a module's SELECTORS and return the original for restoration.

    The caller restores it in a finally block (the tests keep that shape),
    which keeps the diff small while removing the duplicated helper.
    """
    original = module.SELECTORS
    module.SELECTORS = dict(original, **overrides)
    return original
