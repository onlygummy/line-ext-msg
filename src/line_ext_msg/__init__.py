"""line-ext-msg: pull messages from LINE Chrome Extension via Playwright CDP.

Layers and the imports each one is allowed to make (no cycles):

    config   -> nothing                     Settings, SELECTORS, default paths
    domain   -> nothing                     models, typed errors, callback contracts,
                                              pure filters
    output   -> config, domain              JSON storage, checklist printer
    results  -> domain, output              savable query results
    browser  -> config, domain              Chrome lifecycle, CDP, login, JS
    scraper  -> config, domain, browser, results    page DOM -> domain models
    service  -> every layer above           LineClient facade, readiness, diagnostics
    cli      -> service, config, domain, output      command-line entry point

`domain` is the shared vocabulary (models plus typed errors), so any layer
may import it. `results` is the savable result layer used by both `scraper`
and `service`, which is why `scraper` reaches `output` through it.

Only this module exposes the public API; subpackages are implementation
details and may change without notice.
"""

import logging as _logging

from .config.settings import Settings
from .domain.callbacks import PinCallback, ProgressCallback, QrCallback, StatusCallback
from .domain.errors import (
    AppNotReady,
    AttachFailed,
    ChatsViewMissing,
    ChromeNotReady,
    ExtensionMissing,
    LineError,
    LoginRequired,
    LoginTimeout,
    QrDialogFailed,
    RoomNotFound,
)
from .domain.filters import sender_stats
from .domain.models import Message, Room, ScanProgress, StepResult
from .results import Dom, Messages, Probe, Report, Rooms
from .service.client import LineClient

__version__ = "3.1.0"

# Library best practice: never emit or configure logging on import. Callers
# (the CLI, or an embedding app) attach handlers via output.logging.configure.
_logging.getLogger(__name__).addHandler(_logging.NullHandler())

__all__ = [
    "__version__",
    "LineClient",
    "sender_stats",
    "Room",
    "Message",
    "StepResult",
    "ScanProgress",
    "Rooms",
    "Messages",
    "Report",
    "Probe",
    "Dom",
    "Settings",
    "QrCallback",
    "PinCallback",
    "StatusCallback",
    "ProgressCallback",
    "LineError",
    "ChromeNotReady",
    "AttachFailed",
    "ExtensionMissing",
    "AppNotReady",
    "LoginRequired",
    "LoginTimeout",
    "QrDialogFailed",
    "RoomNotFound",
    "ChatsViewMissing",
]
