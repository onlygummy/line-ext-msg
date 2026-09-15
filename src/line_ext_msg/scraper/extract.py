"""Turn rendered message rows into Message models (dates, senders, media)."""

from __future__ import annotations

import re
from datetime import datetime

from playwright.sync_api import Page

from ..browser import js
from ..config.selectors import SELECTORS
from ..domain.models import Message
from .media import fetch_image

# System rows glue the clock to the text ("3:43 PMw.siri joined..."):
# the row carries no dedicated sender element, so strip the prefix here.
_SYSTEM_TIME_PREFIX = re.compile(r"^\d{1,2}:\d{2}\s*(?:AM|PM)?\s*", re.IGNORECASE)


def clean_system_text(text: str) -> str:
    """Drop a leading clock from system rows. Pure (unit-testable)."""
    return _SYSTEM_TIME_PREFIX.sub("", text or "").strip()


def _text(root, selector: str, timeout: int = 500) -> str:
    """text_content (no visibility wait): off-screen bubbles never stabilize."""
    try:
        loc = root.locator(selector)
        if loc.count() == 0:
            return ""
        return (loc.first.text_content(timeout=timeout) or "").strip()
    except Exception:
        return ""


def _epoch_to_parts(epoch_ms: str) -> tuple[str, str]:
    """Epoch ms -> (YYYY-MM-DD, ISO). Empty pair when unparsable."""
    try:
        dt = datetime.fromtimestamp(int(epoch_ms) / 1000)
        return dt.strftime("%Y-%m-%d"), dt.isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return "", ""


def _classify(row) -> str:
    """Message kind by which content module is present."""
    try:
        if row.locator(SELECTORS["text"]).count() > 0:
            return "text"
        if row.locator(SELECTORS["sticker"]).count() > 0:
            return "sticker"
        if row.locator(SELECTORS["image"]).count() > 0:
            return "image"
    except Exception:
        pass
    return "unknown"


def _read_count(row) -> int | None:
    raw = "".join(c for c in _text(row, SELECTORS["read_count"]) if c.isdigit())
    return int(raw) if raw else None


def rendered_keys(page: Page) -> list[tuple[str, str]] | None:
    """(select-id, timestamp) of rendered rows in DOM order.

    None means the probe itself failed (caller should extract anyway);
    [] means the probe worked and no rows are rendered. One cheap
    evaluate: lets the caller skip a full extraction round when the
    virtualized window did not change.
    """
    try:
        rows = page.evaluate(
            js.RENDERED_KEYS,
            {"item": f"{SELECTORS['message_item']}, {SELECTORS['system_row']}"},
        )
        if isinstance(rows, list):
            return [(str(a or ""), str(b or "")) for a, b in rows if isinstance(a, str)]
        return None
    except Exception:
        return None


def extract_current(
    page: Page,
    with_media: bool,
    skip_media_ids: set[str],
) -> list[Message]:
    """Full Message models for currently rendered rows, newest-first.

    When with_media is True, image bubbles are fetched in memory as a data
    URI in Message.media_data (no files). Bubbles whose id is in
    skip_media_ids keep empty media fields (already fetched earlier).
    Never raises: skips bad rows.
    """
    # Date separators and system rows interleave with messages in DOM order.
    nodes = page.locator(
        f"{SELECTORS['message_item']}, {SELECTORS['system_row']}, {SELECTORS['date_sep']}"
    )
    out: list[Message] = []
    current_date = ""
    for i in range(nodes.count()):
        node = nodes.nth(i)
        try:
            cls = node.get_attribute("class") or ""
        except Exception:
            continue
        if "messageDate-module" in cls:
            try:
                dt = node.get_attribute("datetime") or ""
                if dt.isdigit():
                    current_date = datetime.fromtimestamp(int(dt) / 1000).strftime("%Y-%m-%d")
            except Exception:
                pass
            continue
        if "systemMessage-module" in cls:
            text = _text(node, SELECTORS["system_text"])
            if not text and _has_text(node):
                text = node.inner_text().strip()[:200]
            text = clean_system_text(text)
            if not text:
                continue
            epoch = _attr(node, "data-timestamp")
            day, ts = _epoch_to_parts(epoch)
            out.append(Message(
                id=_attr(node, "data-message-select-id") or epoch,
                date=day or current_date,
                ts=ts,
                sender="",
                from_me=False,
                type="system",
                text=text,
            ))
            continue
        kind = _classify(node)
        if kind == "unknown":
            continue
        # Non-text kinds (sticker/image) carry no text but still count
        # as activity, so they are kept with empty text.
        text = _text(node, SELECTORS["text"])
        sender = _text(node, SELECTORS["sender"])
        epoch = _attr(node, "data-timestamp")
        day, ts = _epoch_to_parts(epoch)
        if not ts:
            ts = _text(node, SELECTORS["time"])
        # Unverified heuristic (data-direction is empty on every row seen so
        # far): LINE renders own bubbles without a username element. If a
        # future dump shows a reliable marker, replace this check.
        from_me = not sender and kind in ("text", "image", "sticker")
        msg_id = _attr(node, "data-message-select-id") or f"{epoch}-{_attr(node, 'data-mid')}"
        media_data = ""
        if kind == "image" and with_media and msg_id not in skip_media_ids:
            media_data = fetch_image(page, node)
        out.append(Message(
            id=msg_id,
            date=day or current_date,
            ts=ts,
            sender=sender,
            from_me=from_me,
            type=kind,
            text=text,
            read_count=_read_count(node),
            media_data=media_data,
        ))

    return out


def _attr(node, name: str) -> str:
    try:
        return node.get_attribute(name) or ""
    except Exception:
        return ""


def _has_text(node) -> bool:
    try:
        return bool(node.inner_text().strip())
    except Exception:
        return False
