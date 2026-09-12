"""Room rows: extract + open, returning Room models."""

from playwright.sync_api import Page

from .models import Room
from .settings import SELECTORS, Settings


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

    Bounded by settings.rooms_scroll_ms (default 4s): stops early when the
    row count is stable twice in a row. Skipped entirely when disabled (0).
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
    while waited < settings.rooms_scroll_ms and stable < 2:
        try:
            page.evaluate(
                """(listSel) => {
                    const lists = [];
                    for (const part of listSel.split(',')) {
                        document.querySelectorAll(part.trim()).forEach(el => lists.push(el));
                    }
                    const list = lists[0];
                    if (!list) return false;
                    let sc = list;
                    while (sc && sc !== document.body) {
                        const st = getComputedStyle(sc);
                        if (st.overflowY === 'auto' || st.overflowY === 'scroll') break;
                        sc = sc.parentElement;
                    }
                    (sc || list).scrollTop = (sc || list).scrollHeight;
                    return true;
                }""",
                SELECTORS["room_list"],
            )
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
        stable = stable + 1 if now == last else 0
        last = now
        waited += step


def _batch_rooms(page: Page) -> list[dict]:
    """Read all room rows in one JS call (one CDP roundtrip).

    Returns [] when evaluate fails so the caller can fall back to locators.
    """
    try:
        return page.evaluate(
            """(sels) => {
                const pick = (root, sel) => {
                    for (const part of sel.split(',')) {
                        const el = root.querySelector(part.trim());
                        if (el) return (el.textContent || '').trim();
                    }
                    return '';
                };
                const rows = [];
                for (const part of sels.room_item.split(',')) {
                    document.querySelectorAll(part.trim()).forEach(el => rows.push(el));
                }
                return rows.map(el => ({
                    mid: el.getAttribute('data-mid') || '',
                    name: pick(el, sels.room_name),
                    unread: pick(el, sels.room_unread),
                    preview: pick(el, sels.room_preview),
                    time: pick(el, sels.room_time),
                }));
            }""",
            {k: SELECTORS[k] for k in ("room_item", "room_name", "room_unread", "room_preview", "room_time")},
        ) or []
    except Exception:
        return []


def list_rooms(page: Page, settings: Settings) -> list[Room]:
    """Extract rooms as Room models. Empty list means not rendered yet."""
    try:
        page.wait_for_selector(SELECTORS["room_item"], timeout=settings.selector_ms)
    except Exception:
        return []
    _scroll_to_load(page, settings)
    batch = _batch_rooms(page)
    if batch:
        rooms = []
        for row in batch:
            try:
                name = (row.get("name") or "").strip()
            except Exception:
                continue
            if not name:
                continue
            rooms.append(Room(
                index=len(rooms),
                id=row.get("mid") or "",
                name=name,
                unread=_int(row.get("unread") or ""),
                last_preview=(row.get("preview") or "").strip(),
                last_time=(row.get("time") or "").strip(),
            ))
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
    rows = [row for row, _name in _named_rows(page)]
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
