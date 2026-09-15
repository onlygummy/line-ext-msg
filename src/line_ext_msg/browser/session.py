"""CDP session: attach, find LINE tab, route to chats, readiness probes."""

import glob
import json
import os
import urllib.request

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from ..config.selectors import SELECTORS
from ..config.settings import Settings
from ..domain.errors import AttachFailed


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
        raise AttachFailed(f"เกาะเบราว์เซอร์ไม่สำเร็จ: {e}") from e
    context = browser.contexts[0] if browser.contexts else browser.new_context()
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
    )
    try:
        with urllib.request.urlopen(f"{settings.cdp_endpoint}/json/list", timeout=3) as res:
            targets = json.loads(res.read().decode("utf-8", errors="ignore"))
    except Exception:
        return
    for t in targets:
        if not isinstance(t, dict) or t.get("type") != "page":
            continue
        url = t.get("url") or ""
        if settings.extension_id in url:
            continue
        if url.startswith(prefixes) and t.get("id"):
            try:
                urllib.request.urlopen(f"{settings.cdp_endpoint}/json/close/{t['id']}", timeout=3).read()
            except Exception:
                continue


def close_duplicate_line_targets(settings: Settings) -> None:
    """Close extra LINE pages via CDP HTTP so repeats don't pile up."""
    try:
        with urllib.request.urlopen(f"{settings.cdp_endpoint}/json/list", timeout=3) as res:
            targets = json.loads(res.read().decode("utf-8", errors="ignore"))
    except Exception:
        return
    seen_first = False
    for t in targets:
        if t.get("type") != "page":
            continue
        if settings.extension_id not in (t.get("url") or ""):
            continue
        if not seen_first:
            seen_first = True
            continue
        if t.get("id"):
            try:
                urllib.request.urlopen(f"{settings.cdp_endpoint}/json/close/{t['id']}", timeout=3).read()
            except Exception:
                continue


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
        return page
    page = context.new_page()
    page.goto(settings.chats_url)
    try:
        page.bring_to_front()
    except Exception:
        pass
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    return page


def check_installed(context: BrowserContext, settings: Settings, browser: Browser | None = None) -> tuple[bool, str]:
    """3-layer install check reusing the existing tab. Returns (installed, detail)."""
    found_disk = is_on_disk(settings)
    existing = find_line_page(browser if browser is not None else context, settings.extension_id)
    if existing is not None:
        try:
            body = existing.content()
            url = existing.url or ""
            detail = f"reuse แท็บเดิม body_len={len(body)}"
            if url.startswith("chrome-error://"):
                return False, detail
            if "LINE" in body or 'id="root"' in body or settings.extension_id in url:
                return True, detail
            return found_disk, detail
        except Exception as e:
            return found_disk, f"อ่านแท็บเดิมล้มเหลว: {e}"
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
        return found_disk, f"probe ล้มเหลว: {e} found_on_disk={found_disk}"
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
    # does not burn its whole poll while rows are already on the way.
    try:
        page.wait_for_selector(
            f"{SELECTORS['room_item']}, [class*='loginPage']",
            state="attached",
            timeout=min(10000, settings.app_ready_ms),
        )
    except Exception:
        pass
    try:
        page.wait_for_timeout(800)
    except Exception:
        pass
    return "ready"


def open_store_page(context: BrowserContext, settings: Settings) -> None:
    """Open the Web Store page so the user can install manually."""
    tab = context.new_page()
    tab.goto(settings.webstore_url)
