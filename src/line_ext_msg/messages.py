"""Message extraction returning Message models with real dates."""

import re
from datetime import datetime

from playwright.sync_api import Page

from .models import Message
from .settings import SELECTORS, Settings

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


def _msg_count(page: Page) -> int:
    """Number of rendered message rows. -1 when the query itself fails."""
    try:
        return page.locator(SELECTORS["message_item"]).count()
    except Exception:
        return -1


def _oldest_epoch(page: Page) -> int:
    """Epoch ms of the first (oldest) rendered node. 0 when unknown."""
    try:
        epoch = page.evaluate(
            """() => {
                const el = document.querySelector('[data-timestamp]');
                if (!el) return 0;
                const v = parseInt(el.getAttribute('data-timestamp') || '0', 10);
                return Number.isFinite(v) ? v : 0;
            }""",
        )
        return epoch if isinstance(epoch, int) and epoch > 0 else 0
    except Exception:
        return 0


# Shared scroll-box picker (single-arg scripts only): the chat content box
# when it is really scrollable, else the nearest scrollable ancestor
# (overlay counts: Chrome reports LINE's scroller that way), else whatever
# box exists. Scrollability is verified by height, never assumed from the
# selector alone: picking a fixed 716px-tall non-scrolling panel is exactly
# how backfill silently concluded 'top' with history remaining.
_PICK_BOX = """const pick = (sel) => {
    const direct = document.querySelector("[class*='chatroomContent-module__content_area']");
    if (direct && direct.scrollHeight > direct.clientHeight + 4) return direct;
    const list = document.querySelector(sel);
    if (!list) return null;
    let sc = list;
    while (sc && sc !== document.body) {
        const ov = getComputedStyle(sc).overflowY;
        if ((ov === 'auto' || ov === 'scroll' || ov === 'overlay') &&
            sc.scrollHeight > sc.clientHeight + 4) return sc;
        sc = sc.parentElement;
    }
    return direct || list;
};"""


def _scroll_box_state(page: Page) -> tuple[float, float, float, bool]:
    """(scrollTop, scrollHeight, clientHeight, found) of the chat scroll box.

    Read BEFORE scrolling: reading after setting scrollTop = 0 always
    yields 0, which says nothing about whether history is exhausted.
    Height matters too, because prepended rows can grow the box while
    the rendered count stays flat (windowing unloads the other end).
    Negative tops are valid (column-reverse boxes rest below zero).
    """
    try:
        state = page.evaluate(
            "(listSel) => {\n" + _PICK_BOX + "\n"
            "    const box = pick(listSel);\n"
            "    if (!box) return [-1, -1, -1];\n"
            "    return [box.scrollTop, box.scrollHeight, box.clientHeight];\n"
            "}",
            SELECTORS["message_list"],
        )
        if (isinstance(state, list) and len(state) == 3
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in state)):
            return float(state[0]), float(state[1]), float(state[2]), True
        return 0.0, 0.0, 0.0, False
    except Exception:
        return 0.0, 0.0, 0.0, False


def _probe_scroll_dir(page: Page) -> int:
    """Which way scrollTop moves toward older history: +1 or -1.

    Sets scrollTop 1000px toward older content and reads back: a
    column-reverse box keeps the negative value, a normal box clamps to
    zero. Restores the original position afterwards. Defaults to +1.
    """
    try:
        probed = page.evaluate(
            "(listSel) => {\n" + _PICK_BOX + "\n"
            "    const box = pick(listSel);\n"
            "    if (!box) return null;\n"
            "    const before = box.scrollTop;\n"
            "    box.scrollTop = before - 1000;\n"
            "    const after = box.scrollTop;\n"
            "    box.scrollTop = before;\n"
            "    return [before, after];\n"
            "}",
            SELECTORS["message_list"],
        )
        if (isinstance(probed, list) and len(probed) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                        for v in probed)
                and probed[1] < probed[0] - 100):
            return -1
        return 1
    except Exception:
        return 1


def _stride_target(top: float, edge: float, ch: float) -> float:
    """scrollTop target moving toward older history (pure, testable).

    Stride is half the remaining distance, clamped to 1-4 viewports, so
    long boxes are crossed in a handful of rounds instead of dozens.
    Parked at the edge, the target is the edge itself (hold position).
    """
    ch = max(float(ch), 1.0)
    stride = min(max((top - edge) / 2, ch), ch * 4)
    return max(edge, top - stride)


def _scroll_up_one(page: Page, target: float, top_before: float = 0.0,
                   direction: int = 1) -> bool:
    """Set scrollTop to a precomputed target. False when box is missing.

    All geometry decisions live in Python (_stride_target); the script
    is a dumb setter so there is exactly one place to get direction
    wrong. top_before/direction travel along for observability only.
    Playwright passes a single argument, so the script takes one object
    and unpacks it inside (two declared params would misalign).
    """
    try:
        goal = float(target)
    except (TypeError, ValueError):
        return False
    try:
        return bool(page.evaluate(
            "(args) => {\n" + _PICK_BOX + "\n"
            "    const box = pick(args.listSel);\n"
            "    if (!box) return false;\n"
            "    box.scrollTop = args.target;\n"
            "    return true;\n"
            "}",
            {"listSel": SELECTORS["message_list"], "target": goal,
             "topBefore": top_before, "direction": direction},
        ))
    except Exception:
        return False


def _scroll_date(page: Page) -> str:
    """data-scroll-date anchor on the message list ('' when unreadable).

    The app moves this anchor as older history loads, so a change means
    the loader is working even when the rendered count and the box
    height both look flat.
    """
    try:
        val = page.evaluate(
            """(listSel) => {
                const list = document.querySelector(listSel);
                if (!list) return '';
                return list.getAttribute('data-scroll-date') || '';
            }""",
            SELECTORS["message_list"],
        )
        return val if isinstance(val, str) else ""
    except Exception:
        return ""


def _scroll_box_info(page: Page) -> str:
    """One-line description of the chosen scroll box, for run logs."""
    try:
        info = page.evaluate(
            "(listSel) => {\n" + _PICK_BOX + "\n"
            "    const box = pick(listSel);\n"
            "    if (!box) return 'no-box';\n"
            "    return box.className + ' top=' + box.scrollTop\n"
            "        + ' h=' + box.scrollHeight + ' ch=' + box.clientHeight;\n"
            "}",
            SELECTORS["message_list"],
        )
        return str(info)
    except Exception:
        return "unknown"


def _wheel_up(page: Page) -> bool:
    """    Roll real wheel events over the message list center.

    Some virtualizers listen only to wheel events, so scrollTop sets do
    nothing there. Dips down first and comes back up to re-enter the top
    edge the way a human would; the loop's own settle observes the
    result. False when the list geometry is unreadable or any tick fails.
    """
    try:
        rect = page.locator(SELECTORS["message_list"]).bounding_box()
        if not rect:
            return False
        page.mouse.move(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
        for _ in range(2):
            page.mouse.wheel(0, 400)
        for _ in range(2):
            page.mouse.wheel(0, -400)
        return True
    except Exception:
        return False


def _scroll_to_fill(
    page: Page,
    settings: Settings,
    need: int,
    date_from: str | None = None,
    on_round=None,
) -> str:
    """Scroll the chat up so older rows render before the read pass.

    Returns the stop reason: 'disabled', 'need', 'top', 'date',
    'budget', or 'detached'. 'need' means enough rows accumulated;
    'top' means parked at the older edge (top 0, or the negative edge
    in column-reverse boxes) with a stable count, height, and
    scroll-date anchor five rounds in a row (the first rounds act as
    grace for slow image-heavy history). The scroll direction is probed
    once per run. on_round() is called after each settle and
    its return     value (accumulated unique count) drives the need check;
    without it the rendered count is used. Each round strides toward
    the older edge (half the remaining distance, 1-4 viewports), so the
    loop ends via need/top/date; the time budget (need * 1000ms, capped
    at 300s, never below settings.messages_scroll_ms) is only a
    last-resort guard. Skipped entirely when disabled (0).
    """
    def have() -> int:
        if on_round is not None:
            try:
                return on_round()
            except Exception:
                return 0
        return _msg_count(page)

    if settings.messages_scroll_ms <= 0:
        return "disabled"
    count = _msg_count(page)
    if count < 0:
        return "detached"
    if need and have() >= need:
        return "need"
    # Scroll until the messages are complete: the budget is only a
    # last-resort guard, scaled generously so normal runs end via
    # need/top/date instead of timing out mid-history.
    budget = settings.messages_scroll_ms
    if need:
        budget = max(budget, min(need * 1000, 300000))
    stable_top = 0
    waited = 0
    rounds = 0
    stuck = 0
    wheel_tries = 0
    last_log = 0
    step = 1000
    reason = "budget"
    have_now = have()
    _, prev_height, _, found = _scroll_box_state(page)
    if not found:
        return "detached"
    prev_date = _scroll_date(page)
    direction = _probe_scroll_dir(page)
    if not settings.quiet:
        print(f"  ... กล่อง scroll: {_scroll_box_info(page)} ทิศ={direction}",
              flush=True)
    while waited < budget:
        if need and have_now >= need:
            reason = "need"
            break
        if date_from:
            epoch = _oldest_epoch(page)
            if epoch:
                oldest = datetime.fromtimestamp(epoch / 1000).strftime("%Y-%m-%d")
                if oldest and oldest < date_from:
                    reason = "date"
                    break
        top_before, height_before, ch_before, found = _scroll_box_state(page)
        if not found:
            # Transient (React mid-render replacing nodes): burn one step
            # and retry next round instead of aborting; the budget bounds us.
            try:
                page.wait_for_timeout(step)
            except Exception:
                reason = "detached"
                break
            waited += step
            rounds += 1
            continue
        if direction > 0:
            edge = 0.0
        else:
            edge = -(height_before - ch_before)
        at_edge = top_before <= edge + 4
        target = _stride_target(top_before, edge, ch_before)
        if not _scroll_up_one(page, target, top_before, direction):
            reason = "detached"
            break
        try:
            page.wait_for_timeout(step)
        except Exception:
            reason = "detached"
            break
        waited += step
        rounds += 1
        now = _msg_count(page)
        if now < 0:
            reason = "detached"
            break
        # Height must be read AFTER the settle: comparing the pre-scroll
        # value lags one round behind and hides this round's growth.
        top_after, height_after, _, found = _scroll_box_state(page)
        if not found:
            try:
                page.wait_for_timeout(step)
            except Exception:
                reason = "detached"
                break
            waited += step
            rounds += 1
            continue
        have_now = have()
        if not settings.quiet and waited - last_log >= 2000:
            last_log = waited
            want = f"/{need}" if need else ""
            print(f"  ... เลื่อนโหลดเพิ่ม ({have_now}{want})", flush=True)
        if settings.debug_scroll:
            print(f"  ... [dbg r{rounds} top {top_before}->{top_after}"
                  f" h {prev_height}->{height_after} n {count}->{now}"
                  f" have {have_now} date {prev_date}->{_scroll_date(page)}]",
                  flush=True)
        moved = top_after != top_before
        if now == count and at_edge and height_after == prev_height:
            stable_top += 1
            if stable_top >= 5:
                reason = "top"
                break
        else:
            stable_top = 0
        if not moved and now == count and height_after == prev_height:
            stuck += 1
        else:
            stuck = 0
        # scrollTop sets that change nothing fire no scroll event, so a
        # wheel-only loader would sleep: poke it with a real wheel event.
        if stuck >= 2 and wheel_tries < 3:
            wheel_tries += 1
            if not settings.quiet:
                print(f"  ... ลองหมุน wheel (ครั้งที่ {wheel_tries})", flush=True)
            if _wheel_up(page):
                stuck = 0
        scroll_day = _scroll_date(page)
        if scroll_day != prev_date:
            stable_top = 0
        prev_date = scroll_day
        prev_height = height_after
        count = now
    if not settings.quiet and (waited or reason != "need"):
        want = f"/{need}" if need else ""
        print(f"  ... โหลดได้ {have_now}{want} (หยุดเพราะ: {reason}, {rounds} รอบ)",
              flush=True)
    return reason


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
            sig = _rendered_keys(page)
        except Exception:
            sig = None
        if sig is None or sig != last_sig:
            last_sig = sig
            try:
                rows = _extract_current(page, media_dir, include_media_data, set(seen))
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
        _scroll_to_fill(page, settings, 0 if filtered else (limit or 0),
                         date_from=date or date_from, on_round=capture)

    out = apply_filters(list(seen.values()), date=date, date_from=date_from,
                        date_to=date_to, time_from=time_from, time_to=time_to,
                        sender=sender, keyword=keyword)
    # DOM order is newest-first (verified in room dumps), so the latest
    # messages are at the head, not the tail.
    return out[:limit] if limit else out

def _rendered_keys(page: Page) -> list[tuple[str, str]] | None:
    """(select-id, timestamp) of rendered rows in DOM order.

    None means the probe itself failed (caller should extract anyway);
    [] means the probe worked and no rows are rendered. One cheap
    evaluate: lets the caller skip a full extraction round when the
    virtualized window did not change.
    """
    try:
        rows = page.evaluate(
            """(sels) => {
                const rows = [];
                for (const part of sels.item.split(',')) {
                    document.querySelectorAll(part.trim()).forEach(el => rows.push(el));
                }
                return rows.map(el => [
                    el.getAttribute('data-message-select-id') || '',
                    el.getAttribute('data-timestamp') || '',
                ]);
            }""",
            {"item": f"{SELECTORS['message_item']}, {SELECTORS['system_row']}"},
        )
        if isinstance(rows, list):
            return [(str(a or ""), str(b or "")) for a, b in rows if isinstance(a, str)]
        return None
    except Exception:
        return None


def _extract_current(
    page: Page,
    media_dir: str | None,
    include_media_data: bool,
    skip_media_ids: set[str],
) -> list[Message]:
    """Full Message models for currently rendered rows, newest-first.

    Image bubbles whose id is in skip_media_ids keep empty media fields
    (already downloaded in an earlier round). Never raises: skips bad rows.
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
        media, media_data = "", ""
        if kind == "image" and (media_dir or include_media_data) and msg_id not in skip_media_ids:
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

    return out


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
        if m.type == "system":
            continue
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
