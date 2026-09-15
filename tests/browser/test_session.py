"""Session helpers survive a missing extension (no real browser)."""

import json

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


class _Res:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def test_close_extension_tabs_closes_only_extension_pages(monkeypatch):
    settings = make_settings()
    ext_url = f"chrome-extension://{settings.extension_id}/index.html#/chats"
    targets = [
        {"type": "page", "url": ext_url, "id": "a"},
        {"type": "page", "url": "https://example.com", "id": "b"},
        {"type": "service_worker", "url": ext_url, "id": "c"},
    ]
    closed = []

    def fake_urlopen(url, timeout=0):
        if url.endswith("/json/list"):
            return _Res(json.dumps(targets).encode())
        closed.append(url)
        return _Res(b"")

    monkeypatch.setattr(session.urllib.request, "urlopen", fake_urlopen)
    session.close_extension_tabs(settings)
    assert closed == [f"{settings.cdp_endpoint}/json/close/a"]


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
