"""Models serialize to JSON; ref resolution needs no browser."""

from dataclasses import asdict

import pytest

from line_ext_msg.domain.errors import RoomNotFound
from line_ext_msg.domain.models import Message, Room
from line_ext_msg.scraper.rooms import resolve_ref


def _rooms():
    return [
        Room(index=0, id="AAA", name="Family", unread=3),
        Room(index=1, id="BBB", name="Work"),
    ]


def test_room_asdict_json():
    import json
    raw = json.dumps(asdict(_rooms()[0]), ensure_ascii=False)
    assert "Family" in raw


def test_message_defaults():
    m = Message(id="1", date="2026-09-12", ts="2026-09-12T08:13:00",
                sender="Mom", from_me=False, type="text", text="have you eaten")
    assert m.read_count is None
    assert asdict(m)["text"] == "have you eaten"


def test_resolve_by_index_id_name():
    rooms = _rooms()
    assert resolve_ref(1, rooms).name == "Work"
    assert resolve_ref("AAA", rooms).name == "Family"
    assert resolve_ref("Family", rooms).id == "AAA"
    assert resolve_ref(rooms[0], rooms).name == "Family"


def test_resolve_missing():
    with pytest.raises(RoomNotFound) as exc:
        resolve_ref("missing", _rooms())
    assert "missing" in str(exc.value)
    assert exc.value.available == ["Family", "Work"]
