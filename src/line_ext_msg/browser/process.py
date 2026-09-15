"""OS-level helpers: locate Chrome, expand paths, kill debug processes.

Windows-first for now. All platform-specific code stays in this module so
supporting another OS later is a change in one place.
"""

import os

from ..config import paths
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


def write_pid(settings: Settings, pid: int) -> None:
    """Record the PID of the debug Chrome we just launched."""
    path = expand(paths.CHROME_PID)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(str(int(pid)))
    except OSError:
        pass  # a missing PID file only costs us the slow fallback later


def read_pid(settings: Settings) -> int | None:
    """PID recorded by write_pid, or None when absent or unreadable."""
    try:
        with open(expand(paths.CHROME_PID), encoding="utf-8") as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def clear_pid(settings: Settings) -> None:
    """Drop the recorded PID once that Chrome is gone."""
    try:
        os.remove(expand(paths.CHROME_PID))
    except OSError:
        pass


def _taskkill_tree(pid: int) -> bool:
    """Force-kill one process and its children; True when taskkill succeeded."""
    import subprocess as _sp

    try:
        done = _sp.run(
            ["taskkill", "/F", "/PID", str(pid), "/T"],
            capture_output=True, timeout=15,
        )
    except Exception:
        return False
    return done.returncode == 0


def _debug_chrome_pids(marker: str) -> list[int]:
    """PIDs of chrome.exe processes whose command line carries our profile.

    wmic is gone on recent Windows, so ask PowerShell (CIM) instead. This
    spawn is the slow path; the recorded PID normally makes it unnecessary.
    """
    import subprocess as _sp

    ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" "
          f"| Where-Object {{$_.CommandLine -like '*{marker}*'}} "
          "| Select-Object -ExpandProperty ProcessId")
    try:
        out = _sp.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except Exception:
        return []
    pids: list[int] = []
    for line in out.splitlines():
        try:
            pids.append(int(line.strip()))
        except (TypeError, ValueError):
            continue
    return pids


def terminate_debug_chrome(settings: Settings) -> None:
    """Force-kill ONLY the debug-profile Chrome processes.

    Fast path: the PID recorded at launch, killed with a single
    taskkill /T that takes the whole process tree. Fallback: enumerate
    debug-profile PIDs through PowerShell, for Chrome started by an older
    run that left no PID file. Never touches the user's normal Chrome
    (different profile, so the command-line marker does not match).
    """
    pid = read_pid(settings)
    if pid is not None and _taskkill_tree(pid):
        clear_pid(settings)
        return
    for other in _debug_chrome_pids(profile_marker(settings)):
        _taskkill_tree(other)
    clear_pid(settings)
