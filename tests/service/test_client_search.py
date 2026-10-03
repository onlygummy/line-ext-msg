"""LineClient search reporting: a partial scan is never a silent miss."""

from line_ext_msg import LineClient
from line_ext_msg.domain.models import Message, Room
from line_ext_msg.results import Messages
from line_ext_msg.scraper import rooms as rooms_scraper


def _msg(mid):
    return Message(id=mid, date="2026-09-12", ts="2026-09-12T07:12:28",
                   sender="May", from_me=False, type="text", text="hi")


def _stub_client(monkeypatch, behaviour):
    """LineClient with the browser parts stubbed.

    behaviour maps a room name to (stop reason, match count), so each room can
    finish differently.
    """
    client = LineClient(quiet=True)
    known = [Room(index=0, id="m1", name="Family"), Room(index=1, id="m2", name="Work")]
    current = {}

    def fake_open_room(_page, ref, _rooms, _settings):
        current["room"] = ref
        return ref

    def fake_get_messages(limit=5, **_kwargs):
        name = current["room"].name
        stop, hits = behaviour[name]
        out = Messages(_msg(f"{name}-{i}") for i in range(hits))
        out.scroll_stop = stop
        return out

    client.list_rooms = lambda **_kwargs: list(known)
    client._ready_page = lambda: object()
    client.get_messages = fake_get_messages
    monkeypatch.setattr(rooms_scraper, "open_room", fake_open_room)
    return client


def test_complete_rooms_are_reported_without_truncated(monkeypatch):
    client = _stub_client(monkeypatch, {
        "Family": ("top", 1),
        "Work": ("need", 1),
    })
    report = client.search_all("invoice")
    assert [hit["room"]["name"] for hit in report] == ["Family", "Work"]
    assert [hit["truncated"] for hit in report] == [False, False]


def test_rooms_without_matches_are_left_out_when_the_scan_was_complete(monkeypatch):
    client = _stub_client(monkeypatch, {
        "Family": ("top", 1),
        "Work": ("top", 0),
    })
    assert [hit["room"]["name"] for hit in client.search_all("invoice")] == ["Family"]


def test_partial_room_is_reported_even_with_no_match(monkeypatch):
    """The dangerous case: the scan stopped early, so "no match" is unknown."""
    client = _stub_client(monkeypatch, {
        "Family": ("top", 1),
        "Work": ("budget", 0),
    })
    report = client.search_all("invoice")
    assert [hit["room"]["name"] for hit in report] == ["Family", "Work"]
    assert report[1]["messages"] == []
    assert report[1]["truncated"] is True


def test_partial_room_with_matches_is_flagged(monkeypatch):
    client = _stub_client(monkeypatch, {
        "Family": ("budget", 2),
        "Work": ("top", 0),
    })
    report = client.search_all("invoice")
    assert [(hit["room"]["name"], hit["truncated"]) for hit in report] == [("Family", True)]


def test_a_room_stopped_by_a_detached_page_is_not_truncated(monkeypatch):
    """Only the time budget means partial rows; a detached page is a hard stop."""
    client = _stub_client(monkeypatch, {
        "Family": ("detached", 0),
        "Work": ("top", 0),
    })
    assert list(client.search_all("invoice")) == []


def test_unread_full_flags_a_partial_day(monkeypatch):
    client = _stub_client(monkeypatch, {
        "Family": ("budget", 3),
        "Work": ("need", 1),
    })
    monkeypatch.setattr(client, "list_rooms", lambda **_k: [Room(index=0, id="m1", name="Family")])
    report = client.unread_full(date="2026-09-12")
    assert [(hit["truncated"], len(hit["messages"])) for hit in report] == [(True, 3)]