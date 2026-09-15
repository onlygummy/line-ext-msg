"""Chat scroll mechanics: keep the box moving toward older history.

The chat list is virtualized in both directions, so this module only
moves the box and reports why it stopped; the caller accumulates rows.
All geometry decisions live in Python so there is exactly one place to
get the scroll direction wrong.
"""

from __future__ import annotations

from datetime import datetime

from playwright.sync_api import Page

from ..browser import js
from ..config.selectors import SELECTORS
from ..config.settings import Settings


def msg_count(page: Page) -> int:
    """Number of rendered message rows. -1 when the query itself fails."""
    try:
        return page.locator(SELECTORS["message_item"]).count()
    except Exception:
        return -1


def _oldest_epoch(page: Page) -> int:
    """Epoch ms of the first (oldest) rendered node. 0 when unknown."""
    try:
        epoch = page.evaluate(js.OLDEST_EPOCH)
        return epoch if isinstance(epoch, int) and epoch > 0 else 0
    except Exception:
        return 0


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
            js.SCROLL_BOX_STATE, {"listSel": SELECTORS["message_list"]}
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
            js.PROBE_SCROLL_DIR, {"listSel": SELECTORS["message_list"]}
        )
        if (isinstance(probed, list) and len(probed) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                        for v in probed)
                and probed[1] < probed[0] - 100):
            return -1
        return 1
    except Exception:
        return 1


def stride_target(top: float, edge: float, ch: float) -> float:
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

    All geometry decisions live in Python (stride_target); the script is
    a dumb setter. top_before/direction travel along for observability
    only. Playwright passes a single argument, so the script takes one
    object and unpacks it inside.
    """
    try:
        goal = float(target)
    except (TypeError, ValueError):
        return False
    try:
        return bool(page.evaluate(
            js.SCROLL_SET,
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
            js.SCROLL_DATE, {"listSel": SELECTORS["message_list"]}
        )
        return val if isinstance(val, str) else ""
    except Exception:
        return ""


def _scroll_box_info(page: Page) -> str:
    """One-line description of the chosen scroll box, for run logs."""
    try:
        info = page.evaluate(
            js.SCROLL_BOX_INFO, {"listSel": SELECTORS["message_list"]}
        )
        return str(info)
    except Exception:
        return "unknown"


def _wheel_up(page: Page) -> bool:
    """Roll real wheel events over the message list center.

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


def scroll_to_fill(
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
    once per run. on_round() runs after each settle and its return value
    (accumulated unique count) drives the need check; without it the
    rendered count is used. Each round strides toward the older edge
    (half the remaining distance, 1-4 viewports), so the loop ends via
    need/top/date; the time budget (need * 1000ms, capped at 300s, never
    below settings.messages_scroll_ms) is only a last-resort guard.
    Skipped entirely when disabled (0).
    """
    def have() -> int:
        if on_round is not None:
            try:
                return on_round()
            except Exception:
                return 0
        return msg_count(page)

    if settings.messages_scroll_ms <= 0:
        return "disabled"
    count = msg_count(page)
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
        target = stride_target(top_before, edge, ch_before)
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
        now = msg_count(page)
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
