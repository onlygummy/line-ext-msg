"""Room rows: extract + open, returning Room models."""

import logging

from playwright.sync_api import Page

from ..browser import js
from ..config.selectors import SELECTORS
from ..config.settings import Settings
from ..domain.errors import ChatsViewMissing, RoomNotFound
from ..domain.models import Room

logger = logging.getLogger(__name__)


def _no_chats_view() -> ChatsViewMissing:
    """Typed failure for a page that is not showing the chats list."""
    return ChatsViewMissing(
        "the LINE tab is not showing the chats list; run line-ext-msg --dump "
        "to see the current DOM and tune config/selectors.py"
    )


def _text(locator, timeout: int = 500) -> str:
    """text_content (no visibility wait): virtualized rows off-screen never stabilize."""
    try:
        return (locator.first.text_content(timeout=timeout) or "").strip()
    except Exception:
        return ""


def _int(text: str) -> int:
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else 0


def _named_rows(page: Page) -> list:
    """Visible rows that have a name (skips category headers)."""
    rows = []
    items = page.locator(SELECTORS["room_item"])
    try:
        total = items.count()
    except Exception:
        return []
    for i in range(total):
        row = items.nth(i)
        # Read the name once here; list_rooms reuses it instead of reading twice.
        name = _text(row.locator(SELECTORS["room_name"]))
        if name:
            rows.append((row, name))
    return rows


def _scroll_to_load(page: Page, settings: Settings) -> None:
    """Scroll the room list so virtualized rows render before reading.

    Bounded by settings.rooms_scroll_ms (default 8s): stops early when the
    row count is stable three times in a row. Skipped entirely when disabled (0).
    """
    if settings.rooms_scroll_ms <= 0:
        return
    try:
        last = page.locator(SELECTORS["room_item"]).count()
    except Exception:
        return
    stable = 0
    waited = 0
    step = 400
    max_stable = 3
    while waited < settings.rooms_scroll_ms and stable < max_stable:
        try:
            page.evaluate(js.ROOM_SCROLL, {"listSel": SELECTORS["room_list"]})
        except Exception:
            return
        try:
            page.wait_for_timeout(step)
        except Exception:
            return
        try:
            now = page.locator(SELECTORS["room_item"]).count()
        except Exception:
            return
        if now == last:
            stable += 1
        else:
            stable = 0
        last = now
        waited += step


def _batch_rooms(page: Page) -> list[dict]:
    """Read all room rows in one JS call (one CDP roundtrip).

    Returns [] when evaluate fails so the caller can fall back to locators.
    """
    try:
        return page.evaluate(
            js.ROOMS_BATCH,
            {k: SELECTORS[k] for k in ("room_item", "room_name", "room_unread", "room_preview", "room_time")},
        ) or []
    except Exception:
        return []


def list_rooms(page: Page, settings: Settings) -> list[Room]:
    """Extract rooms as Room models.

    Raises ChatsViewMissing when the chats list never renders, because an
    empty list reads as "this account has no rooms" and hides a wrong view.
    """
    try:
        page.wait_for_selector(SELECTORS["room_item"], timeout=settings.selector_ms)
    except Exception:
        raise _no_chats_view() from None
    _scroll_to_load(page, settings)
    batch = _batch_rooms(page)
    if batch:
        rooms: list[Room] = []
        skipped = []
        for row in batch:
            try:
                name = (row.get("name") or "").strip()
            except Exception:
                continue
            if not name:
                skipped.append(row)
                continue
            rooms.append(Room(
                index=len(rooms),
                id=row.get("mid") or "",
                name=name,
                unread=_int(row.get("unread") or ""),
                last_preview=(row.get("preview") or "").strip(),
                last_time=(row.get("time") or "").strip(),
            ))
        if settings.debug_rooms and skipped:
            # Log the row ids only: a row carries the message preview, which
            # is chat content and does not belong in a log file.
            logger.debug("skipped %d room rows without a name: %s", len(skipped),
                         [row.get("mid", "") for row in skipped[:5]])
        if rooms:
            return rooms
    rooms = []
    for row, name in _named_rows(page):
        try:
            mid = row.get_attribute("data-mid") or ""
        except Exception:
            mid = ""
        rooms.append(Room(
            index=len(rooms),
            id=mid,
            name=name,
            unread=_int(_text(row.locator(SELECTORS["room_unread"]))),
            last_preview=_text(row.locator(SELECTORS["room_preview"])),
            last_time=_text(row.locator(SELECTORS["room_time"])),
        ))
    if not rooms:
        # Rows were attached a moment ago but none carried a name, so this is
        # a layout change rather than an empty account.
        raise _no_chats_view()
    return rooms


def resolve_ref(ref: int | str | Room, rooms: list[Room]) -> Room:
    """Resolve int index, data-mid, Room, or name substring to a Room.

    Search order: exact data-mid, case-insensitive substring, contains all words.
    """
    if isinstance(ref, Room):
        return ref
    if isinstance(ref, int):
        for room in rooms:
            if room.index == ref:
                return room
    else:
        # Exact data-mid match
        for room in rooms:
            if room.id and room.id == ref:
                return room
        # The guard also protects the word pass below: all() over an empty
        # word list is True, so a blank ref would otherwise match rooms[0].
        needle = ref.strip().lower()
        if needle:
            # Case-insensitive substring match
            for room in rooms:
                if needle in room.name.lower():
                    return room
            # Contains all words (for multi-word room names)
            for room in rooms:
                room_name_lower = room.name.lower()
                if all(word in room_name_lower for word in needle.split()):
                    return room
    raise RoomNotFound(ref, [r.name for r in rooms])


def _row_by_mid(rows: list, mid: str):
    """Row whose data-mid matches, or None when mid is empty or absent."""
    if not mid:
        return None
    for row, _name in rows:
        try:
            if (row.get_attribute("data-mid") or "") == mid:
                return row
        except Exception:
            continue
    return None


def _find_row(page: Page, room: Room, settings: Settings):
    """DOM row for a room, or None when it is not rendered right now.

    data-mid is the only safe key, because it names the same conversation on
    every render. The list position does not: a virtualized list scrolls and
    re-renders, so the same index holds a different room once anything moves.
    The positional fallback therefore applies only to a room that carries no
    id at all, where there is nothing better to go on.
    """
    rows = _named_rows(page)
    if room.id:
        row = _row_by_mid(rows, room.id)
        if row is not None:
            return row
        # The room is known but the list has it off-screen. One bounded scroll
        # brings the list back before looking a second time; it stops as soon
        # as the row count settles, so this costs nothing in the common case.
        _scroll_to_load(page, settings)
        return _row_by_mid(_named_rows(page), room.id)
    logger.debug("room %r has no data-mid, falling back to its list position", room.name)
    return rows[room.index][0] if room.index < len(rows) else None


def open_room(page: Page, ref: int | str | Room, rooms: list[Room], settings: Settings) -> Room:
    """Click a room's Go-chatroom button, wait until chat content shows."""
    room = resolve_ref(ref, rooms)
    row = _find_row(page, room, settings)
    if row is None:
        raise RoomNotFound(ref, [r.name for r in rooms])
    try:
        row.locator(SELECTORS["room_open"]).click(timeout=settings.selector_ms)
    except Exception as e:
        # A row without the Go-chatroom button cannot be opened, which happens
        # for the rows LINE renders outside the chat list. Report the rooms
        # that can be opened instead of surfacing a click timeout.
        logger.debug("cannot open room %r: %s", room.name, e)
        raise RoomNotFound(ref, [r.name for r in rooms]) from None
    # Fixed sleep is not enough on slow renders: wait for the chat pane.
    try:
        page.wait_for_selector(SELECTORS["message_list"], timeout=settings.selector_ms)
    except Exception:
        page.wait_for_timeout(settings.open_room_wait_ms)
    return room
