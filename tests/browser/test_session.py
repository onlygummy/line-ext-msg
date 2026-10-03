"""Session helpers survive a missing extension (no real browser)."""

from line_ext_msg.browser import session
from tests.helpers import make_settings


class _Page:
    url = "chrome-error://chromewebdata/"

    def __init__(self, fail_goto=False):
        self.fail_goto = fail_goto
        self.gotos = []
        self.fronted = 0

    def goto(self, url, timeout=0):
        self.gotos.append(url)
        if self.fail_goto:
            raise RuntimeError("net::ERR_BLOCKED_BY_CLIENT")

    def bring_to_front(self):
        self.fronted += 1

    def wait_for_load_state(self, *_a, **_k):
        pass


class _Context:
    def __init__(self, page=None):
        self.pages = []
        self._page = page or _Page()

    def new_page(self):
        return self._page


def _no_network(monkeypatch):
    # Tab cleanup talks to the CDP endpoint; keep the unit test offline.
    monkeypatch.setattr(session, "close_duplicate_line_targets", lambda settings: None)
    monkeypatch.setattr(session, "close_startup_tabs", lambda settings: None)


def test_ensure_line_page_survives_blocked_extension_url(monkeypatch):
    _no_network(monkeypatch)
    page = _Page(fail_goto=True)
    result = session.ensure_line_page(_Context(page), make_settings())
    assert result is page
    assert page.gotos == [make_settings().chats_url]


def test_open_store_page_returns_fronted_tab(monkeypatch):
    _no_network(monkeypatch)
    page = _Page()
    result = session.open_store_page(_Context(page), make_settings())
    assert result is page
    assert page.fronted == 1
    assert page.gotos == [make_settings().webstore_url]


def test_close_extension_tabs_closes_only_extension_pages(monkeypatch):
    settings = make_settings()
    ext_url = f"chrome-extension://{settings.extension_id}/index.html#/chats"
    targets = [
        {"type": "page", "url": ext_url, "id": "a"},
        {"type": "page", "url": "https://example.com", "id": "b"},
        {"type": "service_worker", "url": ext_url, "id": "c"},
    ]
    closed = []
    monkeypatch.setattr(session.cdp, "list_targets", lambda s, timeout_sec=3: targets)
    monkeypatch.setattr(
        session.cdp, "close_target", lambda s, target_id, timeout_sec=3: closed.append(target_id)
    )
    session.close_extension_tabs(settings)
    assert closed == ["a"]


class _ReadyPage:
    """Minimal page recording the settle wait the caller applied."""

    def __init__(self):
        self.settle_waits = []

    def wait_for_function(self, *_a, **_k):
        pass

    def wait_for_selector(self, *_a, **_k):
        pass

    def wait_for_timeout(self, ms):
        self.settle_waits.append(ms)


def test_wait_ready_uses_the_configured_settle_window():
    page = _ReadyPage()
    assert session.wait_ready(page, make_settings(ready_settle_ms=150)) == "ready"
    assert page.settle_waits == [150]


class _NoProbeContext:
    def new_page(self):
        raise AssertionError("no probe tab when the files are already on disk")


def test_check_installed_skips_probe_when_on_disk(monkeypatch):
    monkeypatch.setattr(session, "is_on_disk", lambda settings: True)
    monkeypatch.setattr(session, "find_line_page", lambda target, ext_id: None)
    assert session.check_installed(_NoProbeContext(), make_settings()) == (
        True,
        "found_on_disk=True",
    )


class _BlockedPage:
    def __init__(self):
        self.closed = 0

    def goto(self, url, timeout=0):
        raise RuntimeError(
            "Page.goto: net::ERR_BLOCKED_BY_CLIENT at chrome-extension://x\n"
            "Call log:\n  - navigating to the extension page"
        )

    def close(self):
        self.closed += 1


class _BlockedContext:
    def __init__(self, page):
        self._page = page

    def new_page(self):
        return self._page


def test_check_installed_cleans_the_blocked_probe_message(monkeypatch):
    monkeypatch.setattr(session, "is_on_disk", lambda settings: False)
    monkeypatch.setattr(session, "find_line_page", lambda target, ext_id: None)
    page = _BlockedPage()
    installed, detail = session.check_installed(_BlockedContext(page), make_settings())
    assert installed is False
    assert detail.startswith("probe failed: ")
    assert "\n" not in detail, "the Playwright call log must not leak into the detail"
    assert page.closed == 1


class _ViewPage:
    """Replays a route plus a chat list that appears after some navigation."""

    def __init__(self, url, rows_after=(), rows_after_nav=()):
        self.url = url
        self.gotos = 0
        self.nav_clicks = 0
        self._rows_after = list(rows_after)
        self._rows_after_nav = list(rows_after_nav)

    def goto(self, url, timeout=0):
        self.gotos += 1
        self.url = url
        self._rows_after = list(self._rows_after) or list(self._rows_after_nav)

    def wait_for_load_state(self, *_a, **_k):
        pass

    def wait_for_selector(self, _sel, state=None, timeout=0):
        if self._rows_after:
            return True
        if self._rows_after_nav and self.nav_clicks:
            self._rows_after = list(self._rows_after_nav)
            return True
        raise RuntimeError("no rows yet")

    def locator(self, _sel):
        page = self

        class _Nav:
            @property
            def first(self):
                return self

            def click(self, timeout=0):
                page.nav_clicks += 1

        return _Nav()


def test_on_chats_route_matches_a_route_with_a_parameter():
    page = _ViewPage("chrome-extension://x/index.html#/chats/123")
    assert session._on_chats_route(page) is True


def test_on_chats_route_rejects_other_routes():
    assert session._on_chats_route(_ViewPage("chrome-extension://x/index.html#/friends")) is False
    assert session._on_chats_route(_ViewPage("chrome-extension://x/index.html")) is False


def test_ensure_chats_view_already():
    page = _ViewPage("chrome-extension://x/index.html#/chats", rows_after=["r1"])
    assert session.ensure_chats_view(page, make_settings()) == "already"
    assert page.gotos == 0
    assert page.nav_clicks == 0


def test_ensure_chats_view_navigates_from_another_route():
    page = _ViewPage("chrome-extension://x/index.html#/friends", rows_after=["r1"])
    assert session.ensure_chats_view(page, make_settings()) == "navigated"
    assert page.gotos == 1
    assert page.nav_clicks == 0


def test_ensure_chats_view_clicks_nav_when_the_route_lies():
    """The route says chats but nothing rendered: this is the case a URL
    check alone cannot catch, and the one LINE caused after login."""
    page = _ViewPage("chrome-extension://x/index.html#/chats", rows_after_nav=["r1"])
    assert session.ensure_chats_view(page, make_settings()) == "nav_click"
    assert page.gotos == 0
    assert page.nav_clicks == 1


def test_ensure_chats_view_fails_when_nothing_renders():
    page = _ViewPage("chrome-extension://x/index.html#/friends")
    assert session.ensure_chats_view(page, make_settings()) == "failed"


def test_goto_chats_does_not_wait_for_the_chat_list():
    """It runs before login, where the list cannot render yet, so it must
    neither block on the selector nor report a failure."""
    page = _ViewPage("chrome-extension://x/index.html#/friends")
    session.goto_chats(page, make_settings())
    assert page.gotos == 1
