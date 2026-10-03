"""get_messages: orchestrate scroll + extraction into a Messages result."""

from __future__ import annotations

from playwright.sync_api import Page

from ..config.selectors import SELECTORS
from ..config.settings import Settings
from ..domain.filters import apply_filters
from ..domain.models import Message
from ..results import Messages
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
    with_media: bool = False,
    scroll: bool = True,
) -> Messages:
    """Latest messages, newest-first, as a Messages result.

    Tracks day separators while walking the DOM so each message gets a
    real date. The chat list is virtualized in both directions, so rows
    are accumulated into a SeenMap every scroll round (bounded by
    settings.messages_scroll_ms, or settings.search_scroll_ms when a filter is
    set); rows unloaded mid-scroll stay in the result. with_media fetches
    image bubbles in memory (data URI); call Messages.download_media to write
    files. Never raises on missing selectors: returns an empty Messages
    instead. Messages.scroll_stop says why the backfill stopped, and
    'budget' means the messages are a partial scan.
    """
    try:
        page.wait_for_selector(SELECTORS["message_list"], timeout=settings.selector_ms)
    except Exception:
        return Messages()

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
                rows = extract_current(page, with_media, set(seen))
            except Exception:
                return len(seen)
            for m in rows:
                seen.setdefault(m.id, m)
        return len(seen)

    capture()
    stop = ""
    if scroll:
        # Without a filter any `limit` rows are enough, so `need` can end the
        # scan early. With a filter the surviving count is unknown, so there is
        # no `need` at all and the budget is what bounds the run: without a
        # dedicated one, passing need=0 silently fell back to the base budget
        # and made a filtered search shallower than the same call unfiltered.
        filtered = any(v is not None for v in (
            date, date_from, date_to, time_from, time_to, sender, keyword,
        ))
        budget = None
        need = limit or 0
        if filtered:
            need = 0
            # Same limit scaling the unfiltered path gets, with the search
            # floor on top so a small limit still reaches deep enough.
            budget = max(settings.search_scroll_ms, min(limit * 1000, 300000) if limit else 0)
        stop = _scroll.scroll_to_fill(page, settings, need,
                                      date_from=date or date_from, on_round=capture,
                                      budget_ms=budget)

    out = apply_filters(list(seen.values()), date=date, date_from=date_from,
                        date_to=date_to, time_from=time_from, time_to=time_to,
                        sender=sender, keyword=keyword)
    # DOM order is newest-first (verified in room dumps), so the latest
    # messages are at the head, not the tail.
    result = Messages(out[:limit] if limit else out)
    # The caller needs this to tell a complete scan from a partial one.
    result.scroll_stop = stop
    return result


__all__ = ["get_messages"]
