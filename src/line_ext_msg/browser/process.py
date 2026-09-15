"""OS-level helpers: locate Chrome, expand paths, kill debug processes.

Windows-first for now. All platform-specific code stays in this module so
supporting another OS later is a change in one place.
"""

import os

from ..config.settings import Settings


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


def is_profile_locked(data_dir: str) -> bool:
    """Detect SingletonLock (profile in use by a normal window)."""
    return any(
        os.path.exists(os.path.join(data_dir, name))
        for name in ("SingletonLock", "SingletonSocket", "SingletonCookie")
    )


def profile_marker(settings: Settings) -> str:
    """Substring identifying the debug profile in a process command line."""
    return os.path.basename(expand(settings.profile_dir)) or "line-chrome-debug"


def terminate_debug_chrome(settings: Settings) -> None:
    """Force-kill ONLY the debug-profile Chrome processes.

    Last-resort fallback when a graceful CDP close does not finish in
    time. Never touches the user's normal Chrome (different profile, so
    the command-line marker does not match).
    """
    import subprocess as _sp

    marker = profile_marker(settings)
    # wmic is gone on recent Windows: ask PowerShell (CIM) for PIDs instead.
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" "
          f"| Where-Object {{$_.CommandLine -like '*{marker}*'}} "
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
