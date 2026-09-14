"""line-ext-msg: pull messages from LINE Chrome Extension via Playwright CDP."""

__version__ = "1.2.0"

from .client import LineClient
from .messages import sender_stats
from .errors import (
    AppNotReady,
    AttachFailed,
    ChromeNotReady,
    ExtensionMissing,
    LineError,
    LoginRequired,
    RoomNotFound,
)
from .models import Message, Room, StepResult
from .settings import Settings

__all__ = [
    "__version__",
    "LineClient",
    "sender_stats",
    "Room",
    "Message",
    "StepResult",
    "Settings",
    "LineError",
    "ChromeNotReady",
    "AttachFailed",
    "ExtensionMissing",
    "AppNotReady",
    "LoginRequired",
    "RoomNotFound",
]
