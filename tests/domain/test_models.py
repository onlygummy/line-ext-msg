"""Models serialize to JSON; ref resolution needs no browser."""

from dataclasses import asdict

from line_ext_msg.domain.errors import RoomNotFound
from line_ext_msg.domain.models import Message, Room
from line_ext_msg.scraper.rooms import resolve_ref


def _rooms():
    return [
        Room(index=0, id="AAA", name="ครอบครัว", unread=3),
        Room(index=1, id="BBB", name="ที่ทำงาน"),
    ]


def test_room_asdict_json():
    import json
    raw = json.dumps(asdict(_rooms()[0]), ensure_ascii=False)
    assert "ครอบครัว" in raw


def test_message_defaults():
    m = Message(id="1", date="2026-09-12", ts="2026-09-12T08:13:00",
                sender="แม่", from_me=False, type="text", text="กินข้าวยัง")
    assert m.read_count is None
    assert asdict(m)["text"] == "กินข้าวยัง"


def test_resolve_by_index_id_name():
    rooms = _rooms()
    assert resolve_ref(1, rooms).name == "ที่ทำงาน"
    assert resolve_ref("AAA", rooms).name == "ครอบครัว"
    assert resolve_ref("ครอบครัว", rooms).id == "AAA"
    assert resolve_ref(rooms[0], rooms).name == "ครอบครัว"


def test_resolve_missing():
    try:
        resolve_ref("ไม่มีห้องนี้", _rooms())
    except RoomNotFound as e:
        assert "ไม่มีห้องนี้" in str(e)
        assert e.available == ["ครอบครัว", "ที่ทำงาน"]
    else:
        raise AssertionError("expected RoomNotFound")
