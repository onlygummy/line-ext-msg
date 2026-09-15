"""Shared QR status file: the JSON payload the dialog and viewer exchange.

The controller (``service.qr``) and the viewer process (``service.qr_view``)
talk through this one file. Writing it in a single place keeps both sides on
the same shape instead of duplicating the temp-file plus replace dance.
"""

from __future__ import annotations

import json
import os


def write_status(path: str, state: str, **extra) -> None:
    """Write ``{"state": ...}`` plus extras via temp file and replace.

    Atomic so the viewer never reads a half-written file. A failed write is
    swallowed: the dialog is best-effort UI and must not break the login.
    """
    payload = {"state": state}
    payload.update(extra)
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp, path)
    except OSError:
        pass
