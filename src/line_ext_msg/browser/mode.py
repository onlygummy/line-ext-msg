"""Headless/headed state machine with graceful transitions.

Chrome cannot run two modes on the same profile at once, so every switch
must stop the running instance first. The stop is graceful (CDP
``Browser.close``) so Chrome flushes its session to disk before exiting;
a force kill is only the last resort. `converge` then starts the wanted
mode and verifies it, retrying once before giving up.
"""

from __future__ import annotations

import logging
import time

from ..config.settings import Settings
from ..domain.errors import ChromeNotReady
from . import chrome, process

logger = logging.getLogger(__name__)

ABSENT = "absent"
HEADLESS = "headless"
HEADED = "headed"

# After the force kill, how long to wait for the port to drop. taskkill /T
# takes the whole tree, so this only absorbs the OS teardown.
FORCE_WAIT_S = 3.0


def mode_of(settings: Settings, probe=None) -> str:
    """Current debug Chrome mode: absent, headless, or headed."""
    is_ready = probe or chrome.is_debug_ready
    if not is_ready(settings):
        return ABSENT
    return HEADLESS if chrome.is_headless(settings) else HEADED


def desired_mode(settings: Settings) -> str:
    """Mode the given settings ask for."""
    return HEADLESS if settings.headless else HEADED


def _wait_port_down(settings: Settings, timeout_s: float) -> bool:
    """Wait until the CDP endpoint stops answering, bounded by timeout."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        # Bypass the version cache: this loop must see the port die at once.
        if not chrome.is_debug_ready(settings, timeout_sec=1, use_cache=False):
            return True
        time.sleep(0.2)
    return not chrome.is_debug_ready(settings, timeout_sec=1, use_cache=False)


def _close_browser(browser) -> bool:
    """Ask Chrome to exit; True when a close was dispatched.

    A browser obtained from connect_over_cdp ignores Playwright's
    browser.close(), which only disconnects the client, so prefer the CDP
    Browser.close command: it makes the process exit and flush its session.
    """
    try:
        browser.new_browser_cdp_session().send("Browser.close")
        return True
    except Exception as e:
        logger.debug("CDP Browser.close failed: %s", e)
    try:
        browser.close()
        return True
    except Exception:
        return False


def stop(settings: Settings, browser=None, on_event=None,
         graceful_timeout_s: float | None = None, wait_port=None) -> str:
    """Stop debug Chrome: graceful CDP close first, force kill as fallback.

    Returns 'absent' when it was already down, 'graceful' when the CDP
    close brought the port down, or 'force' when a taskkill was needed.
    """
    is_ready = chrome.is_debug_ready
    wait = wait_port or _wait_port_down
    if graceful_timeout_s is None:
        graceful_timeout_s = settings.stop_graceful_ms / 1000
    if not is_ready(settings):
        return ABSENT
    graceful = browser is not None and _close_browser(browser)
    # The instance is on its way out: drop any cached version payload so the
    # next probe reads the real state instead of the dying one.
    chrome.invalidate(settings)
    if graceful and wait(settings, graceful_timeout_s):
        logger.info("Chrome closed gracefully")
        # Drop the recorded PID now: a stale one could later name a reused
        # process id and get that unrelated process killed.
        process.clear_pid(settings)
        return "graceful"
    if on_event and browser is not None and not graceful:
        on_event("graceful close failed, using force kill")
    logger.warning("force killing debug Chrome")
    process.terminate_debug_chrome(settings)
    wait(settings, FORCE_WAIT_S)
    return "force"


def converge(settings: Settings, browser=None, *, probe=None, starter=None,
             on_event=None, retries: int = 1, wait_port=None) -> str:
    """Make Chrome's mode match ``settings.headless``; returns the mode.

    ``probe`` and ``starter`` are injectable for tests. ``browser`` is the
    live Playwright handle, passed to `stop` for a graceful close.
    """
    probe = probe or mode_of
    starter = starter or chrome.start_chrome_debug
    desired = desired_mode(settings)

    current = probe(settings)
    if current == desired:
        logger.debug("mode already %s", desired)
        return current
    logger.info("switching Chrome mode: %s -> %s", current, desired)
    if on_event:
        on_event(f"switching Chrome: {current} -> {desired}")

    last = current
    for _ in range(max(0, retries) + 1):
        stop(settings, browser, on_event=on_event, wait_port=wait_port)
        # The old handle is gone after the first stop, so later retries
        # fall back to a force kill.
        browser = None
        starter(settings)
        last = probe(settings)
        if last == desired:
            return last
    logger.error("mode switch failed: wanted %s, got %s", desired, last)
    raise ChromeNotReady(f"mode switch failed: wanted {desired} but got {last}")
