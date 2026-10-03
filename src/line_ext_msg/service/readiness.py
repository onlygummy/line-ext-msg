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
from ..domain.callbacks import (
    PinCallback,
    QrCallback,
    StatusCallback,
    call_callback,
)
from ..domain.errors import (
    AppNotReady,
    AttachFailed,
    ChromeNotReady,
    ExtensionMissing,
    LoginRequired,
    LoginTimeout,
    QrDialogFailed,
)
from ..domain.models import StepResult
from . import qr

logger = logging.getLogger(__name__)

TOTAL_STEPS = 5

# Consecutive rounds the page may stay unclassifiable before the login flow
# assumes it is logged in on the wrong view rather than still settling. The
# poll sleeps 500ms, so 4 rounds is about two seconds of grace.
_UNKNOWN_GRACE = 4
# How many times the chats route may be retried before giving up. Two is
# enough for a redirect plus a slow re-render and still terminates.
_UNKNOWN_RECOVERIES = 2

_UNMATCHED_PAGE = (
    "the LINE page shows neither the login screen nor the chats list, so the "
    "extension UI probably changed; run line-ext-msg --dump and send "
    "session/dumps/line_dom.html to tune the selectors"
)


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


def _qr_login(
    client,
    timeout_ms: int | None = None,
    on_qr: QrCallback | None = None,
    on_pin: PinCallback | None = None,
    on_status: StatusCallback | None = None,
) -> str:
    """Show the QR and wait until login, the host cancels, or time runs out.

    Returns 'ok' when logged in, 'cancel' when the dialog was closed or a
    callback returned False, 'timeout' when timeout_ms ran out first,
    'fallback' when the QR canvas could not be captured (the caller should pop
    a headed window instead), and 'stuck' when the page matches no known view
    and the chats route could not fix it. Raises QrDialogFailed when the dialog
    process cannot be started.

    timeout_ms bounds the whole wait. It used to reach only the headed
    fallback, so the dialog itself was bounded by nothing but a human closing
    it, and a host driving its own login UI had no way out at all.

    on_qr and on_pin replace the Tk dialog with the host's own login UI.
    Supplying either one skips the dialog, which is the point on a machine
    with no desktop; supply both to receive the QR and the PIN.

    An unclassifiable page is the interesting case. LINE lands on its own view
    after auth, so 'unknown' usually means "logged in somewhere else" rather
    than "still logging in", and the old loop only spun until the user closed
    the dialog. It now retries the chats route a bounded number of times and
    then gives up with a pointer to --dump instead of hanging.
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

    # Two renderers for the same events. A callback replaces the dialog rather
    # than adding to it: the reason to pass one is that the host owns the login
    # UI, and on a headless server there is no desktop for a dialog to appear
    # on, so showing both would leave the host waiting on a window nobody sees.
    dialog = None
    if on_qr is None and on_pin is None and on_status is None:
        dialog = qr.QrDialog(zoom=settings.qr_zoom, title=settings.dialog_title)
        try:
            dialog.open(data_uri)
        except QrDialogFailed as e:
            dialog.finish("failed", keep_png=True)
            logger.error("%s (open the file manually at %s)", e, dialog.png)
            raise
        logger.info("QR shown in the dialog (close it to cancel)")
    elif not call_callback(on_qr, data_uri, what="qr"):
        logger.info("host declined the QR; cancelling login")
        return "cancel"

    def _verifying(entered: bool) -> None:
        """Move the login UI in or out of the verifying state.

        Entering hides the QR or PIN the user already dealt with, because the
        page is now somewhere else entirely and there is nothing to do. Leaving
        is only needed for the dialog: it swapped its content out, so it has to
        put the previous step back. A host keeps showing its last payload, which
        is why there is no resume event for on_status.
        """
        if dialog is not None:
            if entered:
                dialog.set_verifying()
            else:
                dialog.resume()
        elif entered:
            call_callback(on_status, "verifying", what="status")

    logged = False
    stuck = False
    timed_out = False
    shown = data_uri
    unclassified = 0
    recoveries = 0
    # Deadline covers capture-independent waiting only; _wait_for_qr keeps its
    # own qr_ready_ms budget, so a full run is bounded by the sum of the two.
    deadline = None
    if timeout_ms is not None and timeout_ms > 0:
        deadline = time.monotonic() + timeout_ms / 1000
    try:
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                logger.warning("login wait timed out after %dms", timeout_ms)
                timed_out = True
                break
            ok, reason = auth.check_login(page, timeout_ms=500)
            if ok:
                logged = True
                break
            if reason == "unknown":
                if unclassified == 0:
                    # First unknown after a step we could classify. Post-PIN
                    # this is LINE landing on its own view, so the UI should
                    # stop asking the user to do something.
                    _verifying(True)
                unclassified += 1
                if unclassified >= _UNKNOWN_GRACE:
                    # Safe to reload here and only here: the login screen does
                    # not match, so there is no half-entered code to lose.
                    if recoveries < _UNKNOWN_RECOVERIES:
                        recoveries += 1
                        unclassified = 0
                        logger.info("no login screen and no chat list; "
                                    "switching to the chats view")
                        if session.ensure_chats_view(page, settings) == "failed":
                            stuck = True
                            break
                        continue
                    logger.error(_UNMATCHED_PAGE)
                    stuck = True
                    break
            else:
                if unclassified:
                    # The page is classifiable again, so the unknown stretch was
                    # a rendering hiccup. Put the previous step back.
                    _verifying(False)
                unclassified = 0
            if dialog is not None and not dialog.alive():
                logger.info("dialog closed by the user; cancelling login")
                break
            pin, desc = _login_pin(page)
            if pin:
                logger.info("PIN requested (len=%d)", len(pin))
                if dialog is not None:
                    dialog.set_pin(pin, desc)
                if not call_callback(on_pin, pin, desc, what="pin"):
                    logger.info("host cancelled the login wait")
                    break
            else:
                # Keep the PIN visible while verification runs: only go back
                # to the QR when a genuinely new one appears, otherwise a
                # stale QR image flashes after the code is entered.
                uri = _qr_data(page)
                if uri and uri != shown:
                    logger.info("new QR detected; refreshing the login UI")
                    shown = uri
                    if dialog is not None:
                        dialog.show_qr(uri)
                    if not call_callback(on_qr, uri, what="qr"):
                        logger.info("host cancelled the login wait")
                        break
            try:
                page.wait_for_timeout(500)
            except Exception:
                break
    finally:
        terminal = _terminal_state(logged, timed_out, stuck)
        if dialog is not None:
            dialog.finish(terminal)
        elif terminal != "cancelled":
            # A host that cancelled did it from its own callback, so it already
            # knows; only report the outcomes it cannot infer.
            call_callback(on_status, terminal, what="status")

    if logged:
        return "ok"
    if timed_out:
        return "timeout"
    return "stuck" if stuck else "cancel"


def _terminal_state(logged: bool, timed_out: bool, stuck: bool) -> str:
    """Which login state closes the wait. Pure, so the truth table is testable.

    A timeout or an unmatched page is a failure, not a cancel: nobody closed
    anything, so telling the user "Cancelled" was reporting the library giving
    up as if it were their decision. The names match qr.STATE_COPY, which is
    also what a host receives through on_status.
    """
    if logged:
        return "done"
    if timed_out or stuck:
        return "failed"
    return "cancelled"


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


def _should_wait(wait_for_login: bool | None) -> bool:
    """Whether run() waits for a login when the caller did not say.

    True for every caller, quiet ones included: an explicit
    wait_for_login=False is the only way to stay fail-fast. settings.quiet is
    deliberately not an input here, because it only silences the checklist.
    """
    return True if wait_for_login is None else wait_for_login


def run(client, wait_for_login: bool | None = None,
        login_timeout_ms: int | None = None) -> list[StepResult]:
    """Run the 5 readiness checks. Raises typed LineError on first failure.

    login_timeout_ms bounds the whole login wait, whether the QR is rendered
    by the Tk dialog or by host callbacks. A value of 0 or less skips the QR
    attempt entirely and fails fast with LoginRequired.
    """
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
    # Wait for the QR by default; quiet only silences the checklist, so an
    # embedding app that wants fail-fast must pass wait_for_login=False.
    should_wait = _should_wait(wait_for_login)
    wait_ms = login_timeout_ms if login_timeout_ms is not None else settings.login_wait_ms

    last_ping = [0]

    def _tick(elapsed_ms: int) -> None:
        # Throttle progress to one line per ~10s to avoid log spam.
        if elapsed_ms - last_ping[0] >= 10000:
            last_ping[0] = elapsed_ms
            logger.info("waiting for login (%ds)", elapsed_ms // 1000)

    if not logged_in and reason == "login" and should_wait and wait_ms > 0:
        outcome = _qr_login(client, wait_ms, on_qr=client.on_qr, on_pin=client.on_pin,
                           on_status=client.on_status)
        if outcome == "fallback":
            _ensure_headed(client)
            logger.info("log in the Chrome window (Ctrl+C to cancel)")
            logged_in, reason = auth.wait_for_login(client._page, wait_ms, on_tick=_tick)
        elif outcome == "ok":
            logged_in, reason = True, "chat"
        elif outcome == "stuck":
            # The login may well have succeeded on a view we do not read, so
            # this is a rendering problem rather than a missing login.
            record("Logged in", False, detail=_UNMATCHED_PAGE)
            steps.skip_rest("page did not match a known view")
            raise AppNotReady(_UNMATCHED_PAGE)
        else:
            logged_in, reason = False, "login"
        timed_out = outcome == "timeout"
        waited_ok = logged_in
    else:
        timed_out = False
        waited_ok = False

    if waited_ok:
        detail = "logged in while waiting"
    else:
        detail = "page structure does not match known selectors" if reason == "unknown" and not logged_in else ""
    if not record("Logged in", logged_in, detail=detail,
                  hint="" if logged_in else
                  "open the LINE tab and log in with QR/email, then run again").passed:
        steps.skip_rest("waiting for login")
        if timed_out:
            # Distinct from LoginRequired so a host can tell "no session" from
            # "session needed, nobody scanned in time" and react differently.
            raise LoginTimeout(
                f"no login completed within {wait_ms}ms; raise login_timeout_ms "
                f"or log in once by hand"
            )
        raise LoginRequired("not logged in to LINE")

    # LINE lands on its own view after auth, so the chats route has to be
    # re-checked here instead of only before the login screen appeared. One
    # exit point keeps that check from being skipped on the waiting path.
    how = session.ensure_chats_view(client._page, client.settings)
    if how == "failed":
        # Not fatal here: list_rooms refuses to read a page that is not the
        # chats view, so the failure lands on the call that asked for rooms.
        logger.warning("could not reach the chats view; room queries will fail until it renders")
    _print_keep_open(client)
    return results
