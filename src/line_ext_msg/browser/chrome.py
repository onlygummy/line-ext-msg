"""Chrome lifecycle: start the debug instance and read its CDP mode."""

import json
import logging
import os
import subprocess
import time
import urllib.request

from ..config.settings import Settings
from . import process

logger = logging.getLogger(__name__)


def cdp_version(settings: Settings, timeout_sec: int = 2) -> dict:
    """Parsed /json/version payload, or {} when the endpoint is unreachable."""
    try:
        with urllib.request.urlopen(
            f"{settings.cdp_endpoint}/json/version", timeout=timeout_sec
        ) as res:
            data = json.loads(res.read().decode("utf-8", errors="ignore"))
        payload = data if isinstance(data, dict) else {}
        logger.debug("cdp version: %s", payload.get("Browser", "?"))
        return payload
    except Exception as e:
        logger.debug("cdp version probe failed: %s", e)
        return {}


def is_debug_ready(settings: Settings, timeout_sec: int = 2) -> bool:
    """Check the CDP endpoint responds with a valid Browser field."""
    ready = bool(cdp_version(settings, timeout_sec).get("Browser"))
    logger.debug("debug ready: %s", ready)
    return ready


def is_headless(settings: Settings, timeout_sec: int = 2) -> bool:
    """Detect a headless instance on the debug port.

    New headless mode reports 'HeadlessChrome' in the User-Agent, so the
    whole version payload is inspected instead of the Browser string only.
    """
    info = cdp_version(settings, timeout_sec)
    blob = f"{info.get('Browser', '')} {info.get('User-Agent', '')}"
    headless = "headless" in blob.lower()
    logger.debug("headless detect: %s", headless)
    return headless


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
    # Headless is the default: no window unless login needs a QR scan.
    args = [exe, f"--remote-debugging-port={settings.port}", f"--user-data-dir={data_dir}"]
    if settings.headless:
        args.append("--headless=new")
    args.append(settings.chats_url)
    logger.info("starting Chrome (headless=%s) on port %s", settings.headless, settings.port)
    logger.debug("chrome args: %s", args)
    subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
    )
    for _ in range(30):
        if is_debug_ready(settings, timeout_sec=1):
            logger.info("Chrome debug port is up")
            return
        time.sleep(0.5)
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
    """Ensure debug Chrome is running in the expected mode (headless default).

    Detach-only lifecycle: callers must not kill Chrome on exit. Mode
    switches are handled by browser.mode.converge; this keeps the simple
    start-if-absent path for debugging helpers.
    """
    from ..domain.errors import ChromeNotReady

    if is_debug_ready(settings) and is_headless(settings) == settings.headless:
        logger.debug("Chrome already running in the expected mode")
        return
    try:
        start_chrome_debug(settings)
    except ChromeNotReady as e:
        # Attach the port hint so a squatter port is actionable at once.
        raise ChromeNotReady(f"{e} ({port_hint(settings)})") from e
