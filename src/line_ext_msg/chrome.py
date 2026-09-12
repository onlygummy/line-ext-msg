"""Chrome lifecycle: ensure a debuggable instance on the isolated profile."""

import os
import subprocess
import time
import urllib.request

from .settings import Settings


def expand(path: str) -> str:
    """Expand %VAR% on Windows and ~ on all platforms."""
    return os.path.expandvars(os.path.expanduser(path))


def find_chrome_exe() -> str | None:
    """Search common install locations, return exe path or None."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        expand(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def is_debug_ready(settings: Settings, timeout_sec: int = 2) -> bool:
    """Check CDP endpoint responds with valid Browser field."""
    try:
        with urllib.request.urlopen(f"{settings.cdp_endpoint}/json/version", timeout=timeout_sec) as res:
            return "Browser" in res.read().decode("utf-8", errors="ignore")
    except Exception:
        return False


def is_headless(settings: Settings, timeout_sec: int = 2) -> bool:
    """Detect a headless instance squatting the debug port (no visible window)."""
    try:
        with urllib.request.urlopen(f"{settings.cdp_endpoint}/json/version", timeout=timeout_sec) as res:
            return "Headless" in res.read().decode("utf-8", errors="ignore")
    except Exception:
        return False


def _is_profile_locked(data_dir: str) -> bool:
    """Detect SingletonLock (profile in use by a normal window)."""
    return any(
        os.path.exists(os.path.join(data_dir, name))
        for name in ("SingletonLock", "SingletonSocket", "SingletonCookie")
    )


def start_chrome_debug(settings: Settings) -> None:
    """Start detached Chrome on the isolated profile.

    Chrome 136+ ignores --remote-debugging-port on the default profile,
    hence the isolated dir. Login + install persist there after first setup.
    """
    from .errors import ChromeNotReady

    exe = find_chrome_exe()
    if exe is None:
        raise ChromeNotReady("ไม่พบ chrome.exe กรุณาติดตั้ง Chrome ก่อน")
    data_dir = expand(settings.profile_dir)
    if _is_profile_locked(data_dir):
        raise ChromeNotReady("โปรไฟล์ Chrome ถูกใช้อยู่ ปิดหน้าต่าง debug เก่าก่อนแล้วรันใหม่")
    os.makedirs(data_dir, exist_ok=True)
    subprocess.Popen(
        [exe, f"--remote-debugging-port={settings.port}", f"--user-data-dir={data_dir}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
    )
    for _ in range(30):
        if is_debug_ready(settings, timeout_sec=1):
            return
        time.sleep(0.5)
    raise ChromeNotReady("เปิด Chrome แล้วแต่พอร์ต debug ไม่ตอบใน 15 วิ")


def ensure_chrome(settings: Settings) -> None:
    """Ensure headed debug Chrome is running; start it if the port is closed."""
    from .errors import ChromeNotReady

    if is_debug_ready(settings):
        if is_headless(settings):
            raise ChromeNotReady(
                "พอร์ต debug ถูกโปรแกรมอื่น (headless) ใช้อยู่ ไม่มีหน้าต่างให้เห็น "
                "รัน: Get-Process chrome | Stop-Process -Force แล้วรันใหม่"
            )
        return
    start_chrome_debug(settings)
