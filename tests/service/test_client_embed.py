"""The embedder-facing surface: login policy, callbacks, progress, alias."""

import logging

from line_ext_msg import LineClient
from line_ext_msg.domain.models import Message, Room
from line_ext_msg.results import Messages
from line_ext_msg.scraper import rooms as rooms_scraper
from line_ext_msg.service import readiness


def _msg(mid):
    return Message(id=mid, date="2026-09-12", ts="2026-09-12T07:12:28",
                   sender="May", from_me=False, type="text", text="hi")


def _stub_client(monkeypatch, behaviour, unread=None):
    """LineClient with the browser parts stubbed; behaviour maps room name to
    (stop reason, match count)."""
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

    client.list_rooms = lambda **_kwargs: list(unread if unread is not None else known)
    client._ready_page = lambda: object()
    client.get_messages = fake_get_messages
    monkeypatch.setattr(rooms_scraper, "open_room", fake_open_room)
    return client


def _capture_wait(monkeypatch):
    """Record the wait_for_login value status() forwards to readiness.run."""
    seen: list = []

    def fake_run(client, wait=None, timeout_ms=None):
        seen.append((wait, timeout_ms))
        # The real run() populates the page; without it _ready_page() cannot
        # hand one back to the query that triggered it.
        client._page = object()
        return []

    monkeypatch.setattr(readiness, "run", fake_run)
    monkeypatch.setattr(rooms_scraper, "list_rooms", lambda page, settings: [])
    return seen


def test_wait_policy_is_stored_on_the_instance():
    assert LineClient(quiet=True, wait_for_login=False)._wait_policy is False
    assert LineClient(quiet=True)._wait_policy is None


def test_instance_policy_reaches_status(monkeypatch):
    """A caller that never passes the flag still gets the policy it set once."""
    seen = _capture_wait(monkeypatch)
    LineClient(quiet=True, wait_for_login=False).status()
    # A query that triggers status() itself, without the caller ever naming
    # the policy: this is the path that used to have no way out.
    LineClient(quiet=True, wait_for_login=False).list_rooms()
    assert seen == [(False, None), (False, None)]


def test_a_query_does_not_rerun_status_when_the_page_is_ready(monkeypatch):
    """status() runs once per client; later queries reuse the session."""
    seen = _capture_wait(monkeypatch)
    client = LineClient(quiet=True, wait_for_login=False)
    client.status()
    client.list_rooms()
    client.list_rooms()
    assert seen == [(False, None)]


def test_explicit_argument_beats_the_instance_policy(monkeypatch):
    seen = _capture_wait(monkeypatch)
    client = LineClient(quiet=True, wait_for_login=False)
    client.status(wait_for_login=True)
    assert seen == [(True, None)]


def test_status_still_forwards_the_login_timeout(monkeypatch):
    seen = _capture_wait(monkeypatch)
    LineClient(quiet=True).status(login_timeout_ms=180000)
    assert seen == [(None, 180000)]


def test_search_all_reports_progress_per_room(monkeypatch):
    client = _stub_client(monkeypatch, {
        "Family": ("top", 2),
        "Work": ("budget", 0),
    })
    ticks: list = []
    client.search_all("invoice", on_progress=ticks.append)
    assert [(t.index, t.total, t.room.name, t.matched, t.truncated) for t in ticks] == [
        (1, 2, "Family", 2, False),
        (2, 2, "Work", 0, True),
    ]


def test_progress_covers_truncated_rooms_left_out_of_the_report(monkeypatch):
    """The dangerous case is a partial scan with no match, which the report
    still lists but a progress-only consumer would never see otherwise."""
    client = _stub_client(monkeypatch, {
        "Family": ("top", 1),
        "Work": ("budget", 0),
    })
    ticks: list = []
    report = client.search_all("invoice", on_progress=ticks.append)
    assert [hit["room"]["name"] for hit in report] == ["Family", "Work"]
    assert [(t.room.name, t.truncated) for t in ticks] == [("Family", False), ("Work", True)]


def test_unread_full_reports_progress(monkeypatch):
    client = _stub_client(monkeypatch, {"Family": ("budget", 3)},
                          unread=[Room(index=0, id="m1", name="Family")])
    ticks: list = []
    client.unread_full(date="2026-09-12", on_progress=ticks.append)
    assert [(t.index, t.total, t.room.name, t.matched, t.truncated) for t in ticks] == [
        (1, 1, "Family", 3, True),
    ]


def test_a_raising_progress_callback_does_not_abort_the_scan(monkeypatch):
    """The host's UI code must not be able to lose the report."""
    def boom(_tick):
        raise RuntimeError("host is down")

    client = _stub_client(monkeypatch, {"Family": ("top", 1), "Work": ("top", 1)})
    report = client.search_all("invoice", on_progress=boom)
    assert [hit["room"]["name"] for hit in report] == ["Family", "Work"]


def test_progress_is_optional(monkeypatch):
    client = _stub_client(monkeypatch, {"Family": ("top", 1), "Work": ("top", 0)})
    assert len(client.search_all("invoice")) == 1


def test_clear_session_delegates_to_logout(monkeypatch):
    client = LineClient(quiet=True)
    seen: list = []
    monkeypatch.setattr(client, "logout",
                        lambda backup=True: seen.append(backup) or {"wiped": ["Local Storage"]})
    assert client.clear_session() == {"wiped": ["Local Storage"]}
    assert seen == [True]


def test_clear_session_warns_and_forwards_backup(monkeypatch, caplog):
    client = LineClient(quiet=True)
    seen: list = []
    monkeypatch.setattr(client, "logout", lambda backup=True: seen.append(backup))
    with caplog.at_level(logging.WARNING):
        client.clear_session(backup=False)
    assert seen == [False]
    assert "clear_session" in caplog.text