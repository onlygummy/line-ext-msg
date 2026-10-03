"""Fast room read: batch path, fallback, and bounded scroll (no browser)."""

from typing import cast

import pytest
from playwright.sync_api import Page

from line_ext_msg.domain.errors import RoomNotFound
from line_ext_msg.domain.models import Room
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
    def __init__(self, rows, counts=None):
        self._rows = rows
        # Shared with the page on purpose: each count() consumes one value, so
        # the sequence spans calls instead of restarting per locator.
        self._counts = counts if counts is not None else []

    def count(self):
        # A scripted sequence lets a test drive the scroll stability loop;
        # without one the count is just the number of rendered rows.
        if self._counts:
            return self._counts.pop(0)
        return len(self._rows)

    def nth(self, i):
        return self._rows[i]


class _FakePage:
    def __init__(self, batch=None, rows=None, counts=None, fail_batch=False):
        self._batch = batch
        self._rows = rows or []
        self._counts = list(counts or [])
        self.fail_batch = fail_batch
        self.evals = 0
        self.sleeps = 0

    def wait_for_selector(self, _sel, timeout=0, state=None):
        return True

    def locator(self, _sel):
        return _Items(self._rows, self._counts)

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
    )
    out = rooms.list_rooms(cast(Page, page), _settings(rooms_scroll_ms=0))
    assert [(r.index, r.id, r.name, r.unread) for r in out] == [
        (0, "m1", "Family", 2),
        (1, "m3", "Work", 0),
    ]


def test_fallback_when_batch_fails(monkeypatch):
    rows = [_Row("m9", {"name": "Solo"})]
    page = _FakePage(rows=rows, fail_batch=True)
    # Locator fallback reads name/unread/preview/time per row; stub
    # text_content via _Text by patching _text to return canned values.
    calls = {"n": 0}

    def fake_text(locator, timeout: int = 500) -> str:
        calls["n"] += 1
        return ["Solo", "", "", "", "Solo"][min(calls["n"] - 1, 4)]

    monkeypatch.setattr(rooms, "_text", fake_text)
    out = rooms.list_rooms(cast(Page, page), _settings(rooms_scroll_ms=0))
    assert [r.name for r in out] == ["Solo"]


def test_scroll_disabled_makes_no_evaluate_calls():
    page = _FakePage(
        batch=[{"mid": "m1", "name": "A", "unread": "", "preview": "", "time": ""}],
    )
    rooms.list_rooms(cast(Page, page), _settings(rooms_scroll_ms=0))
    # One evaluate for the batch read only, none for scrolling.
    assert page.evals == 1
    assert page.sleeps == 0


def test_resolve_ref_case_insensitive():
    """Case-insensitive substring match finds rooms regardless of case."""
    room_list = [
        Room(index=0, id="m1", name="Family Group"),
        Room(index=1, id="m2", name="Work Team"),
    ]
    # Lowercase query matches mixed-case room name
    result = rooms.resolve_ref("family", room_list)
    assert result.name == "Family Group"
    # Uppercase query matches lowercase room name
    result = rooms.resolve_ref("WORK", room_list)
    assert result.name == "Work Team"


def test_resolve_ref_contains_all_words():
    """Multi-word query matches when all words are present in the room name."""
    room_list = [
        Room(index=0, id="m1", name="Family Group Chat"),
        Room(index=1, id="m2", name="Work Team"),
    ]
    # Both words present in the room name
    result = rooms.resolve_ref("Family Chat", room_list)
    assert result.name == "Family Group Chat"


def test_resolve_ref_exact_mid():
    """Exact data-mid match takes priority over name matching."""
    room_list = [
        Room(index=0, id="m1", name="Family"),
        Room(index=1, id="m2", name="Work"),
    ]
    result = rooms.resolve_ref("m2", room_list)
    assert result.name == "Work"


def test_resolve_ref_tolerates_surrounding_whitespace():
    room_list = [Room(index=0, id="m1", name="Family")]
    assert rooms.resolve_ref("  family  ", room_list).name == "Family"


@pytest.mark.parametrize("blank", ["", "   "])
def test_resolve_ref_rejects_a_blank_name(blank):
    """A blank ref must raise instead of matching an arbitrary room."""
    room_list = [
        Room(index=0, id="m1", name="Family"),
        Room(index=1, id="m2", name="Work"),
    ]
    with pytest.raises(RoomNotFound):
        rooms.resolve_ref(blank, room_list)


def test_resolve_ref_not_found():
    """RoomNotFound is raised when no match is found."""
    room_list = [
        Room(index=0, id="m1", name="Family"),
    ]
    with pytest.raises(RoomNotFound) as err:
        rooms.resolve_ref("NonExistent", room_list)
    assert "NonExistent" in str(err.value)
    assert "Family" in err.value.available


def test_scroll_stops_after_three_stable_rounds():
    """The count grows once, then holds: the loop must not stop on the first
    stable pair, and must stop once three rounds in a row show no change."""
    page = _FakePage(
        batch=[{"mid": "m1", "name": "A", "unread": "", "preview": "", "time": ""}],
        rows=[_Row("m1", {"name": "A"})],
        counts=[5, 7, 7, 7, 7],
    )
    rooms.list_rooms(cast(Page, page), _settings(rooms_scroll_ms=8000))
    # Four scroll rounds (the first one sees the growth) plus the batch read.
    assert page.evals == 5
    assert page.sleeps == 4


def test_scroll_stops_on_the_budget_when_counts_keep_growing():
    """A list that never settles is bounded by the time budget, not by
    stability, so a growing room list cannot spin forever."""
    page = _FakePage(
        batch=[{"mid": "m1", "name": "A", "unread": "", "preview": "", "time": ""}],
        rows=[_Row("m1", {"name": "A"})],
        counts=list(range(5, 40)),
    )
    rooms.list_rooms(cast(Page, page), _settings(rooms_scroll_ms=800))
    # 800ms budget at a 400ms step: one initial count plus two rounds.
    assert page.sleeps == 2
    assert page.evals == 3
