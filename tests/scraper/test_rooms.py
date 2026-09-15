"""Fast room read: batch path, fallback, and bounded scroll (no browser)."""

from typing import cast

from playwright.sync_api import Page

from line_ext_msg.scraper import rooms
from tests.helpers import make_settings as _settings


class _Text:
    def __init__(self, value):
        self.value = value
        self.first = self

    def text_content(self, timeout=0):
        return self.value


class _Row:
    def __init__(self, mid, fields):
        self._mid = mid
        self._fields = fields

    def locator(self, _sel):
        return self

    @property
    def first(self):
        return self

    def text_content(self, timeout=0):
        return self._fields.get("name", "")

    def get_attribute(self, name):
        return self._mid if name == "data-mid" else ""


class _Items:
    def __init__(self, rows):
        self._rows = rows

    def count(self):
        return len(self._rows)

    def nth(self, i):
        return self._rows[i]


class _FakePage:
    def __init__(self, batch=None, rows=None, counts=None, fail_batch=False):
        self._batch = batch
        self._rows = rows or []
        self._counts = list(counts or [len(self._rows)])
        self.fail_batch = fail_batch
        self.evals = 0
        self.sleeps = 0

    def wait_for_selector(self, _sel, timeout=0, state=None):
        return True

    def locator(self, _sel):
        return _Items(self._rows)

    def evaluate(self, _js, _arg=None):
        self.evals += 1
        if self.fail_batch:
            raise RuntimeError("no js")
        if isinstance(self._batch, list):
            return self._batch
        # Scroll probe returns bool; count sequence drives stability.
        if self._counts:
            return True
        return True

    def wait_for_timeout(self, ms):
        self.sleeps += 1


def test_batch_path_skips_empty_names():
    page = _FakePage(
        batch=[
            {"mid": "m1", "name": "Family", "unread": "2", "preview": "hi", "time": "8:00"},
            {"mid": "m2", "name": "", "unread": "", "preview": "", "time": ""},
            {"mid": "m3", "name": "Work", "unread": "", "preview": "ok", "time": ""},
        ],
        counts=[3, 3, 3],
    )
    out = rooms.list_rooms(cast(Page, page), _settings(rooms_scroll_ms=0))
    assert [(r.index, r.id, r.name, r.unread) for r in out] == [
        (0, "m1", "Family", 2),
        (1, "m3", "Work", 0),
    ]


def test_fallback_when_batch_fails():
    rows = [_Row("m9", {"name": "Solo"})]
    page = _FakePage(rows=rows, fail_batch=True)
    # Locator fallback reads name/unread/preview/time per row; stub
    # text_content via _Text by patching _text to return canned values.
    calls = {"n": 0}

    def fake_text(locator, timeout: int = 500) -> str:  # type: ignore[no-redef]
        calls["n"] += 1
        return ["Solo", "", "", "", "Solo"][min(calls["n"] - 1, 4)]

    old = rooms._text
    rooms._text = fake_text  # type: ignore[assignment]
    try:
        out = rooms.list_rooms(cast(Page, page), _settings(rooms_scroll_ms=0))
    finally:
        rooms._text = old
    assert [r.name for r in out] == ["Solo"]


def test_scroll_disabled_makes_no_evaluate_calls():
    page = _FakePage(
        batch=[{"mid": "m1", "name": "A", "unread": "", "preview": "", "time": ""}],
    )
    rooms.list_rooms(cast(Page, page), _settings(rooms_scroll_ms=0))
    # One evaluate for the batch read only, none for scrolling.
    assert page.evals == 1
    assert page.sleeps == 0
