"""CDP session: attach, find LINE tab, route to chats, readiness probes."""

import glob
import logging
import os

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from ..config.selectors import SELECTORS
from ..config.settings import Settings
from ..domain.errors import AttachFailed
from . import cdp

logger = logging.getLogger(__name__)


def _debug_dir(settings: Settings) -> str:
    from .process import expand
    return expand(settings.profile_dir)


def is_on_disk(settings: Settings) -> bool:
    """Extension folder exists (source of truth for install check)."""
    pattern = os.path.join(
        _debug_dir(settings), "Default", "Extensions", settings.extension_id, "*", "index.html"
    )
    return len(glob.glob(pattern)) > 0


def connect(settings: Settings):
    """Attach to the debug Chrome. Returns (playwright, browser, context)."""
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.connect_over_cdp(settings.cdp_endpoint, timeout=15000)
    except Exception as e:
        logger.error("CDP attach failed: %s", e)
        raise AttachFailed(f"could not attach to the browser: {e}") from e
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    logger.info("attached over CDP (%d context(s))", len(browser.contexts))
    return pw, browser, context


def find_line_page(target, extension_id: str) -> Page | None:
    """Search all contexts if given Browser, else single context."""
    contexts = target.contexts if hasattr(target, "contexts") else [target]
    for ctx in contexts:
        try:
            pages = ctx.pages
        except Exception:
            continue
        for page in pages:
            try:
                if page.url and extension_id in page.url:
                    return page
            except Exception:
                continue
    return None


def close_startup_tabs(settings: Settings) -> None:
    """Close startup noise (newtab/welcome/blank) so LINE stays tab 1.

    Only touches the isolated debug profile via CDP. Never closes LINE tabs.
    """
    prefixes = (
        "chrome://newtab",
        "chrome://welcome",
        "chrome://new-tab-page",
        "chrome-untrusted://new-tab-page",
        "about:blank",
        # Blocked chrome-extension:// loads (e.g. before install) land here.
        "chrome-error://",
    )
    for target in cdp.list_targets(settings):
        if target.get("type") != "page":
            continue
        url = target.get("url") or ""
        if settings.extension_id in url:
            continue
        if url.startswith(prefixes) and target.get("id"):
            cdp.close_target(settings, target["id"])


def close_duplicate_line_targets(settings: Settings) -> None:
    """Close extra LINE pages via CDP HTTP so repeats don't pile up."""
    seen_first = False
    for target in cdp.list_targets(settings):
        if target.get("type") != "page":
            continue
        if settings.extension_id not in (target.get("url") or ""):
            continue
        if not seen_first:
            seen_first = True
            continue
        if target.get("id"):
            cdp.close_target(settings, target["id"])


def close_extension_tabs(settings: Settings) -> None:
    """Close every tab pointing at the extension.

    Only call this when the extension is missing: those tabs are blocked
    loads, and closing them keeps only the Web Store page the install flow
    opened.
    """
    for target in cdp.list_targets(settings):
        if target.get("type") != "page":
            continue
        if settings.extension_id in (target.get("url") or "") and target.get("id"):
            cdp.close_target(settings, target["id"])


def goto_chats(page: Page, settings: Settings) -> None:
    """Route the LINE tab to #/chats (direct URL, fallback: nav click)."""
    try:
        if (page.url or "").rstrip("/").endswith("#/chats"):
            return
    except Exception:
        pass
    try:
        page.goto(settings.chats_url, timeout=10000)
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    try:
        if (page.url or "").rstrip("/").endswith("#/chats"):
            return
        page.locator(SELECTORS["nav_chat"]).first.click(timeout=5000)
    except Exception:
        pass


def ensure_line_page(context: BrowserContext, settings: Settings, browser: Browser | None = None) -> Page:
    """Reuse the LINE tab (or open fresh, straight to #/chats). Left open for reuse."""
    close_duplicate_line_targets(settings)
    close_startup_tabs(settings)
    page = find_line_page(browser if browser is not None else context, settings.extension_id)
    if page is not None:
        try:
            page.bring_to_front()
        except Exception:
            pass
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        goto_chats(page, settings)
        logger.debug("reusing the existing LINE tab")
        return page
    page = context.new_page()
    logger.debug("opening a new LINE tab")
    try:
        page.goto(settings.chats_url)
    except Exception:
        # The extension may not be installed yet and Chrome blocks the
        # chrome-extension:// URL. The readiness step handles that case, so
        # do not crash the whole flow here.
        pass
    try:
        page.bring_to_front()
    except Exception:
        pass
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    return page


def _one_line(text) -> str:
    """First line of a Playwright error; its call log spans many lines."""
    lines = str(text).splitlines()
    return lines[0] if lines else ""


def check_installed(context: BrowserContext, settings: Settings, browser: Browser | None = None) -> tuple[bool, str]:
    """3-layer install check reusing the existing tab. Returns (installed, detail)."""
    found_disk = is_on_disk(settings)
    existing = find_line_page(browser if browser is not None else context, settings.extension_id)
    if existing is not None:
        try:
            body = existing.content()
            url = existing.url or ""
            detail = f"reused tab body_len={len(body)}"
            if url.startswith("chrome-error://"):
                return False, detail
            if "LINE" in body or 'id="root"' in body or settings.extension_id in url:
                return True, detail
            return found_disk, detail
        except Exception as e:
            return found_disk, f"could not read the reused tab: {_one_line(e)}"
    if found_disk:
        # The files are already there, so treat the install as done. A probe
        # tab would only get blocked while a freshly started Chrome finishes
        # registering the extension; step [4/5] exercises the real load.
        return True, "found_on_disk=True"
    probe = context.new_page()
    try:
        probe.goto(settings.extension_url, timeout=10000)
        probe.wait_for_load_state("domcontentloaded", timeout=10000)
        probe.wait_for_timeout(2000)
        url = probe.url or ""
        body = probe.content()
        detail = f"found_on_disk={found_disk} body_len={len(body)}"
        if url.startswith("chrome-error://"):
            return False, detail
        if "LINE" in body or 'id="root"' in body or settings.extension_id in url:
            return True, detail
        return found_disk, detail
    except Exception as e:
        return found_disk, f"probe failed: {_one_line(e)} found_on_disk={found_disk}"
    finally:
        probe.close()


def wait_ready(page: Page, settings: Settings) -> str:
    """Wait until React hydrates. Returns 'ready', 'loading', or 'timeout'."""
    try:
        page.wait_for_function(
            "() => !document.querySelector('div.is_loading')",
            timeout=settings.app_ready_ms,
        )
    except Exception:
        try:
            return "loading" if page.locator("div.is_loading").count() > 0 else "ready"
        except Exception:
            return "timeout"
    # Give the chat list (or login screen) a moment to render so step [5/5]
    # does not burn its whole poll while rows are already on the way. The
    # settle window is env-tunable because slower machines need more of it.
    try:
        page.wait_for_selector(
            f"{SELECTORS['room_item']}, [class*='loginPage']",
            state="attached",
            timeout=min(10000, settings.app_ready_ms),
        )
    except Exception:
        pass
    try:
        page.wait_for_timeout(settings.ready_settle_ms)
    except Exception:
        pass
    logger.debug("page ready")
    return "ready"


def open_store_page(context: BrowserContext, settings: Settings) -> Page:
    """Open the Web Store page and bring it forward so the user can install."""
    tab = context.new_page()
    tab.goto(settings.webstore_url)
    try:
        tab.bring_to_front()
    except Exception:
        pass
    return tab
