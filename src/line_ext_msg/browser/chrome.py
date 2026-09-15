"""Chrome lifecycle: start the debug instance and read its CDP mode."""

import logging
import os
import subprocess
import time

from ..config.settings import Settings
from . import cdp, process

logger = logging.getLogger(__name__)

# A lifecycle transition reads the same endpoint several times. Cache a
# successful payload briefly so those reads share one HTTP request; every
# start/stop invalidates the entry instead of waiting for the TTL.
_VERSION_TTL_S = 0.3
_version_cache: dict[str, tuple[float, dict]] = {}


def invalidate(settings: Settings) -> None:
    """Drop the cached /json/version payload for this endpoint."""
    _version_cache.pop(settings.cdp_endpoint, None)


def cdp_version(
    settings: Settings, timeout_sec: float = 2, use_cache: bool = True
) -> dict:
    """Parsed /json/version payload, or {} when the endpoint is unreachable."""
    endpoint = settings.cdp_endpoint
    now = time.monotonic()
    if use_cache:
        cached = _version_cache.get(endpoint)
        if cached is not None and now - cached[0] < _VERSION_TTL_S:
            return cached[1]
    payload = cdp.version(settings, timeout_sec)
    if payload:
        logger.debug("cdp version: %s", payload.get("Browser", "?"))
    # Cache successes only: a failure must stay observable to the next poll.
    if use_cache and payload:
        _version_cache[endpoint] = (now, payload)
    return payload


def is_debug_ready(
    settings: Settings, timeout_sec: float = 2, use_cache: bool = True
) -> bool:
    """Check the CDP endpoint responds with a valid Browser field."""
    ready = bool(cdp_version(settings, timeout_sec, use_cache).get("Browser"))
    logger.debug("debug ready: %s", ready)
    return ready


def is_headless(
    settings: Settings, timeout_sec: float = 2, use_cache: bool = True
) -> bool:
    """Detect a headless instance on the debug port.

    New headless mode reports 'HeadlessChrome' in the User-Agent, so the
    whole version payload is inspected instead of the Browser string only.
    """
    info = cdp_version(settings, timeout_sec, use_cache)
    headless = "headless" in _mode_blob(info)
    logger.debug("headless detect: %s", headless)
    return headless


def _mode_blob(info: dict) -> str:
    """Lowercased Browser + User-Agent text used for mode detection."""
    return f"{info.get('Browser', '')} {info.get('User-Agent', '')}".lower()


def probe(settings: Settings) -> tuple[bool, bool]:
    """Read once and return (debug_ready, headless)."""
    info = cdp_version(settings)
    if not bool(info.get("Browser")):
        return False, False
    return True, "headless" in _mode_blob(info)


def start_chrome_debug(settings: Settings) -> None:
    """Start detached Chrome on the isolated profile.

    Chrome 136+ ignores --remote-debugging-port on the default profile,
    hence the isolated dir. Login + install persist there after first setup.
    """
    from ..domain.errors import ChromeNotReady

    exe = process.find_chrome_exe()
    if exe is None:
        logger.error("chrome.exe not found in the known install paths")
        raise ChromeNotReady("chrome.exe not found. Install Google Chrome first")
    data_dir = process.expand(settings.profile_dir)
    if process.is_profile_locked(data_dir):
        logger.error("profile is locked: %s", data_dir)
        raise ChromeNotReady("Chrome profile is in use. Close the old debug window and run again")
    os.makedirs(data_dir, exist_ok=True)
    # Open LINE chats as the first tab so no New Tab lingers at index 0.
    # Headless is the default: no window unless login needs a QR scan. The
    # two extra flags skip first-run work that only slows the boot down.
    args = [
        exe,
        f"--remote-debugging-port={settings.port}",
        f"--user-data-dir={data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        # No web or push notifications, and no "Restore pages?" bubble after
        # a force kill (the profile records exit_type Crashed).
        "--disable-notifications",
        "--hide-crash-restore-bubble",
    ]
    if settings.headless:
        args.append("--headless=new")
    args.append(settings.chats_url)
    logger.info("starting Chrome (headless=%s) on port %s", settings.headless, settings.port)
    logger.debug("chrome args: %s", args)
    child = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
    )
    process.write_pid(settings, child.pid)
    invalidate(settings)
    _wait_debug_port(settings)


def _wait_debug_port(settings: Settings) -> None:
    """Poll the CDP port, backing off after the first couple of seconds.

    Chrome normally answers within a second, so poll fast at first and
    relax later; the overall budget stays 15s.
    """
    from ..domain.errors import ChromeNotReady

    start = time.monotonic()
    while True:
        elapsed = time.monotonic() - start
        timeout = 0.3 if elapsed < 2.0 else 0.5
        if is_debug_ready(settings, timeout_sec=timeout, use_cache=False):
            logger.info("Chrome debug port is up")
            return
        if time.monotonic() - start >= 15.0:
            break
        time.sleep(0.1 if elapsed < 2.0 else 0.3)
    logger.error("Chrome started but the debug port stayed silent for 15s")
    raise ChromeNotReady("Chrome started but the debug port did not respond within 15s")


def port_hint(settings: Settings) -> str:
    """One-line hint for CDP port conflicts (pure, no side effects)."""
    return (
        f"port {settings.port} is in use. Check with: "
        f"netstat -ano | findstr {settings.port} "
        "or change it with LINE_EXT_MSG_PORT"
    )


def ensure_chrome(settings: Settings) -> None:
    """Ensure a debug Chrome on our port is running.

    Detach-only lifecycle: callers must not kill Chrome on exit. A running
    instance is reused whatever its mode, because restarting it would drop
    the in-memory LINE session; the expected-mode check only introduced a
    profile-lock failure here. Mode switches belong to browser.mode.converge.
    """
    from ..domain.errors import ChromeNotReady

    if probe(settings)[0]:
        logger.debug("Chrome already running; reusing it")
        return
    try:
        start_chrome_debug(settings)
    except ChromeNotReady as e:
        # Attach the port hint so a squatter port is actionable at once.
        raise ChromeNotReady(f"{e} ({port_hint(settings)})") from e
