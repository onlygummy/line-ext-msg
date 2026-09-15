"""Chrome lifecycle: start the debug instance and read its CDP mode."""

import json
import os
import subprocess
import time
import urllib.request

from ..config.settings import Settings
from . import process


def cdp_version(settings: Settings, timeout_sec: int = 2) -> dict:
    """Parsed /json/version payload, or {} when the endpoint is unreachable."""
    try:
        with urllib.request.urlopen(
            f"{settings.cdp_endpoint}/json/version", timeout=timeout_sec
        ) as res:
            data = json.loads(res.read().decode("utf-8", errors="ignore"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def is_debug_ready(settings: Settings, timeout_sec: int = 2) -> bool:
    """Check the CDP endpoint responds with a valid Browser field."""
    return bool(cdp_version(settings, timeout_sec).get("Browser"))


def is_headless(settings: Settings, timeout_sec: int = 2) -> bool:
    """Detect a headless instance on the debug port.

    New headless mode reports 'HeadlessChrome' in the User-Agent, so the
    whole version payload is inspected instead of the Browser string only.
    """
    info = cdp_version(settings, timeout_sec)
    blob = f"{info.get('Browser', '')} {info.get('User-Agent', '')}"
    return "headless" in blob.lower()


def start_chrome_debug(settings: Settings) -> None:
    """Start detached Chrome on the isolated profile.

    Chrome 136+ ignores --remote-debugging-port on the default profile,
    hence the isolated dir. Login + install persist there after first setup.
    """
    from ..domain.errors import ChromeNotReady

    exe = process.find_chrome_exe()
    if exe is None:
        raise ChromeNotReady("ไม่พบ chrome.exe กรุณาติดตั้ง Chrome ก่อน")
    data_dir = process.expand(settings.profile_dir)
    if process.is_profile_locked(data_dir):
        raise ChromeNotReady("โปรไฟล์ Chrome ถูกใช้อยู่ ปิดหน้าต่าง debug เก่าก่อนแล้วรันใหม่")
    os.makedirs(data_dir, exist_ok=True)
    # Open LINE chats as the first tab so no New Tab lingers at index 0.
    # Headless is the default: no window unless login needs a QR scan.
    args = [exe, f"--remote-debugging-port={settings.port}", f"--user-data-dir={data_dir}"]
    if settings.headless:
        args.append("--headless=new")
    args.append(settings.chats_url)
    subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
    )
    for _ in range(30):
        if is_debug_ready(settings, timeout_sec=1):
            return
        time.sleep(0.5)
    raise ChromeNotReady("เปิด Chrome แล้วแต่พอร์ต debug ไม่ตอบใน 15 วิ")


def port_hint(settings: Settings) -> str:
    """One-line hint for CDP port conflicts (pure, no side effects)."""
    return (
        f"พอร์ต {settings.port} ถูกใช้อยู่ ตรวจด้วย: "
        f"netstat -ano | findstr {settings.port} "
        "หรือย้ายพอร์ตด้วย LINE_EXT_MSG_PORT"
    )


def ensure_chrome(settings: Settings) -> None:
    """Ensure debug Chrome is running in the expected mode (headless default).

    Detach-only lifecycle: callers must not kill Chrome on exit. Mode
    switches are handled by browser.mode.converge; this keeps the simple
    start-if-absent path for debugging helpers.
    """
    from ..domain.errors import ChromeNotReady

    if is_debug_ready(settings) and is_headless(settings) == settings.headless:
        return
    try:
        start_chrome_debug(settings)
    except ChromeNotReady as e:
        # Attach the port hint so a squatter port is actionable at once.
        raise ChromeNotReady(f"{e} ({port_hint(settings)})") from e
