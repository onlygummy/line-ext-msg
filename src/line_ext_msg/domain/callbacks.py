"""Callback contracts an embedding app passes to LineClient.

The Tk QR dialog is the only login UI the library ships, which forces a host
that renders the QR itself (an MCP server, a web backend, a bot) to either pop
a window on the server machine or drive the browser by hand. These callbacks
are the seam: the same values the dialog would have shown go to the host
instead.

Every callback here belongs to someone else's UI, so the library treats it as
untrusted. An exception raised in one is logged and ignored, because a
rendering bug in the host must not strand a login halfway through.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from .models import ScanProgress

logger = logging.getLogger(__name__)

# Called with the QR as a PNG data URI. Return False to cancel the login wait.
QrCallback = Callable[[str], "bool | None"]

# Called with the verification PIN and its instruction text, as shown after the
# QR is scanned. Return False to cancel the login wait.
PinCallback = Callable[[str, str], "bool | None"]

# Called with a login phase that carries no new payload: "verifying" once the
# code is submitted and LINE is switching views, then one of "done", "failed" or
# "cancelled" when the wait ends. A host keeps showing its last on_qr or on_pin
# value until one of these arrives, which is why there is no resume event.
StatusCallback = Callable[[str], None]

# Called once per room with what that room produced. Return value ignored.
ProgressCallback = Callable[[ScanProgress], None]


def call_callback(fn: Callable | None, *args, what: str) -> bool:
    """Invoke a host callback defensively. False only when it returns False.

    Returns False when the callback explicitly asked to cancel, so a login
    callback can end its own wait. A None callback counts as "continue", which
    keeps callers free of None checks around every call site.
    """
    if fn is None:
        return True
    try:
        return fn(*args) is not False
    except Exception as exc:
        # Deliberately broad: this is a trust boundary, not a type check.
        logger.warning("%s callback raised (%s); continuing", what, exc)
        return True


__all__ = [
    "PinCallback",
    "ProgressCallback",
    "QrCallback",
    "ScanProgress",
    "StatusCallback",
    "call_callback",
]