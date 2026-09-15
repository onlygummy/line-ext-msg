"""Result containers save themselves and write media on request."""

import base64
import json
import os

from line_ext_msg.domain.models import Message, Room
from line_ext_msg.results import Dom, Messages, Probe, Report, Rooms


def _room():
    return Room(index=0, id="AAA", name="Family", unread=1)


def _image(msg_id="img1", data=b"hi"):
    uri = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
    return Message(id=msg_id, date="2026-09-12", ts="2026-09-12T08:13:00",
                   sender="", from_me=True, type="image", text="", media_data=uri)


def test_rooms_is_a_list_and_saves(tmp_path):
    rooms = Rooms([_room()])
    assert isinstance(rooms, list)
    path = rooms.save(str(tmp_path / "rooms.json"))
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["rooms"][0]["name"] == "Family"


def test_messages_save_with_room(tmp_path):
    msgs = Messages([_image()])
    msgs.room = _room()
    path = msgs.save(str(tmp_path / "messages.json"))
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["room"]["name"] == "Family"
    assert "fetched_at" in data
    assert data["messages"][0]["id"] == "img1"


def test_messages_save_without_room(tmp_path):
    path = Messages([_image()]).save(str(tmp_path / "messages.json"))
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert "room" not in data
    assert data["messages"][0]["id"] == "img1"


def test_download_media_writes_file_and_clears_data(tmp_path):
    msgs = Messages([_image()])
    msgs.room = _room()
    out = msgs.download_media(str(tmp_path))
    assert out.room is _room() or out.room is msgs.room
    assert out[0].media.endswith(".png")
    assert out[0].media_data == ""
    assert os.path.exists(out[0].media)


def test_download_media_keeps_data_when_asked(tmp_path):
    out = Messages([_image()]).download_media(str(tmp_path), include_data=True)
    assert out[0].media_data.startswith("data:image/png")


def test_download_media_skips_non_images(tmp_path):
    text = Message(id="t1", date="2026-09-12", ts="2026-09-12T08:00:00",
                   sender="Mom", from_me=False, type="text", text="hi")
    out = Messages([text]).download_media(str(tmp_path))
    assert out[0] is text
    assert out[0].media == ""


def test_report_and_probe_save(tmp_path):
    report = Report([{"room": "Family"}])
    report_path = report.save(str(tmp_path / "report.json"))
    with open(report_path, encoding="utf-8") as f:
        assert json.load(f) == [{"room": "Family"}]

    probe = Probe({"logged_in": True})
    probe_path = probe.save(str(tmp_path / "probe.json"))
    with open(probe_path, encoding="utf-8") as f:
        assert json.load(f) == {"logged_in": True}


def test_dom_saves_and_carries_room_and_state(tmp_path):
    dom = Dom("<html></html>", room=_room(), state="ready")
    assert dom.room is not None
    assert dom.room.name == "Family"
    assert dom.state == "ready"
    path = dom.save(str(tmp_path / "page.html"))
    assert open(path, encoding="utf-8").read() == "<html></html>"
