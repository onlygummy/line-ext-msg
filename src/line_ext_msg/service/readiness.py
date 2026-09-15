"""Startup checklist: reuse a live session, attach, verify, then handle login.

The LINE session lives in the running Chrome process. The token stays in
Local Storage (``lcs_secure_<mid>``) across restarts, but the key that
decrypts it lives in the extension's sandboxed LTSM page, whose storage is
not persistent, so a fresh Chrome always asks for the QR again.

Therefore this module never restarts a running Chrome just to match a
preferred mode: a live instance is reused as-is and stays logged in, and
the preferred mode only decides how a fresh Chrome starts. When a QR is
needed it is captured from the headless login page and shown in a dialog,
so the whole run stays headless.
"""

from __future__ import annotations

import dataclasses
import logging
import time

from ..browser import auth, chrome, js, mode, session
from ..config.selectors import SELECTORS
from ..config.settings import Settings
from ..domain.errors import (
    AppNotReady,
    AttachFailed,
    ChromeNotReady,
    ExtensionMissing,
    LoginRequired,
    QrDialogFailed,
)
from ..domain.models import StepResult
from . import qr

logger = logging.getLogger(__name__)

TOTAL_STEPS = 5


def switch_mode(client, headless: bool, open_page: bool = True) -> None:
    """Converge Chrome to the wanted mode and reattach the LINE page.

    Only safe when no login must survive: a restart drops the in-memory
    session and forces another QR scan. open_page=False skips navigating to
    the extension page, for switches made before the extension is installed.
    """
    settings = dataclasses.replace(client.settings, headless=headless)
    mode.converge(settings, browser=client._browser)
    client.close()  # stop Playwright; Chrome itself stays up
    client._pw, client._browser, client._context = session.connect(settings)
    if open_page:
        client._page = session.ensure_line_page(client._context, settings, client._browser)
        session.wait_ready(client._page, settings)
    else:
        client._page = None
    client.settings = settings


def _ensure_headed(client) -> bool:
    """Pop a visible window when the QR canvas cannot be captured headlessly."""
    if mode.mode_of(client.settings) == mode.HEADED:
        return False
    logger.warning("falling back to a headed Chrome window to scan the QR")
    switch_mode(client, headless=False)
    return True


def _qr_data(page) -> str:
    """PNG data URI of the login QR canvas, '' when unavailable."""
    try:
        data = page.evaluate(
            js.QR_DATA_URL,
            {"sel": SELECTORS["login_qr"], "pageSel": SELECTORS["login_page"]},
        )
    except Exception as e:
        logger.debug("qr data read failed: %s", e)
        return ""
    return data if isinstance(data, str) else ""


def _qr_debug(page) -> dict:
    """Redacted login-page diagnostics for --debug-qr (no QR content)."""
    try:
        data = page.evaluate(
            js.QR_DEBUG,
            {
                "sel": SELECTORS["login_qr"],
                "pageSel": SELECTORS["login_page"],
                "pinSel": SELECTORS["login_pin"],
            },
        )
    except Exception as e:
        return {"error": str(e)[:120]}
    return data if isinstance(data, dict) else {}


def _login_pin(page) -> tuple[str, str]:
    """PIN shown after a QR scan and its instruction text, ('', '') when none."""
    try:
        data = page.evaluate(js.LOGIN_PIN, {
            "pinSel": SELECTORS["login_pin"],
            "descSel": SELECTORS["login_pin_desc"],
        })
    except Exception:
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    pin = data.get("pin") or ""
    desc = data.get("desc") or ""
    return (pin if isinstance(pin, str) else "", desc if isinstance(desc, str) else "")


def _wait_for_qr(page, timeout_ms: int) -> str:
    """Poll for a non-empty QR data URI until it appears or time runs out."""
    deadline = time.monotonic() + max(0.0, timeout_ms / 1000)
    while True:
        uri = _qr_data(page)
        if uri:
            logger.debug("qr captured (%d bytes of data URI)", len(uri))
            return uri
        if time.monotonic() >= deadline:
            logger.warning("no QR canvas after %dms", timeout_ms)
            return ""
        try:
            page.wait_for_timeout(500)
        except Exception:
            return ""


def _qr_login(client) -> str:
    """Show the QR in a dialog and wait until login or the user closes it.

    There is no timeout on purpose: the caller waits until the QR is
    scanned or the window is closed. Returns 'ok' when logged in, 'cancel'
    when the dialog was closed, or 'fallback' when the QR canvas could not
    be captured (the caller should pop a headed window instead). Raises
    QrDialogFailed when the dialog process cannot be started.
    """
    page = client._page
    settings: Settings = client.settings
    data_uri = _wait_for_qr(page, settings.qr_ready_ms)
    reloaded = False
    if not data_uri:
        # The reused SPA may be stuck from an earlier run, so the login view
        # never mounts. A reload is safe here because we are not logged in.
        reloaded = True
        logger.info("reloading the login page and retrying the QR capture")
        try:
            page.goto(settings.chats_url, timeout=10000)
            session.wait_ready(page, settings)
        except Exception as e:
            logger.debug("reload failed: %s", e)
        data_uri = _wait_for_qr(page, settings.qr_ready_ms)
    if not data_uri:
        if settings.debug_qr:
            logger.info("qr diagnostics: %s", _qr_debug(page))
        logger.warning("could not capture the QR (reloaded=%s)", reloaded)
        return "fallback"

    dialog = qr.QrDialog(zoom=settings.qr_zoom, title=settings.dialog_title)
    try:
        dialog.open(data_uri)
    except QrDialogFailed as e:
        dialog.finish("cancel", keep_png=True)
        logger.error("%s (open the file manually at %s)", e, dialog.png)
        raise

    logger.info("QR shown in the dialog (close it to cancel)")

    logged = False
    shown = data_uri
    try:
        while True:
            ok, _ = auth.check_login(page, timeout_ms=500)
            if ok:
                logged = True
                break
            if not dialog.alive():
                logger.info("dialog closed by the user; cancelling login")
                break
            pin, desc = _login_pin(page)
            if pin:
                logger.info("PIN requested (len=%d)", len(pin))
                dialog.set_pin(pin, desc)
            else:
                # Keep the PIN visible while verification runs: only go back
                # to the QR when a genuinely new one appears, otherwise a
                # stale QR image flashes after the code is entered.
                uri = _qr_data(page)
                if uri and uri != shown:
                    logger.info("new QR detected; refreshing the dialog")
                    dialog.show_qr(uri)
                    shown = uri
            try:
                page.wait_for_timeout(500)
            except Exception:
                break
    finally:
        dialog.finish("done" if logged else "cancel")

    return "ok" if logged else "cancel"


def _print_keep_open(client) -> None:
    """Tell the user why the Chrome process is left running after login."""
    if client.settings.quiet:
        return
    logger.info("logged in (leave Chrome running to avoid scanning again)")


def _install_extension(client, settings: Settings, detail: str) -> tuple[bool, str]:
    """Pop a headed window, open the Web Store, and wait for the install.

    Waits until the extension folder appears on disk or the user closes
    Chrome. Once installed it always returns to headless, then reports the
    fresh check result. Returns (installed, detail).
    """
    if mode.mode_of(settings) != mode.HEADED:
        logger.warning("extension not found; opening a headed Chrome window to install")
        # Do not open the LINE page here: without the extension it is a
        # blocked tab that only clutters the window.
        switch_mode(client, headless=False, open_page=False)
    session.close_startup_tabs(settings)
    session.close_extension_tabs(settings)
    try:
        session.open_store_page(client._context, settings)
    except Exception as e:
        logger.warning("could not open the Web Store page: %s", e)
    logger.info("install LINE from the Web Store (close the window to cancel)")

    # No timeout on purpose: stop by installing the extension, closing
    # Chrome, or pressing Ctrl+C.
    polls = 0
    while not session.is_on_disk(settings):
        if not chrome.is_debug_ready(settings):
            logger.warning("Chrome closed before the install finished")
            return False, "cancelled: Chrome window closed before install finished"
        polls += 1
        if polls % 10 == 0:
            logger.debug("still waiting for the extension files")
        time.sleep(2)

    logger.info("extension installed; returning to headless")
    switch_mode(client, headless=True)
    return session.check_installed(client._context, settings, client._browser)


def run(client, wait_for_login: bool | None = None,
        login_timeout_ms: int | None = None) -> list[StepResult]:
    """Run the 5 readiness checks. Raises typed LineError on first failure."""
    settings: Settings = client.settings
    steps = client._steps
    logger.info("[0/5] checking prerequisites")
    results: list[StepResult] = []

    def record(name: str, passed: bool, detail: str = "", hint: str = "") -> StepResult:
        # Log the label first, then the detail, so the detail line sits
        # under the step it describes instead of the previous one.
        steps.check(name, passed, "" if passed else hint)
        if detail:
            steps.detail(detail)
        result = StepResult(name=name, passed=passed, detail=detail or hint)
        results.append(result)
        return result

    # Start Chrome only when none is running. A live instance is reused
    # as-is, whatever its mode, because restarting it would end the
    # in-memory session and force another QR scan.
    try:
        if not chrome.is_debug_ready(settings):
            mode.converge(settings)
    except ChromeNotReady as e:
        record("Chrome debug ready", False, str(e))
        steps.skip_rest("stopped early")
        raise
    record("Chrome debug ready", True)

    try:
        client._pw, client._browser, client._context = session.connect(settings)
    except AttachFailed as e:
        record("Attached to browser", False, str(e))
        steps.skip_rest("stopped early")
        raise
    record("Attached to browser", True)

    installed, detail = session.check_installed(client._context, settings, client._browser)
    if not installed:
        installed, detail = _install_extension(client, settings, detail)
    if not record("Extension installed", installed,
                  detail=detail, hint=f"install it here: {settings.webstore_url}").passed:
        steps.skip_rest("waiting for install")
        raise ExtensionMissing(f"install it here: {settings.webstore_url}")

    client._page = session.ensure_line_page(client._context, settings, client._browser)
    state = session.wait_ready(client._page, settings)
    if not record("LINE page ready", state == "ready",
                  detail=f"state={state}",
                  hint="app did not finish loading in time, try again").passed:
        steps.skip_rest("stopped early")
        raise AppNotReady("app did not finish loading in time, try again")

    logged_in, reason = auth.check_login(client._page, settings.login_poll_ms)
    # Interactive CLI waits by default; quiet library use stays fail-fast.
    should_wait = wait_for_login if wait_for_login is not None else not settings.quiet
    wait_ms = login_timeout_ms if login_timeout_ms is not None else settings.login_wait_ms

    last_ping = [0]

    def _tick(elapsed_ms: int) -> None:
        # Throttle progress to one line per ~10s to avoid log spam.
        if elapsed_ms - last_ping[0] >= 10000:
            last_ping[0] = elapsed_ms
            logger.info("waiting for login (%ds)", elapsed_ms // 1000)

    if not logged_in and reason == "login" and should_wait and wait_ms > 0:
        outcome = _qr_login(client)
        if outcome == "fallback":
            _ensure_headed(client)
            logger.info("log in the Chrome window (Ctrl+C to cancel)")
            logged_in, reason = auth.wait_for_login(client._page, wait_ms, on_tick=_tick)
        elif outcome == "ok":
            logged_in, reason = True, "chat"
        else:
            logged_in, reason = False, "login"
        if logged_in:
            record("Logged in", True, detail="logged in while waiting")
            _print_keep_open(client)
            return results

    detail = "page structure does not match known selectors" if reason == "unknown" and not logged_in else ""
    if not record("Logged in", logged_in,
                  detail=detail,
                  hint="open the LINE tab and log in with QR/email, then run again").passed:
        steps.skip_rest("waiting for login")
        raise LoginRequired("not logged in to LINE")
    return results
