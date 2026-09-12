"""Settings + tuned selectors (single place to adjust for LINE UI updates)."""

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
    open_room_wait_ms: int = field(default_factory=lambda: _env_int("LINE_EXT_MSG_OPEN_MS", 3000))
    quiet: bool = field(
        default_factory=lambda: _env("LINE_EXT_MSG_QUIET", "").lower() in ("1", "true", "yes")
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


# Tuned from real DOM of extension v3.7.2. CSS-module hashes change per
# build, so match the stable module prefix with *= and never the hash.
SELECTORS = {
    # Left nav button that routes to the chats view.
    "nav_chat": "button[aria-label='Chat']",
    # Room rows (chats view first, friends as fallback).
    "room_list": "[class*='chatlist-module__chatlist'], [class*='friendlist-module__list']",
    "room_item": "[class*='chatlistItem-module__chatlist_item'], [class*='friendlistItem-module__item']",
    "room_name": "[class*='chatlistItem-module__text'], [class*='friendlistItem-module__text']",
    "room_open": "button[aria-label='Go chatroom']",
    "room_unread": "[class*='chatlistItem-module__message_count'], [class*='friendlistItem-module__badge']",
    "room_preview": "[class*='chatlistItem-module__description'], [class*='friendlistItem-module__description']",
    "room_time": "[class*='chatlistItem-module__date']",
    # Message list: stable hash-free container (role=log).
    "message_list": "div.message_list",
    "message_item": "[class*='message-module__message']",
    "sender": "[class*='username-module__username']",
    "text": "[class*='textMessageContent-module__text']",
    "time": "[class*='metaInfo-module__send_time']",
    "read_count": "[class*='metaInfo-module__read_count']",
    "sticker": "[class*='stickerMessageContent-module__']",
    "image": "[class*='imageMessageContent-module__']",
    "system_row": "[class*='systemMessage-module__message']",
    "system_text": "[class*='systemMessage-module__text']",
    "date_sep": "[class*='messageDate-module__date']",
}
