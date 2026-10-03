"""Fast room read: batch path, fallback, and bounded scroll (no browser)."""

from typing import cast

import pytest
from playwright.sync_api import Page

from line_ext_msg.config.selectors import SELECTORS
from line_ext_msg.domain.errors import ChatsViewMissing, RoomNotFound
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
    def __init__(self, mid, fields, can_open=True):
        self._mid = mid
        self._fields = fields
        self.can_open = can_open
        self.clicks = 0

    def locator(self, sel):
        self._sel = sel
        return self

    @property
    def first(self):
        return self

    def text_content(self, timeout=0):
        return self._fields.get("name", "")

    def get_attribute(self, name):
        return self._mid if name == "data-mid" else ""

    def click(self, timeout=0):
        self.clicks += 1
        if not self.can_open:
            raise RuntimeError("no Go chatroom button in this row")


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
    def __init__(self, batch=None, rows=None, counts=None, fail_batch=False,
                 no_selector=False):
        self._batch = batch
        self._rows = rows or []
        self._counts = list(counts or [])
        self.fail_batch = fail_batch
        self.no_selector = no_selector
        self.evals = 0
        self.sleeps = 0

    def wait_for_selector(self, _sel, timeout=0, state=None):
        if self.no_selector:
            raise RuntimeError("selector never matched")
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


def test_list_rooms_raises_when_the_chats_list_never_renders():
    """An empty list would read as an account with no rooms, so the wrong view
    has to be an error instead."""
    page = _FakePage(no_selector=True)
    with pytest.raises(ChatsViewMissing):
        rooms.list_rooms(cast(Page, page), _settings())


def test_room_selectors_do_not_fall_back_to_the_friends_list():
    """A union here is what let friend names be read as rooms."""
    for key in ("room_list", "room_item", "room_name", "room_unread", "room_preview"):
        assert "friendlist" not in SELECTORS[key], key


def test_open_room_finds_the_row_by_data_mid():
    rows = [_Row("m1", {"name": "Family"}), _Row("m2", {"name": "Work"})]
    page = _FakePage(rows=rows)
    found = [
        Room(index=0, id="m1", name="Family"),
        Room(index=1, id="m2", name="Work"),
    ]
    # index 0 would click the first row, so the click on m2 proves the lookup
    # used data-mid rather than the position.
    room = rooms.open_room(cast(Page, page), found[1], found, _settings())
    assert room.name == "Work"
    assert rows[0].clicks == 0
    assert rows[1].clicks == 1


def test_open_room_reports_a_row_without_the_chat_button():
    rows = [_Row("m1", {"name": "Family"}, can_open=False)]
    page = _FakePage(rows=rows)
    known = [Room(index=0, id="m1", name="Family")]
    with pytest.raises(RoomNotFound):
        rooms.open_room(cast(Page, page), known[0], known, _settings())


def test_open_room_refuses_a_position_fallback_when_the_id_is_known():
    """The row for a known data-mid is off-screen, so index 0 now holds a
    different conversation. Clicking it would read the wrong room silently."""
    rows = [_Row("mX", {"name": "Someone else"})]
    page = _FakePage(rows=rows)
    known = [Room(index=0, id="m1", name="Family")]
    with pytest.raises(RoomNotFound):
        rooms.open_room(cast(Page, page), known[0], known, _settings())
    assert rows[0].clicks == 0, "must not open a room just because it sits at that index"


def test_open_room_scrolls_the_list_when_the_id_is_not_rendered(monkeypatch):
    """The target is off-screen on the first look and the scroll brings it
    back, so the room opens instead of failing."""
    target = _Row("m1", {"name": "Family"})
    other = _Row("mX", {"name": "Someone else"})
    page = _FakePage(rows=[other])

    def fake_scroll(pg, _settings):
        pg._rows.append(target)

    monkeypatch.setattr(rooms, "_scroll_to_load", fake_scroll)
    known = [Room(index=0, id="m1", name="Family")]
    found = rooms.open_room(cast(Page, page), known[0], known, _settings())
    assert found.name == "Family"
    assert target.clicks == 1
    assert other.clicks == 0


def test_open_room_falls_back_to_position_without_an_id():
    """A row with no data-mid leaves the position as the only option, so the
    fallback has to stay for those."""
    rows = [_Row("m1", {"name": "Family"})]
    page = _FakePage(rows=rows)
    known = [Room(index=0, id="", name="Family")]
    rooms.open_room(cast(Page, page), known[0], known, _settings())
    assert rows[0].clicks == 1
