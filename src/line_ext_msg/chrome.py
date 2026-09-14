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


def terminate_debug_chrome(settings: Settings) -> None:
    """Kill only Chrome processes of the isolated debug profile.

    Needed to switch headless/headed (same user-data-dir cannot run both).
    Never touches the user's normal Chrome (different profile, no match).
    """
    import subprocess as _sp

    # wmic is gone on recent Windows: ask PowerShell (CIM) for PIDs instead.
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" "
          "| Where-Object {$_.CommandLine -like '*line-chrome-debug*'} "
          "| Select-Object -ExpandProperty ProcessId")
    try:
        out = _sp.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except Exception:
        return
    for line in out.splitlines():
        try:
            pid = int(line.strip())
        except (TypeError, ValueError):
            continue
        try:
            _sp.run(["taskkill", "/F", "/PID", str(pid), "/T"],
                    capture_output=True, timeout=15)
        except Exception:
            pass


def ensure_chrome(settings: Settings) -> None:
    """Ensure debug Chrome is running in the expected mode (headless default).

    Detach-only lifecycle: callers must not kill Chrome on exit. Mode
    switches (headless/headed) are explicit via terminate_debug_chrome.
    """
    from .errors import ChromeNotReady

    if is_debug_ready(settings):
        want_headless = settings.headless
        got_headless = is_headless(settings)
        if want_headless == got_headless:
            return
        # Wrong mode on the port: restart in the expected mode.
        terminate_debug_chrome(settings)
        for _ in range(20):
            if not is_debug_ready(settings):
                break
            try:
                __import__("time").sleep(0.5)
            except Exception:
                break
    try:
        start_chrome_debug(settings)
    except ChromeNotReady as e:
        # Attach the port hint so a squatter port is actionable at once.
        raise ChromeNotReady(f"{e} ({port_hint(settings)})") from e
