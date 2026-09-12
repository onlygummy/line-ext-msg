"""Domain models: plain frozen dataclasses, JSON-ready via asdict()."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Room:
    """One chat room row from the chats/friends list."""

    index: int
    id: str  # data-mid, stable across runs
    name: str
    unread: int = 0
    last_preview: str = ""
    last_time: str = ""


@dataclass(frozen=True)
class Message:
    """One message bubble. ts is full ISO timestamp from data-timestamp."""

    id: str
    date: str  # YYYY-MM-DD in local time
    ts: str  # ISO 8601
    sender: str
    from_me: bool  # heuristic: no username shown means own message
    type: str  # text | sticker | image | system | file
    text: str
    read_count: int | None = None
    media: str = ""  # local file path when downloaded (image type)
    media_data: str = ""  # data URI (opt-in via include_media_data, for MCP/AI)


@dataclass(frozen=True)
class StepResult:
    """One startup checklist row, for CLI display and MCP line_status."""

    name: str
    passed: bool
    detail: str = ""
