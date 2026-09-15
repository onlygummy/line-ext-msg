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
