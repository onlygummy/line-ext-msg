"""Settings: all runtime knobs, overridable via LINE_EXT_MSG_* env vars."""

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# The QR canvas is small, so 2x is readable without the blockiness of a larger
# nearest-neighbor zoom. Tk's PhotoImage.zoom refuses anything outside this
# range, and the viewer process runs with its stderr discarded, so an
# out-of-range value would surface as a blank dialog with no error anywhere.
QR_ZOOM_MIN, QR_ZOOM_MAX = 1, 4


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    """All knobs; override via constructor or LINE_EXT_MSG_* env vars."""

    port: int = field(default_factory=lambda: _env_int("LINE_EXT_MSG_PORT", 9222))
    profile_dir: str = field(
        default_factory=lambda: _env("LINE_EXT_MSG_PROFILE", r"%LOCALAPPDATA%\line-chrome-debug")
    )
    extension_id: str = field(
        default_factory=lambda: _env("LINE_EXT_MSG_EXTENSION", "ophjlpahpchlmihnnnihgmmeilfjmjjc")
    )
    app_ready_ms: int = field(default_factory=lambda: _env_int("LINE_EXT_MSG_READY_MS", 30000))
    selector_ms: int = field(default_factory=lambda: _env_int("LINE_EXT_MSG_SELECTOR_MS", 15000))
    login_poll_ms: int = field(default_factory=lambda: _env_int("LINE_EXT_MSG_LOGIN_MS", 10000))
    login_wait_ms: int = field(default_factory=lambda: _env_int("LINE_EXT_MSG_LOGIN_WAIT_MS", 300000))
    rooms_scroll_ms: int = field(default_factory=lambda: _env_int("LINE_EXT_MSG_ROOMS_SCROLL_MS", 8000))
    # How long to wait for the chat list to render when switching to the chats
    # view after login. Separate from selector_ms because the login screen
    # cannot render a chat list, so the wait only happens once logged in.
    chats_ensure_ms: int = field(
        default_factory=lambda: _env_int("LINE_EXT_MSG_CHATS_ENSURE_MS", 10000)
    )
    messages_scroll_ms: int = field(default_factory=lambda: _env_int("LINE_EXT_MSG_MSGS_SCROLL_MS", 8000))
    # A filtered query cannot know how many rows it needs, so it gets its own
    # budget floor and only stops at the older edge, a date, or this timeout.
    # Without it a keyword made the scan shallower than the same call without
    # one, and a partial scan looked exactly like "no match".
    search_scroll_ms: int = field(
        default_factory=lambda: _env_int("LINE_EXT_MSG_SEARCH_SCROLL_MS", 60000)
    )
    # Hard ceiling on the budget derived from `limit`, whichever path asks for
    # it. Without a knob, a room with a long archive stays pinned to five
    # minutes and reports truncated: true forever. Set it to 0 or less to let
    # `limit` decide on its own with no ceiling at all.
    scroll_cap_ms: int = field(
        default_factory=lambda: _env_int("LINE_EXT_MSG_SCROLL_CAP_MS", 300000)
    )
    open_room_wait_ms: int = field(default_factory=lambda: _env_int("LINE_EXT_MSG_OPEN_MS", 3000))
    # How long a graceful CDP close may take before the force kill fallback.
    stop_graceful_ms: int = field(
        default_factory=lambda: _env_int("LINE_EXT_MSG_STOP_GRACEFUL_MS", 3000)
    )
    # Extra settle after the app looks ready, to let React finish painting.
    ready_settle_ms: int = field(
        default_factory=lambda: _env_int("LINE_EXT_MSG_READY_SETTLE_MS", 200)
    )
    # QR dialog zoom. Clamped to QR_ZOOM_MIN..QR_ZOOM_MAX in __post_init__.
    qr_zoom: int = field(default_factory=lambda: _env_int("LINE_EXT_MSG_QR_ZOOM", 2))
    # Title of the QR dialog window. It shows in the title bar only; the card
    # itself carries the status pill and no app name.
    dialog_title: str = field(
        default_factory=lambda: _env("LINE_EXT_MSG_DIALOG_TITLE", "LINE")
    )
    qr_ready_ms: int = field(default_factory=lambda: _env_int("LINE_EXT_MSG_QR_READY_MS", 20000))
    debug_qr: bool = field(
        default_factory=lambda: _env("LINE_EXT_MSG_DEBUG_QR", "").lower() in ("1", "true", "yes")
    )
    headless: bool = field(
        default_factory=lambda: _env("LINE_EXT_MSG_HEADLESS", "1").lower() in ("1", "true", "yes")
    )
    quiet: bool = field(
        default_factory=lambda: _env("LINE_EXT_MSG_QUIET", "").lower() in ("1", "true", "yes")
    )
    debug_scroll: bool = field(
        default_factory=lambda: _env("LINE_EXT_MSG_DEBUG_SCROLL", "").lower() in ("1", "true", "yes")
    )
    debug_rooms: bool = field(
        default_factory=lambda: _env("LINE_EXT_MSG_DEBUG_ROOMS", "").lower() in ("1", "true", "yes")
    )

    def __post_init__(self) -> None:
        # Frozen dataclass, so the clamp has to go through object.__setattr__.
        # Clamping rather than falling back to the default keeps the intent of
        # a caller who asked for the largest readable zoom.
        if not QR_ZOOM_MIN <= self.qr_zoom <= QR_ZOOM_MAX:
            clamped = max(QR_ZOOM_MIN, min(QR_ZOOM_MAX, self.qr_zoom))
            logger.warning("qr_zoom %s is outside %d-%d; using %s",
                           self.qr_zoom, QR_ZOOM_MIN, QR_ZOOM_MAX, clamped)
            object.__setattr__(self, "qr_zoom", clamped)

    @property
    def cdp_endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def extension_url(self) -> str:
        return f"chrome-extension://{self.extension_id}/index.html#/"

    @property
    def chats_url(self) -> str:
        return f"chrome-extension://{self.extension_id}/index.html#/chats"

    @property
    def webstore_url(self) -> str:
        return f"https://chromewebstore.google.com/detail/line/{self.extension_id}"
