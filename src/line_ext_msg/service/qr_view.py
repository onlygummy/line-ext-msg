"""Standalone Tk dialog that shows the login QR and the PIN step.

Launched as a separate process by ``service.qr``. It never touches Chrome
or Playwright: it watches the PNG for QR changes and the JSON status file
for the PIN code and the done/cancel signal, then closes itself. All Tk
usage stays in this module so the rest of the package imports fine without Tk.

The window has no buttons on purpose: closing it (the X) is the one way to
cancel, and the ``WM_DELETE_WINDOW`` handler records that in the status
file so the waiting process notices.
"""

from __future__ import annotations

import argparse
import json
import os
import tkinter as tk

from .qr import clamp_zoom

POLL_MS = 400


def _read_status(path: str) -> dict:
    """Full status dict, {} when missing or unreadable."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


class _Dialog:
    def __init__(self, png: str, status: str, zoom: int):
        self.png = png
        self.status = status
        self.zoom = clamp_zoom(zoom)
        self._photo: tk.PhotoImage | None = None
        self._mtime = -1.0
        self._pin: str = ""
        self._closed = False

        self.root = tk.Tk()
        self.root.title("LINE login")
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        self.status_label = tk.Label(self.root, text="รอสแกน QR", font=("Segoe UI", 11))
        self.status_label.pack(padx=14, pady=(14, 4))
        self.pin_label = tk.Label(self.root, text="", font=("Segoe UI", 30, "bold"), fg="#111")
        self.pin_label.pack(padx=14, pady=4)
        self.image_label = tk.Label(self.root)
        self.image_label.pack(padx=14, pady=4)
        self.hint_label = tk.Label(
            self.root, text="ปิดหน้าต่างนี้เพื่อยกเลิก", font=("Segoe UI", 9), fg="#666"
        )
        self.hint_label.pack(padx=14, pady=(2, 14))
        self.root.protocol("WM_DELETE_WINDOW", self._cancel)

    def _write_status(self, state: str) -> None:
        tmp = f"{self.status}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"state": state}, f)
            os.replace(tmp, self.status)
        except OSError:
            pass

    def _cancel(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._write_status("cancel")
        self.root.destroy()

    def _reload_image(self) -> None:
        try:
            photo = tk.PhotoImage(file=self.png)
            if self.zoom > 1:
                photo = photo.zoom(self.zoom)
        except Exception:
            # The file may be mid-replace; the next tick retries.
            return
        self._photo = photo  # keep a reference so Tk does not drop it
        self.image_label.configure(image=photo)

    def _show_pin(self, pin: str, desc: str) -> None:
        """Switch between the PIN step and the QR image."""
        if pin:
            self.status_label.configure(text=f"กรอกรหัสนี้ในมือถือ\n{desc}".strip())
            self.pin_label.configure(text=pin)
            self.image_label.configure(image="")
        else:
            self.status_label.configure(text="รอสแกน QR")
            self.pin_label.configure(text="")
            self._mtime = -1.0  # force the QR image to reload

    def _tick(self) -> None:
        if self._closed:
            return
        status = _read_status(self.status)
        state = status.get("state")
        if state in ("done", "cancel"):
            message = "ล็อกอินสำเร็จ" if state == "done" else "ยกเลิกแล้ว"
            self.status_label.configure(text=message)
            self.pin_label.configure(text="")
            self._closed = True
            self.root.after(700, self.root.destroy)
            return
        pin = status.get("pin") or ""
        if pin != self._pin:
            self._pin = pin
            self._show_pin(pin, status.get("desc") or "")
        if not pin:
            mtime = _mtime(self.png)
            if mtime and mtime != self._mtime:
                self._mtime = mtime
                self._reload_image()
        self.root.after(POLL_MS, self._tick)

    def run(self) -> None:
        self._tick()
        self.root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="LINE login dialog")
    parser.add_argument("--png", required=True, help="QR image to display")
    parser.add_argument("--status", required=True, help="JSON status file to watch")
    parser.add_argument("--zoom", type=int, default=2, help="image zoom, 1-4")
    args = parser.parse_args()
    _Dialog(args.png, args.status, args.zoom).run()


if __name__ == "__main__":
    main()
