"""All page.evaluate snippets obey Playwright's single-argument rule."""

import importlib
import inspect
import re

# Modules holding evaluate scripts. Explicit and small: add browser/js.py
# targets every time new DOM logic moves there.
EVALUATE_MODULES = ["line_ext_msg.browser.js"]

# Top-level arrows may appear as a line-anchored literal, attached to a
# quote in string concatenation, or right after a triple-quoted opener.
_ARROW_PATTERNS = (
    re.compile(r'(?m)^\s*(?:"""\s*)?(?:async\s+)?\(\s*([^)]*?)\s*\)\s*=>'),
    re.compile(r'"\(([^)]*?)\)\s*=>'),
    re.compile(r'"""\s*(?:async\s+)?\(\s*([^)]*?)\s*\)\s*=>'),
)


def _check_arrows(mod) -> int:
    """Assert every top-level evaluate arrow takes at most one param."""
    seen = 0
    src = inspect.getsource(mod)
    for pattern in _ARROW_PATTERNS:
        for found in pattern.finditer(src):
            seen += 1
            params = [p for p in found.group(1).split(",") if p.strip()]
            assert len(params) <= 1, f"{mod.__name__}: {found.group(0)!r}"
    return seen


def test_all_evaluate_scripts_take_single_arg():
    # Playwright passes exactly one argument to evaluate(). A script
    # declaring two params silently misaligns (first gets the object, the
    # rest undefined) and querySelector throws, surfacing as a bogus
    # 'detached' stop with zero rounds scrolled.
    for name in EVALUATE_MODULES:
        mod = importlib.import_module(name)
        assert _check_arrows(mod) > 0, f"{name}: no evaluate script found"


def test_scroll_finder_accepts_overlay():
    # LINE reports its scroller as overflow:overlay; the old
    # auto/scroll-only check walked past it onto body, so nothing on
    # screen moved while the loop concluded 'top'.
    mod = importlib.import_module(EVALUATE_MODULES[0])
    assert "'overlay'" in inspect.getsource(mod)
