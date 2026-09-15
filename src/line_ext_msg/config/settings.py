"""Settings: all runtime knobs, overridable via LINE_EXT_MSG_* env vars."""

import os
from dataclasses import dataclass, field


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
    rooms_scroll_ms: int = field(default_factory=lambda: _env_int("LINE_EXT_MSG_ROOMS_SCROLL_MS", 4000))
    messages_scroll_ms: int = field(default_factory=lambda: _env_int("LINE_EXT_MSG_MSGS_SCROLL_MS", 8000))
    open_room_wait_ms: int = field(default_factory=lambda: _env_int("LINE_EXT_MSG_OPEN_MS", 3000))
    # QR dialog zoom. The QR canvas is small, so 2x is readable without the
    # blockiness of a larger nearest-neighbor zoom.
    qr_zoom: int = field(default_factory=lambda: _env_int("LINE_EXT_MSG_QR_ZOOM", 2))
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
