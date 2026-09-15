"""Login check: distinguish 'not logged in' from 'selector mismatch'."""

import logging

from playwright.sync_api import Page

from ..config.selectors import SELECTORS

logger = logging.getLogger(__name__)

# Fast login-screen locators (CSS-module hashes change, so match stable parts).
LOGIN_LOCATORS = [
    "[class*='loginPage']",
    "text=QR code login",
    "text=Log in",
]

# Fallback text markers when locators miss (checked on small scope only).
LOGIN_MARKERS = [
    "qr code", "qr login", "email address", "log in", "sign in",
]


def _has_login_ui(page: Page) -> bool:
    """True if any login marker is visible (cheap locator checks)."""
    for sel in LOGIN_LOCATORS:
        try:
            if page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    return False


def _has_chat_ui(page: Page) -> bool:
    """True if any room row is rendered (user is logged in)."""
    # Single combined query is one CDP roundtrip instead of one per split.
    try:
        return page.locator(SELECTORS["room_item"]).count() > 0
    except Exception:
        return False


def _body_has_login(page: Page) -> bool:
    """Fallback text scan when locators miss (e.g. UI update)."""
    try:
        text = (page.inner_text("body") or "").lower()
    except Exception:
        return False
    return any(m in text for m in LOGIN_MARKERS)


def check_login(page: Page, timeout_ms: int = 10000) -> tuple[bool, str]:
    """Poll chat UI vs login UI; return as soon as either appears.

    Return (logged_in, reason): 'chat' / 'login' / 'unknown'.
    Caller must ensure the app finished rendering (wait_for_app_ready).
    """
    # Fast path: wake the moment rooms render instead of sleeping blindly.
    try:
        page.wait_for_selector(SELECTORS["room_item"], state="attached", timeout=timeout_ms)
        logger.info("login state: chat")
        return True, "chat"
    except Exception:
        pass
    if _has_chat_ui(page):
        logger.info("login state: chat")
        return True, "chat"
    if _has_login_ui(page):
        logger.info("login state: login")
        return False, "login"
    # Final text fallback on rendered body before giving up.
    if _body_has_login(page):
        logger.info("login state: login (text marker)")
        return False, "login"
    logger.warning("login state: unknown (no chat or login UI matched)")
    return False, "unknown"


def wait_for_login(
    page: Page,
    timeout_ms: int = 300000,
    poll_ms: int = 500,
    on_tick=None,
) -> tuple[bool, str]:
    """Keep tracking the login page until chat rows appear or timeout.

    Returns (logged_in, reason): 'chat' on success, 'login' when the
    timeout expires while still on the login screen, 'unknown' when
    neither chat nor login UI was ever seen (likely selector mismatch).

    on_tick(elapsed_ms) is called after each poll so the caller can
    print progress. KeyboardInterrupt is never swallowed here.
    """
    step = max(100, poll_ms)
    elapsed = 0
    seen_login = False
    polls = 0
    while elapsed < max(step, timeout_ms):
        if _has_chat_ui(page):
            logger.info("logged in after %dms", elapsed)
            return True, "chat"
        if _has_login_ui(page):
            seen_login = True
        elif polls % 10 == 0 and _body_has_login(page):
            # inner_text(body) serializes the whole DOM: expensive, so use
            # it as a slow fallback only (every ~5s), not every 500ms poll.
            seen_login = True
        if on_tick is not None:
            try:
                on_tick(elapsed)
            except Exception:
                pass
        try:
            page.wait_for_timeout(step)
        except Exception:
            # Page closed or detached mid-wait: treat as unknown.
            logger.warning("page closed while waiting for login")
            return False, "unknown"
        elapsed += step
        polls += 1
    if _has_chat_ui(page):
        return True, "chat"
    if seen_login or _has_login_ui(page) or _body_has_login(page):
        logger.warning("login not completed within %dms", timeout_ms)
        return False, "login"
    logger.warning("login UI never matched within %dms", timeout_ms)
    return False, "unknown"
