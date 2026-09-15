"""get_messages: orchestrate scroll + extraction into a filtered list."""

from __future__ import annotations

from playwright.sync_api import Page

from ..config.selectors import SELECTORS
from ..config.settings import Settings
from ..domain.filters import apply_filters
from ..domain.models import Message
from . import scroll as _scroll
from .extract import extract_current, rendered_keys


def get_messages(
    page: Page,
    settings: Settings,
    limit: int = 5,
    date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    time_from: str | None = None,
    time_to: str | None = None,
    sender: str | None = None,
    keyword: str | None = None,
    media_dir: str | None = None,
    include_media_data: bool = False,
    scroll: bool = True,
) -> list[Message]:
    """Latest messages, newest-first, with dates and ids.

    Tracks day separators while walking the DOM so each message gets a
    real date. The chat list is virtualized in both directions, so rows
    are accumulated into a SeenMap every scroll round (bounded by
    settings.messages_scroll_ms); rows unloaded mid-scroll stay in the
    result. Never raises on missing selectors: returns [] instead.
    """
    try:
        page.wait_for_selector(SELECTORS["message_list"], timeout=settings.selector_ms)
    except Exception:
        return []

    seen: dict[str, Message] = {}
    last_sig: list[tuple[str, str]] | None = None

    def capture() -> int:
        """Merge currently rendered rows; return accumulated unique count."""
        nonlocal last_sig
        try:
            sig = rendered_keys(page)
        except Exception:
            sig = None
        if sig is None or sig != last_sig:
            last_sig = sig
            try:
                rows = extract_current(page, media_dir, include_media_data, set(seen))
            except Exception:
                return len(seen)
            for m in rows:
                seen.setdefault(m.id, m)
        return len(seen)

    capture()
    if scroll:
        # Without filters any `limit` rows are enough; with filters the
        # surviving count is unknown, so fill the whole scroll budget (0).
        filtered = any(v is not None for v in (
            date, date_from, date_to, time_from, time_to, sender, keyword,
        ))
        _scroll.scroll_to_fill(page, settings, 0 if filtered else (limit or 0),
                               date_from=date or date_from, on_round=capture)

    out = apply_filters(list(seen.values()), date=date, date_from=date_from,
                        date_to=date_to, time_from=time_from, time_to=time_to,
                        sender=sender, keyword=keyword)
    # DOM order is newest-first (verified in room dumps), so the latest
    # messages are at the head, not the tail.
    return out[:limit] if limit else out


__all__ = ["get_messages"]
