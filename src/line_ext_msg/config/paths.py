"""Default output paths. Every CLI artifact lives under SESSION_DIR.

Forward slashes are kept on purpose: Python accepts them on Windows and
they match the paths printed by earlier releases.
"""

SESSION_DIR = "session"
DUMPS_DIR = f"{SESSION_DIR}/dumps"
MEDIA_DIR = f"{SESSION_DIR}/media"
ROOMS_JSON = f"{SESSION_DIR}/rooms.json"
PROBE_JSON = f"{SESSION_DIR}/session_probe.json"
PROBE_BEFORE_CLEAR_JSON = f"{SESSION_DIR}/session_probe_before_clear.json"
PAGE_DUMP = f"{DUMPS_DIR}/line_dom.html"
ROOM_DUMP = f"{DUMPS_DIR}/line_room.html"

# Login QR dialog: the image the viewer shows and the state file the
# viewer watches to close itself (both removed when the login ends).
QR_PNG = f"{SESSION_DIR}/qr.png"
QR_STATUS = f"{SESSION_DIR}/qr_status.json"

# PID of the debug Chrome we started, so a stop can taskkill the tree once
# instead of enumerating processes through PowerShell.
CHROME_PID = f"{SESSION_DIR}/chrome.pid"


def messages_json(index: int) -> str:
    """Path of the per-room messages file for a room index."""
    return f"{SESSION_DIR}/messages_{index}.json"
