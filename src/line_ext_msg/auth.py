"""Login check: distinguish 'not logged in' from 'selector mismatch'."""

from playwright.sync_api import Page

from .settings import SELECTORS

# Fast login-screen locators (CSS-module hashes change, so match stable parts).
LOGIN_LOCATORS = [
    "[class*='loginPage']",
    "text=QR code login",
    "text=Log in",
]

# Fallback text markers when locators miss (checked on small scope only).
LOGIN_MARKERS = [
    "qr code", "qr login", "email address",
    "เข้าสู่ระบบ", "ล็อกอิน",
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


def check_login(page: Page, timeout_ms: int = 10000) -> tuple[bool, str]:
    """Poll chat UI vs login UI; return as soon as either appears.

    Return (logged_in, reason): 'chat' / 'login' / 'unknown'.
    Caller must ensure the app finished rendering (wait_for_app_ready).
    """
    # Poll room rows (not the container: it may not exist as one element).
    rows = [s.strip() for s in SELECTORS["room_item"].split(",")]
    # Poll every 500ms; worst case only when page genuinely stuck.
    for _ in range(max(1, timeout_ms // 500)):
        for sel in rows:
            try:
                if page.locator(sel).count() > 0:
                    return True, "chat"
            except Exception:
                continue
        if _has_login_ui(page):
            return False, "login"
        page.wait_for_timeout(500)
    # Final text fallback on rendered body before giving up.
    try:
        text = (page.inner_text("body") or "").lower()
    except Exception:
        text = ""
    if any(m in text for m in LOGIN_MARKERS):
        return False, "login"
    return False, "unknown"
