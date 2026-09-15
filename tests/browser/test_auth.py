"""wait_for_login logic with a fake page (no browser)."""

from typing import cast

from playwright.sync_api import Page

from line_ext_msg.browser import auth


class _FakeLocator:
    def __init__(self, count):
        self._count = count

    def count(self):
        return self._count


class _FakePage:
    """Replays a script of (has_chat, has_login) states per poll."""

    def __init__(self, script, body=""):
        self.script = list(script)
        self.body = body
        self.ticks = []

    def locator(self, sel):
        state = self.script[0] if self.script else (False, False)
        has_chat, has_login = state
        # Room selectors contain chatlistItem/friendlistItem.
        if "chatlistItem" in sel or "friendlistItem" in sel:
            return _FakeLocator(1 if has_chat else 0)
        # Login locators contain loginPage/QR/Log in.
        return _FakeLocator(1 if has_login else 0)

    def wait_for_timeout(self, ms):
        self.ticks.append(ms)
        # Advance one poll per sleep so the script replays in order.
        if len(self.script) > 1:
            self.script.pop(0)

    def inner_text(self, _sel):
        return self.body


def test_immediate_chat():
    page = cast(Page, _FakePage([(True, False)]))
    assert auth.wait_for_login(page, timeout_ms=1000) == (True, "chat")


def test_login_then_chat():
    page = cast(Page, _FakePage([(False, True), (False, True), (True, False)]))
    seen = []
    ok, reason = auth.wait_for_login(page, timeout_ms=5000, on_tick=seen.append)
    assert (ok, reason) == (True, "chat")
    assert seen  # progress callback fired


def test_timeout_still_login():
    page = cast(Page, _FakePage([(False, True)] * 10))
    assert auth.wait_for_login(page, timeout_ms=1000, poll_ms=500) == (False, "login")


def test_timeout_unknown():
    page = cast(Page, _FakePage([(False, False)] * 10))
    assert auth.wait_for_login(page, timeout_ms=1000, poll_ms=500) == (False, "unknown")
