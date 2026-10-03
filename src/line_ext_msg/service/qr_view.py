"""Standalone Tk dialog that shows the login QR and the PIN step.

Launched as a separate process by ``service.qr``. It never touches Chrome
or Playwright: it watches the status file for the login state and the QR PNG
for image changes, then closes itself. The state names and their copy come from
``service.qr`` so both renderers, this dialog and a host's on_status callback,
agree on one vocabulary. All Tk usage stays in this module so the rest of the
package imports fine without Tk.

The window keeps the native title bar, so closing it (the X) is the one
way to cancel and the ``WM_DELETE_WINDOW`` handler records that in the
status file. Its size is fixed: the content frame stops following its
children, so the QR, the code and the spinner all occupy the same box and
the window does not jump between states. Everything inside that box is
centred on both axes. The window is centred once, when the QR has been
measured, rather than on every state change, so a window the user moved by
hand stays where they put it.
"""

from __future__ import annotations

import argparse
import json
import os
import tkinter as tk
from tkinter import font as tkfont

from .qr import (
    CARD_PAD,
    MIN_CARD,
    STATE_COPY,
    TERMINAL_STATES,
    card_size,
    center_xy,
    clamp_zoom,
    clean_title,
    format_pin,
)
from .qr_status import write_status

POLL_MS = 400
SPIN_MS = 80

# Light theme tokens (LINE green accent).
BG = "#FFFFFF"
TEXT = "#1A1D1F"
MUTED = "#6B7280"
GREEN = "#06C755"
AMBER = "#F59E0B"
RED = "#EF4444"
GRAY = "#9CA3AF"
FONT = "Segoe UI"

# One spec per role, used both to build the labels and to measure the copy, so
# the size floor cannot drift from what actually gets rendered.
PILL_FONT = (FONT, 10, "bold")
BODY_FONT = (FONT, 11)
SMALL_FONT = (FONT, 9)
PIN_FONT = (FONT, 34, "bold")
FOOTER_TEXT = "Close to cancel"

# Used when Tk cannot measure text at all. Generous on purpose: an oversized box
# is harmless, a clipped instruction is not.
FALLBACK_EXTENT = (460, 120)

# Pill colour per tone named in qr.STATE_COPY.
TONE_COLOR = {"green": GREEN, "amber": AMBER, "red": RED, "gray": GRAY}


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
    def __init__(self, png: str, status: str, zoom: int, title: str = "LINE"):
        self.png = png
        self.status = status
        self.zoom = clamp_zoom(zoom)
        self.title = clean_title(title)
        self._photo: tk.PhotoImage | None = None
        self._mtime = -1.0
        self._closed = False
        # What is on screen right now, as (state, pin). One comparison replaces
        # the old "is the pin field empty" test, which could not tell a state
        # change that carried no payload from no change at all.
        self._shown: tuple[str, str] = ("waiting", "")
        self._showing_pin = False
        self.spinner: tk.Canvas | None = None
        self._arc: int | None = None
        self._angle = 0
        self._spinning = False
        self._size: tuple[int, int] | None = None
        self._centred = False

        _enable_dpi()
        self.root = tk.Tk()
        self.root.title(self.title)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        try:
            self.root.tk.call("tk", "scaling", self.root.winfo_fpixels("1i") / 72.0)
        except Exception:
            pass

        # The pill is the only thing on this row: the app name lives in the
        # window title bar, so the card header stays empty on the left.
        header = tk.Frame(self.root, bg=BG)
        header.pack(side="top", fill="x", padx=CARD_PAD, pady=(18, 0))
        self.status_label = tk.Label(
            header, text="", bg=GREEN, fg=BG, font=PILL_FONT, padx=10, pady=3
        )
        self.status_label.pack(side="right")

        # Header above, caption below, box between them. Pinning the two ends to
        # their own edges is what leaves the box in the space in between, so
        # the QR, the code and the spinner all sit centred in the window on both
        # axes rather than pushed down under the header.
        tk.Label(self.root, text=FOOTER_TEXT, bg=BG, fg=GRAY,
                 font=SMALL_FONT).pack(side="bottom", pady=(0, 16))
        self.instruction = tk.Label(self.root, text="", bg=BG, fg=MUTED, font=BODY_FONT)
        self.instruction.pack(side="bottom", pady=(0, 4))

        # pack_propagate(False) in _resize is what holds the size. The children
        # are placed rather than packed, so they cannot drive it either way:
        # place centres on both axes with relx/rely and never contributes to its
        # parent's geometry, which pack cannot promise for both.
        self.content = tk.Frame(self.root, bg=BG)
        self.content.pack(side="top", fill="both", expand=True,
                          padx=CARD_PAD, pady=(16, 16))
        self.image_label = tk.Label(self.content, bg=BG)
        self.pin_label = tk.Label(self.content, bg=BG, fg=TEXT, font=PIN_FONT)

        self.root.protocol("WM_DELETE_WINDOW", self._cancel)
        # Size to the copy first, so the floor exists before anything is shown.
        self._extent = self._text_extent()
        self._resize(*card_size(None, *self._extent))
        self._set_state("waiting")

    # -- layout helpers ------------------------------------------------

    def _text_extent(self) -> tuple[int, int]:
        """Widest and tallest copy shown outside the content box.

        Measured with the same font specs the labels are built from. At 150%
        scaling a long instruction is a third wider than at 100%, and a fixed
        constant would stop covering it, putting the state back in charge of
        the window width.
        """
        try:
            pill = tkfont.Font(family=FONT, size=10, weight="bold")
            body = tkfont.Font(family=FONT, size=11)
            small = tkfont.Font(family=FONT, size=9)
            pin = tkfont.Font(family=FONT, size=34, weight="bold")
            widths = [
                pin.measure(format_pin("123456")),
                small.measure(FOOTER_TEXT),
                *(pill.measure(label) for label, _text, _tone in STATE_COPY.values()),
                *(body.measure(text) for _l, text, _t in STATE_COPY.values() if text),
            ]
            heights = [f.metrics("linespace") for f in (pill, body, small, pin)]
            return max(widths), max(heights)
        except Exception:
            return FALLBACK_EXTENT

    def _resize(self, width: int, height: int) -> None:
        """Fix the content box, and re-centre only when the size really changed.

        Tk maps the root when the event loop starts, so a resize before that is
        free. Re-centring only on a real change means a window the user moved by
        hand is not yanked back on the next state change.
        """
        if self._size == (width, height):
            return
        self._size = (width, height)
        self.content.configure(width=width, height=height)
        self.content.pack_propagate(False)
        self._center()

    def _pill(self, text: str, color: str) -> None:
        self.status_label.configure(text=text, bg=color)

    def _place_centred(self, widget) -> None:
        """Centre one child in the content box on both axes, hiding the rest.

        place rather than pack: a placed child never contributes to its
        parent's geometry, so swapping the QR, the code and the spinner cannot
        resize the box, and relx/rely centre on both axes directly instead of
        depending on the parcel pack would carve out. Passing None clears the
        box.
        """
        for other in (self.image_label, self.pin_label, self.spinner):
            if other is not None and other is not widget:
                other.place_forget()
        if widget is not None:
            widget.place(relx=0.5, rely=0.5, anchor="center")

    def _start_spinner(self) -> None:
        """Show a rotating arc where the QR or PIN was.

        Nothing in this flow is instant after the PIN is submitted, and a
        frozen code the user already typed reads as a hang. Sized from the
        content box rather than fixed, so it does not look lost in a large one.
        """
        if self.spinner is None:
            side = max(64, min(160, int(min(self._size or MIN_CARD) * 0.35)))
            inset = side * 0.1
            self.spinner = tk.Canvas(self.content, width=side, height=side,
                                     bg=BG, highlightthickness=0)
            self._arc = self.spinner.create_arc(
                inset, inset, side - inset, side - inset, start=0, extent=100,
                style="arc", outline=GREEN, width=max(2, side // 16),
            )
        self._place_centred(self.spinner)
        self._spinning = True
        self._spin()

    def _spin(self) -> None:
        if self._closed or not self._spinning or self.spinner is None:
            return
        self._angle = (self._angle + 30) % 360
        self.spinner.itemconfigure(self._arc or 0, start=self._angle)
        self.spinner.after(SPIN_MS, self._spin)

    def _stop_spinner(self) -> None:
        """Stop the arc where it is, without taking it off screen.

        A terminal state uses this: a frozen arc reads as "that is where it got
        to", while an empty box reads as a bug. Visibility is _place_centred's
        job, so there is nothing else to undo here.
        """
        self._spinning = False

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
        """Render one login state.

        Declarative on purpose: everything is hidden first, then only what the
        state needs is shown, so a branch that forgot to hide the previous
        content cannot leave a stale PIN under a new pill.

        A terminal state is the exception. It leaves the content alone, which is
        what the pre-3.1.0 viewer did and what makes the outcome legible: the
        QR or the code the user typed is still there to look at, and on failed
        the code is still there to retype. Nothing moves either way now that
        the box no longer resizes.
        """
        label, instruction, tone = STATE_COPY.get(state, STATE_COPY["waiting"])
        self._pill(label, TONE_COLOR[tone])
        self.instruction.configure(text=instruction)
        # Always stop the arc first: a terminal state leaves it frozen where it
        # got to, and any other state is about to swap the content out anyway.
        self._stop_spinner()
        if state in TERMINAL_STATES:
            return
        self._showing_pin = False
        if state == "pin":
            self.pin_label.configure(text=format_pin(pin))
            self._place_centred(self.pin_label)
            self._showing_pin = True
        elif state == "verifying":
            self._start_spinner()
        elif state == "waiting":
            self._place_centred(self.image_label)
            self._reload_image()

    # -- file-driven updates -------------------------------------------

    def _cancel(self) -> None:
        if self._closed:
            return
        self._closed = True
        # The controller learns about this from the process exiting, not from
        # the file, but recording it keeps the payload honest for anything
        # reading it.
        write_status(self.status, "cancelled")
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
        # The image is the only state whose size the user picks, through zoom,
        # so it is the one that can push the box wider than the copy needs.
        self._resize(*card_size((photo.width(), photo.height()), *self._extent))

    def _close_soon(self, state: str) -> None:
        self._set_state(state)
        self._closed = True
        self.root.after(700, self.root.destroy)

    def _tick(self) -> None:
        if self._closed:
            return
        if not self._centred:
            # Belt and braces for the initial position: _resize already asked
            # for it before the window was mapped, but a geometry request made
            # that early is not honoured on every Tk build. Doing it once from
            # inside the loop makes sure, and only once so a window the user
            # moves afterwards stays where they put it.
            self._centred = True
            self._center()
        status = _read_status(self.status)
        state = status.get("state") or "waiting"
        if state in TERMINAL_STATES:
            self._close_soon(state)
            return
        pin = status.get("pin") or ""
        if (state, pin) != self._shown:
            self._shown = (state, pin)
            self._set_state(state, pin)
        # The QR image only changes while it is the step on screen; reloading
        # it under a PIN or a spinner would just repaint a hidden label.
        if state == "waiting" and not self._showing_pin:
            mtime = _mtime(self.png)
            if mtime and mtime != self._mtime:
                self._mtime = mtime
                self._reload_image()
        self.root.after(POLL_MS, self._tick)

    def run(self) -> None:
        # Load the QR before the event loop starts. Tk does not map the root
        # until then, so widening the box here costs nothing on screen; waiting
        # for the first tick would show the floor size and then grow in front of
        # the user. If the file is unreadable the loop still retries on mtime.
        self._reload_image()
        self._tick()
        self.root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="LINE login dialog")
    parser.add_argument("--png", required=True, help="QR image to display")
    parser.add_argument("--status", required=True, help="JSON status file to watch")
    parser.add_argument("--zoom", type=int, default=2, help="image zoom, 1-4")
    parser.add_argument("--title", default="LINE", help="window title bar text")
    args = parser.parse_args()
    _Dialog(args.png, args.status, args.zoom, args.title).run()


if __name__ == "__main__":
    main()
