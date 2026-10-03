"""The declared version and the package version must be the same string.

Two places to bump is two places to forget, and a stale __version__ is exactly
what a caller reads when they report a bug against a release.
"""

import re
from pathlib import Path

import line_ext_msg

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _declared_version() -> str:
    """Read [project].version out of pyproject.toml.

    A regex rather than tomllib, because the package supports Python 3.10 and
    tomllib only arrived in 3.11.
    """
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    assert match is not None, "pyproject.toml has no top-level version = \"...\""
    return match.group(1)


def test_package_version_matches_pyproject():
    assert line_ext_msg.__version__ == _declared_version()


def test_version_is_a_release_number():
    """Guard against shipping a dev or local build by accident."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", line_ext_msg.__version__), line_ext_msg.__version__