"""Message extraction returning Message models with real dates."""

from datetime import datetime

from playwright.sync_api import Page

from .models import Message
from .settings import SELECTORS, Settings


def _text(root, selector: str) -> str:
    """text_content (no visibility wait): off-screen bubbles never stabilize."""
    try:
        loc = root.locator(selector)
        if loc.count() == 0:
            return ""
        return (loc.first.text_content(timeout=3000) or "").strip()
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


_MIME_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}


def to_data_uri(mime: str, b64: str) -> str:
    """Build data URI from mime + base64. Pure (unit-testable)."""
    if not mime or not b64:
        return ""
    return f"data:{mime};base64,{b64}"


def _fetch_blob(page, src: str) -> tuple[str, str]:
    """Fetch blob: URL inside the page. Returns (mime, base64), '' on failure."""
    try:
        payload = page.evaluate(
            """async (url) => {
                const r = await fetch(url);
                const b = await r.blob();
                const buf = await b.arrayBuffer();
                let bin = '';
                const bytes = new Uint8Array(buf);
                for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
                return {data: btoa(bin), mime: b.type};
            }""",
            src,
        )
        if not isinstance(payload, dict):
            return "", ""
        return payload.get("mime", "") or "", payload.get("data", "") or ""
    except Exception:
        return "", ""


def _download_image(
    page,
    row,
    media_dir: str | None,
    include_data: bool,
    msg_id: str,
) -> tuple[str, str]:
    """Fetch image bubble. Returns (local path, data URI); '' when skipped/failed."""
    import base64
    import os

    if not media_dir and not include_data:
        return "", ""
    try:
        img = row.locator(SELECTORS["image"]).locator("img").first
        src = img.get_attribute("src") or ""
        if not src.startswith("blob:"):
            return "", ""
        mime, data = _fetch_blob(page, src)
        if not data:
            return "", ""
        path = ""
        if media_dir:
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in msg_id)[:60]
            os.makedirs(media_dir, exist_ok=True)
            path = os.path.join(media_dir, f"{safe}.{_MIME_EXT.get(mime, 'bin')}")
            with open(path, "wb") as f:
                f.write(base64.b64decode(data))
        return path, to_data_uri(mime, data) if include_data else ""
    except Exception:
        return "", ""


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
) -> list[Message]:
    """Latest messages in chronological order, with dates and ids.

    Tracks day separators while walking the DOM so each message gets a
    real date. Only rendered rows are visible (virtualized list).
    Never raises on missing selectors: returns [] instead.
    """
    try:
        page.wait_for_selector(SELECTORS["message_list"], timeout=settings.selector_ms)
    except Exception:
        return []

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
        media, media_data = "", ""
        if kind == "image" and (media_dir or include_media_data):
            media, media_data = _download_image(page, node, media_dir, include_media_data, msg_id)
        out.append(Message(
            id=msg_id,
            date=day or current_date,
            ts=ts,
            sender=sender,
            from_me=from_me,
            type=kind,
            text=text,
            read_count=_read_count(node),
            media=media,
            media_data=media_data,
        ))

    out = apply_filters(out, date=date, date_from=date_from, date_to=date_to,
                        time_from=time_from, time_to=time_to, sender=sender, keyword=keyword)
    return out[-limit:] if limit else out


def _time_of(msg: Message) -> str:
    """HH:MM from full ISO ts; '' when ts is display text only."""
    ts = msg.ts or ""
    return ts[11:16] if len(ts) >= 16 and ts[10:11] == "T" else ""


def apply_filters(
    msgs: list["Message"],
    date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    time_from: str | None = None,
    time_to: str | None = None,
    sender: str | None = None,
    keyword: str | None = None,
) -> list["Message"]:
    """Pure post-filter (no browser). `date` is shorthand for from==to."""
    if date is not None:
        date_from = date_to = date
    out = msgs
    if date_from is not None:
        out = [m for m in out if m.date >= date_from]
    if date_to is not None:
        out = [m for m in out if m.date and m.date <= date_to]
    if time_from is not None or time_to is not None:
        keep = []
        for m in out:
            t = _time_of(m)
            if not t:
                continue
            if time_from is not None and t < time_from:
                continue
            if time_to is not None and t > time_to:
                continue
            keep.append(m)
        out = keep
    if sender is not None:
        out = [m for m in out if sender in m.sender]
    if keyword is not None:
        out = [m for m in out if keyword in m.text]
    return out


def sender_stats(msgs: list["Message"]) -> list[dict]:
    """Count messages per sender, most first. Pure (no browser)."""
    counts: dict[str, int] = {}
    for m in msgs:
        name = m.sender or "(เรา)"
        counts[name] = counts.get(name, 0) + 1
    return [{"sender": s, "count": c} for s, c in sorted(counts.items(), key=lambda kv: -kv[1])]


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
