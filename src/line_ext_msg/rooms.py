"""Room rows: extract + open, returning Room models."""

from playwright.sync_api import Page

from .models import Room
from .settings import SELECTORS, Settings


def _text(locator) -> str:
    """text_content (no visibility wait): virtualized rows off-screen never stabilize."""
    try:
        return (locator.first.text_content(timeout=3000) or "").strip()
    except Exception:
        return ""


def _int(text: str) -> int:
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else 0


def _named_rows(page: Page) -> list:
    """Visible rows that have a name (skips category headers)."""
    rows = []
    items = page.locator(SELECTORS["room_item"])
    for i in range(items.count()):
        row = items.nth(i)
        if _text(row.locator(SELECTORS["room_name"])):
            rows.append(row)
    return rows


def list_rooms(page: Page, settings: Settings) -> list[Room]:
    """Extract rooms as Room models. Empty list means not rendered yet."""
    try:
        page.wait_for_selector(SELECTORS["room_item"], timeout=settings.selector_ms)
    except Exception:
        return []
    rooms = []
    for row in _named_rows(page):
        try:
            mid = row.get_attribute("data-mid") or ""
        except Exception:
            mid = ""
        rooms.append(Room(
            index=len(rooms),
            id=mid,
            name=_text(row.locator(SELECTORS["room_name"])),
            unread=_int(_text(row.locator(SELECTORS["room_unread"]))),
            last_preview=_text(row.locator(SELECTORS["room_preview"])),
            last_time=_text(row.locator(SELECTORS["room_time"])),
        ))
    return rooms


def resolve_ref(ref: int | str | Room, rooms: list[Room]) -> Room:
    """Resolve int index, data-mid, Room, or name substring to a Room."""
    from .errors import RoomNotFound
    if isinstance(ref, Room):
        return ref
    if isinstance(ref, int):
        for room in rooms:
            if room.index == ref:
                return room
    else:
        for room in rooms:
            if room.id and room.id == ref:
                return room
        for room in rooms:
            if ref in room.name:
                return room
    raise RoomNotFound(ref, [r.name for r in rooms])


def open_room(page: Page, ref: int | str | Room, rooms: list[Room], settings: Settings) -> Room:
    """Click a room's Go-chatroom button, wait until chat content shows."""
    room = resolve_ref(ref, rooms)
    rows = _named_rows(page)
    if room.index >= len(rows):
        from .errors import RoomNotFound
        raise RoomNotFound(ref, [r.name for r in rooms])
    rows[room.index].locator(SELECTORS["room_open"]).click()
    # Fixed sleep is not enough on slow renders: wait for the chat pane.
    try:
        page.wait_for_selector(SELECTORS["message_list"], timeout=settings.selector_ms)
    except Exception:
        page.wait_for_timeout(settings.open_room_wait_ms)
    return room
