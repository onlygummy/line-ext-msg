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


@dataclass(frozen=True)
class ScanProgress:
    """One tick from a multi-room scan (unread_full, search_all).

    Those scans walk rooms one at a time and each one can spend up to the
    scroll budget, so a host that wants to show progress needs a tick per
    room. truncated rides along on every tick so "this room may be missing
    older matches" can be surfaced while the scan is still running, not only
    when the report comes back.
    """

    room: Room  # the room this tick is about
    index: int  # 1-based position in the scan
    total: int  # how many rooms the scan covers
    matched: int  # messages kept for this room
    truncated: bool  # backfill hit its budget, so older matches may be missing
