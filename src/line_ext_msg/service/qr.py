"""QR login dialog controller.

Owns the separate viewer process (service.qr_view) plus the two files they
share: the QR PNG the viewer shows and a JSON status file the viewer reads
to close itself. Keeping the viewer in its own process avoids running
Tkinter and the synchronous Playwright API on the same thread.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys

from ..config import paths
from ..domain.errors import QrDialogFailed

MIN_ZOOM = 1
MAX_ZOOM = 4


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


def _write_status(path: str, state: str, **extra) -> None:
    payload = {"state": state}
    payload.update(extra)
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, path)
    except OSError:
        pass


def _remove(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


class QrDialog:
    """Owns the viewer process and the shared QR/status files."""

    def __init__(self, png: str = paths.QR_PNG, status: str = paths.QR_STATUS,
                 zoom: int = 2):
        self.png = png
        self.status = status
        self.zoom = clamp_zoom(zoom)
        self._proc: subprocess.Popen | None = None
        self._last = ""
        self._pin: tuple[str, str] | None = None

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
        """Update the PIN step shown in the dialog."""
        if (pin, desc) == self._pin:
            return
        self._pin = (pin, desc)
        _write_status(self.status, "waiting", pin=pin, desc=desc)

    def show_qr(self, data_uri: str) -> None:
        """Write the QR image and switch the dialog back to the QR state.

        Called only when a genuinely new QR appears, so a PIN that is being
        verified is never replaced by a stale QR image.
        """
        self.update(data_uri)
        self._pin = ("", "")
        _write_status(self.status, "waiting", pin="", desc="")

    def open(self, data_uri: str) -> None:
        """Write the first QR image, then launch the viewer process."""
        self.show_qr(data_uri)
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-m", "line_ext_msg.service.qr_view",
                 "--png", self.png, "--status", self.status,
                 "--zoom", str(self.zoom)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            raise QrDialogFailed(f"เปิด dialog QR ไม่ได้: {e}") from e

    def finish(self, state: str = "cancel", keep_png: bool = False) -> None:
        """Signal the viewer to close, then clean up the shared files."""
        _write_status(self.status, state)
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
