"""QR login dialog controller.

Owns the separate viewer process (service.qr_view) plus the two files they
share: the QR PNG the viewer shows and a JSON status file the viewer reads
to close itself. Keeping the viewer in its own process avoids running
Tkinter and the synchronous Playwright API on the same thread.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys

from ..config import paths
from ..domain.errors import QrDialogFailed
from .qr_status import write_status

MIN_ZOOM = 1
MAX_ZOOM = 4

# The login flow has a single state machine and two renderers for it: the Tk
# dialog, and a host that receives the same names through on_status. The
# vocabulary lives here rather than in qr_view so the whole contract is
# testable without importing Tkinter.
#
# state: (pill text, instruction, tone)
STATE_COPY: dict[str, tuple[str, str, str]] = {
    "waiting": ("Waiting", "Scan with the LINE app", "green"),
    "pin": ("Enter code", "Enter this code in the LINE app", "amber"),
    "verifying": ("Signing in", "LINE is opening your chats", "green"),
    "done": ("Done", "", "green"),
    "failed": ("Could not continue", "", "red"),
    "cancelled": ("Cancelled", "", "gray"),
}

# States the viewer renders and then shuts down on.
TERMINAL_STATES = frozenset({"done", "failed", "cancelled"})

# Horizontal padding around the content box, on each side.
CARD_PAD = 22

# Floor for the content box, so a tiny or unreadable QR cannot collapse it.
MIN_CARD = (200, 120)


def card_size(
    image: tuple[int, int] | None,
    text_width: int,
    text_height: int,
    pad_x: int = CARD_PAD,
) -> tuple[int, int]:
    """Content box that keeps the window the same size in every login state.

    The instruction line, the status pill and the footer all sit outside this
    frame, so whichever of them is longest would otherwise become the widest
    thing in the window and the size would depend on the state again. The box is
    therefore widened until the frame plus its own padding covers all of them.
    The image is a floor too, so a bigger QR is never clipped.

    Pure: the caller measures the text, which keeps this testable without Tk.
    """
    width = max(text_width - 2 * pad_x, MIN_CARD[0])
    height = max(text_height, MIN_CARD[1])
    if image is not None:
        width = max(width, image[0])
        height = max(height, image[1])
    return width, height


def clamp_zoom(value) -> int:
    """Clamp a QR zoom to 1-4; bad values fall back to 2. Pure (unit-testable)."""
    try:
        zoom = int(value)
    except (TypeError, ValueError):
        zoom = 2
    return max(MIN_ZOOM, min(MAX_ZOOM, zoom))


def center_xy(win_w: int, win_h: int, screen_w: int, screen_h: int,
              bias: float = 0.45) -> tuple[int, int]:
    """Top-left coordinate that centers a window. bias < 0.5 sits higher. Pure."""
    x = int((screen_w - win_w) / 2)
    y = int((screen_h - win_h) * bias)
    return max(0, x), max(0, y)


def format_pin(pin: str) -> str:
    """Space out PIN digits so they read easily. Pure (unit-testable)."""
    text = (pin or "").strip()
    if len(text) < 2:
        return text
    return " ".join(text)


def clean_title(text: str | None) -> str:
    """Trim a dialog title; blank or missing falls back to LINE. Pure."""
    title = (text or "").strip()
    return title or "LINE"


def data_uri_to_bytes(data_uri: str) -> bytes:
    """Decode a base64 image data URI to bytes. Pure (unit-testable)."""
    if not data_uri:
        return b""
    _, _, payload = data_uri.partition(",")
    if not payload:
        return b""
    try:
        return base64.b64decode(payload)
    except Exception:
        return b""


def _atomic_write(path: str, data: bytes) -> None:
    """Write bytes via a temp file + replace so the viewer never reads half."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _remove(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


class QrDialog:
    """Owns the viewer process and the shared QR/status files."""

    def __init__(self, png: str = paths.QR_PNG, status: str = paths.QR_STATUS,
                 zoom: int = 2, title: str = "LINE"):
        self.png = png
        self.status = status
        self.zoom = clamp_zoom(zoom)
        self.title = clean_title(title)
        self._proc: subprocess.Popen | None = None
        self._last = ""
        self._pin: tuple[str, str] = ("", "")
        self._verifying = False

    def alive(self) -> bool:
        """True while the viewer process is still running."""
        return self._proc is not None and self._proc.poll() is None

    def update(self, data_uri: str) -> bool:
        """Write a new PNG when the data URI changed. True when written."""
        if not data_uri or data_uri == self._last:
            return False
        data = data_uri_to_bytes(data_uri)
        if not data:
            return False
        self._last = data_uri
        _atomic_write(self.png, data)
        return True

    def set_pin(self, pin: str, desc: str = "") -> None:
        """Show the PIN step in the dialog."""
        # While verifying, the same PIN reappearing means the previous
        # verification was rejected and the user has to type it again. The
        # dedup below would swallow that, leaving the dialog on its spinner.
        if (pin, desc) == self._pin and not self._verifying:
            return
        self._verifying = False
        self._pin = (pin, desc)
        write_status(self.status, "pin", pin=pin, desc=desc)

    def set_verifying(self) -> None:
        """The code was submitted and LINE is switching views, so there is
        nothing left for the user to do.

        The previous step is kept so resume() can fall back to it, and so a
        rejected PIN still knows what to restore.
        """
        self._verifying = True
        write_status(self.status, "verifying")

    def resume(self) -> None:
        """Leave the verifying state for the step the user was on.

        Called when the login screen comes back, which means the unknown state
        was a rendering hiccup rather than a session on another view. A host
        callback needs no equivalent event: it keeps showing its last payload.
        """
        if not self._verifying:
            return
        self._verifying = False
        pin, desc = self._pin
        write_status(self.status, "pin" if pin else "waiting", pin=pin, desc=desc)

    def show_qr(self, data_uri: str) -> None:
        """Write the QR image and switch the dialog back to the QR state.

        Called only when a genuinely new QR appears, so a PIN that is being
        verified is never replaced by a stale QR image.
        """
        self.update(data_uri)
        self._verifying = False
        self._pin = ("", "")
        write_status(self.status, "waiting", pin="", desc="")

    def open(self, data_uri: str) -> None:
        """Write the first QR image, then launch the viewer process."""
        self.show_qr(data_uri)
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-m", "line_ext_msg.service.qr_view",
                 "--png", self.png, "--status", self.status,
                 "--zoom", str(self.zoom), "--title", self.title],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            raise QrDialogFailed(f"could not open the QR dialog: {e}") from e

    def finish(self, state: str = "cancelled", keep_png: bool = False) -> None:
        """Signal the viewer to close, then clean up the shared files."""
        write_status(self.status, state)
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
            try:
                proc.wait(timeout=1)
            except Exception:
                pass
        self._proc = None
        _remove(self.status)
        if not keep_png:
            _remove(self.png)
