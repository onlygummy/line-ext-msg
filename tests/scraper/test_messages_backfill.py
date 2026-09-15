"""Message backfill scroll: stop rules without a browser."""

import logging
from typing import cast

from playwright.sync_api import Page

from line_ext_msg.config.settings import Settings
from line_ext_msg.scraper import messages, scroll
from tests.helpers import make_settings as _settings
from tests.helpers import patch_selectors as _patch_selectors


class _Count:
    def __init__(self, page, sel):
        self._page = page
        self._sel = sel

    def count(self):
        return self._page.counts.get(self._sel, 0)

    def bounding_box(self):
        return {"x": 0, "y": 0, "width": 100, "height": 100}


class _WheelMouse:
    def __init__(self, page):
        self._page = page

    def move(self, x, y):
        pass

    def wheel(self, dx, dy):
        self._page.wheeled += 1
        self._page.wheel_moves.append((dx, dy))
        if self._page.wheel_loads:
            self._page.counts["msg"] = min(
                self._page.total, self._page.counts["msg"] + 5)


class _FakePage:
    """Scripts message counts; scroll evaluate grows them toward total."""

    def __init__(self, start=5, total=5, oldest_epoch=0, slow_rounds=0,
                 top_zero=False, height_bump=0, wheel_loads=False,
                 date_shifts=0, fail_state_at=(), reverse=False):
        self.total = total
        self.counts = {"msg": start}
        self.oldest_epoch = oldest_epoch
        self.slow = slow_rounds  # scroll rounds before new rows render
        self.top_zero = top_zero  # box already at top while loader lags
        self.reverse = reverse  # column-reverse box: older lives negative
        self.top = 0 if (start >= total or top_zero or reverse) else 100
        self.ch = 716
        self.extra_height = 0
        self.height_bump = height_bump  # initial scrolls that grow height only
        self.wheel_loads = wheel_loads  # loader answers wheel events only
        self.scroll_date = "day0"
        self.date_shifts = date_shifts  # initial scrolls that move the date only
        self.fail_state_at = set(fail_state_at)  # state-probe call indices to flunk
        self._state_calls = 0
        self.wheeled = 0
        self.wheel_moves = []
        self.mouse = _WheelMouse(self)
        self.scrolls = 0
        self.sleeps = 0
        self.scroll_args = []
        self.targets = []

    @property
    def height(self):
        return self.counts["msg"] * 70 + self.extra_height

    def locator(self, sel):
        return _Count(self, "msg")

    def wait_for_selector(self, _sel, timeout=0, state=None):
        return True

    def evaluate(self, js, arg=None):
        if "- 1000" in js:  # direction probe: negative sticks iff reverse
            return [self.top, self.top - 1000 if self.reverse else self.top]
        if "args.target" in js:  # directed scroll step: follow the target
            self.scrolls += 1
            if isinstance(arg, dict):
                self.scroll_args.append(dict(arg))
                self.targets.append(arg.get("target"))
            self.top = float(arg.get("target", self.top)) if isinstance(arg, dict) else self.top
            if self.date_shifts > 0:
                self.date_shifts -= 1
                self.scroll_date += ">"
            elif self.height_bump > 0:
                self.height_bump -= 1
                self.extra_height += 70
            elif self.slow > 0:
                self.slow -= 1
            else:
                self.counts["msg"] = min(self.total, self.counts["msg"] + 5)
            return True
        if "className" in js:  # box-info probe
            return f"box top={self.top} h={self.height}"
        if "scrollHeight" in js:  # box-state probe
            self._state_calls += 1
            if self._state_calls in self.fail_state_at:
                return "mid-render-garbage"
            return [self.top, self.height, self.ch]
        if "data-scroll-date" in js:  # date-anchor probe
            return self.scroll_date
        if "data-timestamp" in js:
            return self.oldest_epoch
        return self.top  # legacy top read (no side effects)

    def wait_for_timeout(self, ms):
        self.sleeps += 1


def test_no_scroll_when_enough_rendered():
    page = _FakePage(start=10, total=10)
    old = _patch_selectors(scroll, message_item="msg")
    try:
        reason = scroll.scroll_to_fill(cast(Page, page), _settings(), need=5)
    finally:
        scroll.SELECTORS = old
    assert reason == "need"
    assert page.scrolls == 0
    assert page.sleeps == 0


def test_scrolls_until_need_met():
    page = _FakePage(start=5, total=15)
    old = _patch_selectors(scroll, message_item="msg")
    try:
        scroll.scroll_to_fill(cast(Page, page), _settings(), need=15)
    finally:
        scroll.SELECTORS = old
    assert page.counts["msg"] == 15
    assert page.scrolls == 2


def test_disabled_setting_skips_scroll():
    page = _FakePage(start=2, total=50)
    old = _patch_selectors(scroll, message_item="msg")
    try:
        reason = scroll.scroll_to_fill(
            cast(Page, page), _settings(messages_scroll_ms=0), need=50)
    finally:
        scroll.SELECTORS = old
    assert reason == "disabled"
    assert page.scrolls == 0
    assert page.sleeps == 0


def test_stops_when_count_stable_at_top():
    page = _FakePage(start=5, total=5)
    old = _patch_selectors(scroll, message_item="msg")
    try:
        reason = scroll.scroll_to_fill(cast(Page, page), _settings(), need=50)
    finally:
        scroll.SELECTORS = old
    # Count never grows and already at the real top: five steady rounds
    # prove history is exhausted without burning the whole budget.
    assert reason == "top"
    assert page.sleeps == 5


def test_slow_loader_at_top_does_not_stop_early():
    # The reported bug: box already at top while image-heavy history is
    # still loading. Three quiet rounds must not end the loop.
    page = _FakePage(start=5, total=15, slow_rounds=4, top_zero=True)
    old = _patch_selectors(scroll, message_item="msg")
    try:
        reason = scroll.scroll_to_fill(cast(Page, page), _settings(), need=15)
    finally:
        scroll.SELECTORS = old
    assert reason == "need"
    assert page.counts["msg"] == 15
    assert page.scrolls == 6


def test_slow_load_does_not_stop_early():
    page = _FakePage(start=5, total=15, slow_rounds=2)
    old = _patch_selectors(scroll, message_item="msg")
    try:
        scroll.scroll_to_fill(cast(Page, page), _settings(), need=15)
    finally:
        scroll.SELECTORS = old
    # First two scrolls render nothing but the list is not at the top,
    # so the loop must keep going until the rows actually arrive.
    assert page.counts["msg"] == 15
    assert page.scrolls == 4


def test_stops_when_older_than_date_from():
    from datetime import datetime

    old_day = datetime(2026, 9, 1)
    epoch_ms = int(old_day.timestamp() * 1000)
    page = _FakePage(start=5, total=100, oldest_epoch=epoch_ms)
    old = _patch_selectors(scroll, message_item="msg")
    try:
        reason = scroll.scroll_to_fill(
            cast(Page, page), _settings(), need=0, date_from="2026-09-10",
        )
    finally:
        scroll.SELECTORS = old
    assert reason == "date"
    assert page.scrolls == 0


class _NodeText:
    def __init__(self, value):
        self._value = value
        self.first = self

    def count(self):
        return 1 if self._value else 0

    def text_content(self, timeout=0):
        return self._value


class _Node:
    """One text bubble. DOM order given newest-first."""

    def __init__(self, mid, epoch_ms):
        self._mid = mid
        self._epoch = str(epoch_ms)

    def get_attribute(self, name):
        if name == "class":
            return "message-module__message__x"
        if name == "data-timestamp":
            return self._epoch
        if name == "data-message-select-id":
            return self._mid
        return ""

    def locator(self, sel):
        if "textMessageContent" in sel:
            return _NodeText("hi")
        return _NodeText("")

    def inner_text(self):
        return "hi"


class _Nodes:
    def __init__(self, nodes):
        self._nodes = nodes

    def count(self):
        return len(self._nodes)

    def nth(self, i):
        return self._nodes[i]


class _MsgPage:
    def __init__(self, nodes):
        self._nodes = nodes

    def wait_for_selector(self, _sel, timeout=0, state=None):
        return True

    def locator(self, _sel):
        return _Nodes(self._nodes)

    def evaluate(self, js, _arg=None):
        return [[n._mid, n._epoch] for n in self._nodes]


def test_limit_takes_newest_head():
    base = 1789175000000
    nodes = [_Node(f"n{i}", base - i * 60000) for i in range(3)]
    page = _MsgPage(nodes)
    out = messages.get_messages(cast(Page, page), _settings(), limit=2, scroll=False)
    assert [m.id for m in out] == ["n0", "n1"]


def test_limit_zero_returns_all():
    base = 1789175000000
    nodes = [_Node(f"n{i}", base - i * 60000) for i in range(3)]
    page = _MsgPage(nodes)
    out = messages.get_messages(cast(Page, page), _settings(), limit=0, scroll=False)
    assert [m.id for m in out] == ["n0", "n1", "n2"]


class _SlidingPage:
    """Rendered window slides older per scroll, unloading the newest."""

    def __init__(self, windows):
        self._windows = windows
        self._i = 0
        self.fetches = 0
        self.scroll_args = []

    @property
    def _nodes(self):
        return self._windows[min(self._i, len(self._windows) - 1)]

    def wait_for_selector(self, _sel, timeout=0, state=None):
        return True

    def locator(self, _sel):
        return _Nodes(self._nodes)

    def evaluate(self, js, arg=None):
        if "- 1000" in js:  # direction probe: normal world here
            return [100, 100]
        if "args.target" in js:  # directed scroll step: show next window
            self._i = min(self._i + 1, len(self._windows) - 1)
            if isinstance(arg, dict):
                self.scroll_args.append(dict(arg))
            return True
        if "className" in js:  # box-info probe
            return f"box win{self._i}"
        if "scrollHeight" in js:  # box-state probe
            top = 0 if self._i >= len(self._windows) - 1 else 100
            return [top, 1000 + self._i * 200, 716]
        if "data-scroll-date" in js:  # date-anchor probe
            return f"day{self._i}"
        if "data-message-select-id" in js:  # rendered-keys probe
            return [[n._mid, n._epoch] for n in self._nodes]
        if "arrayBuffer" in js:  # blob fetch for image bubbles
            self.fetches += 1
            return {"data": "aGk=", "mime": "image/png"}
        if "data-timestamp" in js:  # oldest-epoch probe
            return int(self._nodes[-1]._epoch) if self._nodes else 0
        return 100  # legacy top read (no side effects)

    def wait_for_timeout(self, ms):
        pass


def _win(base, ids):
    return [_Node(f"n{i}", base - i * 60000) for i in ids]


def test_sliding_window_keeps_unloaded_newest():
    base = 1789175000000
    page = _SlidingPage([_win(base, [0, 1, 2]), _win(base, [2, 3, 4])])
    out = messages.get_messages(cast(Page, page), _settings(), limit=5, scroll=True)
    # n0/n1 were unloaded by the scroll but must survive via SeenMap.
    assert [m.id for m in out] == ["n0", "n1", "n2", "n3", "n4"]


class _ImgNode(_Node):
    def locator(self, sel):
        if "imageMessageContent" in sel or sel == "img":
            return self
        return _NodeText("")

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def get_attribute(self, name):
        if name == "src":
            return "blob:fake-img"
        return super().get_attribute(name)


def test_image_not_redownloaded_for_known_id(tmp_path):
    base = 1789175000000
    page = _SlidingPage([[_ImgNode("img1", base)], [_ImgNode("img1", base)]])
    media = str(tmp_path)
    out = messages.get_messages(
        cast(Page, page), _settings(), limit=5, scroll=True, media_dir=media)
    assert [m.id for m in out] == ["img1"]
    assert out[0].media.endswith(".png")
    assert page.fetches == 1


def test_parked_top_holds_edge():
    # Box starts at the top; every target must hold the edge instead of
    # wandering, otherwise the loader debounce resets each round.
    page = _FakePage(start=5, total=15, top_zero=True)
    old = _patch_selectors(scroll, message_item="msg")
    try:
        reason = scroll.scroll_to_fill(cast(Page, page), _settings(), need=15)
    finally:
        scroll.SELECTORS = old
    assert reason == "need"
    assert page.counts["msg"] == 15
    assert page.targets == [0, 0]


def test_stride_target():
    from line_ext_msg.scraper.scroll import stride_target as _stride_target
    assert _stride_target(13200, 0, 716) == 10336
    assert _stride_target(1000, 0, 716) == 284
    assert _stride_target(0, 0, 716) == 0
    assert _stride_target(0, -13194, 716) == -2864
    assert _stride_target(-13194, -13194, 716) == -13194
    assert _stride_target(100, 0, 0) == 96


def test_height_growth_resets_stability():
    # Count flat but box keeps growing: loader prepends above while the
    # other end unloads. Must not conclude 'top' until truly steady.
    page = _FakePage(start=5, total=5, height_bump=3)
    old = _patch_selectors(scroll, message_item="msg")
    try:
        reason = scroll.scroll_to_fill(cast(Page, page), _settings(), need=50)
    finally:
        scroll.SELECTORS = old
    assert reason == "top"
    assert page.sleeps == 8


def test_budget_scales_with_need():
    # Date anchor drifts forever while rows never arrive: only the
    # budget can end this run, scaled generously with need.
    page = _FakePage(start=5, total=50, slow_rounds=999, date_shifts=9999)
    old = _patch_selectors(scroll, message_item="msg")
    try:
        reason = scroll.scroll_to_fill(
            cast(Page, page), _settings(messages_scroll_ms=500), need=100)
    finally:
        scroll.SELECTORS = old
    # max(500, min(100*1000, 300000)) = 100000ms = 100 rounds at 1000ms.
    assert reason == "budget"
    assert page.sleeps == 100


def test_small_need_keeps_base_budget():
    page = _FakePage(start=5, total=50, slow_rounds=999, date_shifts=9999)
    old = _patch_selectors(scroll, message_item="msg")
    try:
        reason = scroll.scroll_to_fill(
            cast(Page, page), _settings(messages_scroll_ms=500), need=0)
    finally:
        scroll.SELECTORS = old
    assert reason == "budget"
    assert page.sleeps == 1


def test_wheel_fallback_wakes_wheel_only_loader():
    # scrollTop sets never move (stuck box) but the loader answers wheel
    # events: the loop must poke it instead of concluding 'top'.
    page = _FakePage(start=5, total=15, top_zero=True, slow_rounds=999,
                     wheel_loads=True)
    old = _patch_selectors(scroll, message_item="msg")
    try:
        reason = scroll.scroll_to_fill(cast(Page, page), _settings(), need=15)
    finally:
        scroll.SELECTORS = old
    assert reason == "need"
    assert page.counts["msg"] == 15
    assert page.wheeled >= 1


def test_box_info_logged(caplog):
    caplog.set_level(logging.INFO, logger="line_ext_msg")
    page = _FakePage(start=5, total=5)
    old = _patch_selectors(scroll, message_item="msg")
    try:
        scroll.scroll_to_fill(
            cast(Page, page), Settings(), need=50)
    finally:
        scroll.SELECTORS = old
    assert "scroll box" in caplog.text


def test_scroll_date_change_resets_stability():
    # Date anchor moves while count and height look flat: the loader is
    # still working, so the loop must not conclude 'top' yet.
    page = _FakePage(start=5, total=5, date_shifts=3)
    old = _patch_selectors(scroll, message_item="msg")
    try:
        reason = scroll.scroll_to_fill(cast(Page, page), _settings(), need=50)
    finally:
        scroll.SELECTORS = old
    assert reason == "top"
    assert page.sleeps == 8


def test_transient_probe_failure_continues():
    # React mid-render can answer one probe with garbage: burn a step
    # and retry instead of aborting the whole loop as 'detached'.
    page = _FakePage(start=5, total=15, slow_rounds=0, fail_state_at={2})
    old = _patch_selectors(scroll, message_item="msg")
    try:
        reason = scroll.scroll_to_fill(cast(Page, page), _settings(), need=15)
    finally:
        scroll.SELECTORS = old
    assert reason == "need"
    assert page.counts["msg"] == 15


def test_wheel_dips_down_then_up():
    # Wheel fallback must re-enter the top edge the way a human would:
    # down ticks first, then back up.
    page = _FakePage(start=5, total=15, top_zero=True, slow_rounds=999,
                     wheel_loads=True)
    old = _patch_selectors(scroll, message_item="msg")
    try:
        scroll.scroll_to_fill(cast(Page, page), _settings(), need=15)
    finally:
        scroll.SELECTORS = old
    downs = [dy for dx, dy in page.wheel_moves if dy > 0]
    ups = [dy for dx, dy in page.wheel_moves if dy < 0]
    assert downs and ups
    assert page.wheel_moves.index((0, downs[0])) < page.wheel_moves.index((0, ups[0]))


def test_wheel_attempt_logged(caplog):
    caplog.set_level(logging.INFO, logger="line_ext_msg")
    page = _FakePage(start=5, total=15, top_zero=True, slow_rounds=999,
                     wheel_loads=True)
    old = _patch_selectors(scroll, message_item="msg")
    try:
        reason = scroll.scroll_to_fill(
            cast(Page, page), Settings(), need=15)
    finally:
        scroll.SELECTORS = old
    assert reason == "need"
    assert "wheel attempt" in caplog.text


def test_reverse_box_walks_negative_to_need():
    # Column-reverse world: older history lives at negative scrollTop.
    # The probe must report -1, every scroll must carry it, and the loop
    # must keep walking negative until enough rows accumulate.
    page = _FakePage(start=15, total=30, reverse=True)
    old = _patch_selectors(scroll, message_item="msg")
    try:
        reason = scroll.scroll_to_fill(cast(Page, page), _settings(), need=30)
    finally:
        scroll.SELECTORS = old
    assert reason == "need"
    assert page.counts["msg"] == 30
    assert page.scroll_args, "scroll calls must record their args"
    assert {a.get("direction") for a in page.scroll_args} == {-1}
    assert page.top < 0


def test_probe_defaults_to_normal_world():
    page = _FakePage(start=5, total=5)
    old = _patch_selectors(scroll, message_item="msg")
    try:
        scroll.scroll_to_fill(cast(Page, page), _settings(), need=50)
    finally:
        scroll.SELECTORS = old
    assert {a.get("direction") for a in page.scroll_args} == {1}
