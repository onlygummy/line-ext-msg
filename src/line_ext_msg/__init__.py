"""line-ext-msg: pull messages from LINE Chrome Extension via Playwright CDP.

Layers and their one-way dependency rule (no cycles):

    config   -> (nothing)   Settings, SELECTORS, default paths
    domain   -> (nothing)   models, typed errors, pure filters
    browser  -> config      Chrome lifecycle, CDP session, login, JS snippets
    scraper  -> config, domain, browser    page DOM -> domain models
    output   -> config, domain             JSON storage, checklist printer
    service  -> all of the above           LineClient facade, readiness, diagnostics
    cli      -> service, config            command-line entry point

Only this module exposes the public API; subpackages are implementation
details and may change without notice.
"""

__version__ = "1.2.0"

from .config.settings import Settings
from .domain.errors import (
    AppNotReady,
    AttachFailed,
    ChromeNotReady,
    ExtensionMissing,
    LineError,
    LoginRequired,
    QrDialogFailed,
    RoomNotFound,
)
from .domain.filters import sender_stats
from .domain.models import Message, Room, StepResult
from .service.client import LineClient

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
    "QrDialogFailed",
    "RoomNotFound",
]
