"""Standalone Tk dialog that shows the login QR and the PIN step.

Launched as a separate process by ``service.qr``. It never touches Chrome
or Playwright: it watches the PNG for QR changes and the JSON status file
for the PIN code and the done/cancel signal, then closes itself. All Tk
usage stays in this module so the rest of the package imports fine without
Tk.

The window keeps the native title bar, so closing it (the X) is the one
way to cancel and the ``WM_DELETE_WINDOW`` handler records that in the
status file. It re-centers on the primary screen whenever its content
changes size.
"""

from __future__ import annotations

import argparse
import json
import os
import tkinter as tk

from .qr import center_xy, clamp_zoom, format_pin

POLL_MS = 400

# Light theme tokens (LINE green accent).
BG = "#FFFFFF"
TEXT = "#1A1D1F"
MUTED = "#6B7280"
GREEN = "#06C755"
AMBER = "#F59E0B"
GRAY = "#9CA3AF"
FONT = "Segoe UI"


def _enable_dpi() -> None:
    """Make text crisp on scaled displays (Windows only, best effort)."""
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


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
        self._pin = ""
        self._closed = False
        self._showing_pin = False

        _enable_dpi()
        self.root = tk.Tk()
        self.root.title("LINE")
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        try:
            self.root.tk.call("tk", "scaling", self.root.winfo_fpixels("1i") / 72.0)
        except Exception:
            pass

        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=22, pady=(18, 0))
        tk.Label(header, text="LINE", bg=BG, fg=TEXT, font=(FONT, 15, "bold")).pack(side="left")
        self.status_label = tk.Label(
            header, text="", bg=GREEN, fg=BG, font=(FONT, 10, "bold"), padx=10, pady=3
        )
        self.status_label.pack(side="right")

        content = tk.Frame(self.root, bg=BG)
        content.pack(fill="both", expand=True, padx=22, pady=(16, 16))
        self.image_label = tk.Label(content, bg=BG)
        self.pin_label = tk.Label(content, bg=BG, fg=TEXT, font=(FONT, 34, "bold"))

        self.instruction = tk.Label(self.root, text="", bg=BG, fg=MUTED, font=(FONT, 11))
        self.instruction.pack(pady=(0, 4))
        tk.Label(self.root, text="Close to cancel", bg=BG, fg=GRAY, font=(FONT, 9)).pack(
            pady=(0, 16)
        )

        self.root.protocol("WM_DELETE_WINDOW", self._cancel)
        self._set_state("waiting")

    # -- layout helpers ------------------------------------------------

    def _pill(self, text: str, color: str) -> None:
        self.status_label.configure(text=text, bg=color)

    def _show_image(self) -> None:
        self.pin_label.pack_forget()
        self.image_label.pack()
        self._showing_pin = False
        self._reload_image()

    def _show_pin(self, pin: str) -> None:
        self.image_label.pack_forget()
        self.pin_label.configure(text=format_pin(pin))
        self.pin_label.pack()
        self._showing_pin = True

    def _center(self) -> None:
        self.root.update_idletasks()
        x, y = center_xy(
            self.root.winfo_width(),
            self.root.winfo_height(),
            self.root.winfo_screenwidth(),
            self.root.winfo_screenheight(),
        )
        self.root.geometry(f"+{x}+{y}")

    def _set_state(self, state: str, pin: str = "") -> None:
        if state == "pin":
            self._pill("Enter code", AMBER)
            self.instruction.configure(text="Enter this code in the LINE app")
            self._show_pin(pin)
        elif state == "done":
            self._pill("Done", GREEN)
            self.instruction.configure(text="")
        elif state == "cancel":
            self._pill("Cancelled", GRAY)
            self.instruction.configure(text="")
        else:
            self._pill("Waiting", GREEN)
            self.instruction.configure(text="Scan with the LINE app")
            self._show_image()
        self._center()

    # -- file-driven updates -------------------------------------------

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

    def _close_soon(self, state: str) -> None:
        self._set_state(state)
        self._closed = True
        self.root.after(700, self.root.destroy)

    def _tick(self) -> None:
        if self._closed:
            return
        status = _read_status(self.status)
        state = status.get("state")
        if state == "done":
            self._close_soon("done")
            return
        if state == "cancel":
            self._close_soon("cancel")
            return
        pin = status.get("pin") or ""
        if pin != self._pin:
            self._pin = pin
            self._set_state("pin" if pin else "waiting", pin)
        if not pin and not self._showing_pin:
            mtime = _mtime(self.png)
            if mtime and mtime != self._mtime:
                self._mtime = mtime
                self._reload_image()
        self.root.after(POLL_MS, self._tick)

    def run(self) -> None:
        self._center()
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
