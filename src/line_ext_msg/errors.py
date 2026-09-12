"""Typed errors so callers (CLI, MCP) branch on kind, not message text."""


class LineError(Exception):
    """Base for all line-ext-msg failures."""


class ChromeNotReady(LineError):
    """Debug Chrome could not be started or reached."""


class AttachFailed(LineError):
    """CDP attach to the running Chrome failed."""


class ExtensionMissing(LineError):
    """LINE Extension is not installed in the debug profile."""


class AppNotReady(LineError):
    """LINE SPA did not finish rendering in time."""


class LoginRequired(LineError):
    """Login screen is showing; user must log in first."""


class RoomNotFound(LineError):
    """No visible room matches the given reference."""

    def __init__(self, ref: object, available: list[str]):
        self.ref = ref
        self.available = available
        super().__init__(f"ไม่เจอห้อง '{ref}' (มี: {', '.join(available) or '—'})")
