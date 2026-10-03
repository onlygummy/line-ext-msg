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


class QrDialogFailed(LineError):
    """The QR dialog process could not be started; headless login cannot continue."""


class RoomNotFound(LineError):
    """No visible room matches the given reference."""

    def __init__(self, ref: object, available: list[str]):
        self.ref = ref
        self.available = available
        super().__init__(f"Room '{ref}' not found (available: {', '.join(available) or '-'})")


class ChatsViewMissing(LineError):
    """The LINE tab is not rendering the chats list, so rooms cannot be read.

    Raised instead of returning an empty room list, because an empty result is
    indistinguishable from "this account has no rooms".
    """
