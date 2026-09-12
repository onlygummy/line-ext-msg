"""Filter + stats logic (pure, no browser)."""

from line_ext_msg.messages import apply_filters, sender_stats, to_data_uri
from line_ext_msg.models import Message


def _msgs():
    return [
        Message(id="1", date="2026-09-10", ts="2026-09-10T08:00:00",
                sender="แม่", from_me=False, type="text", text="กินข้าวยัง"),
        Message(id="2", date="2026-09-11", ts="2026-09-11T09:30:00",
                sender="พ่อ", from_me=False, type="text", text="ใบแจ้งหนี้มาแล้ว"),
        Message(id="3", date="2026-09-12", ts="2026-09-12T18:00:00",
                sender="", from_me=True, type="text", text="รับทราบครับ"),
        Message(id="4", date="2026-09-12", ts="2026-09-12T19:00:00",
                sender="แม่", from_me=False, type="sticker", text=""),
    ]


def test_date_range():
    out = apply_filters(_msgs(), date_from="2026-09-11", date_to="2026-09-12")
    assert [m.id for m in out] == ["2", "3", "4"]
    out = apply_filters(_msgs(), date="2026-09-12")
    assert [m.id for m in out] == ["3", "4"]


def test_time_range_skips_display_only():
    out = apply_filters(_msgs(), time_from="09:00", time_to="18:30")
    assert [m.id for m in out] == ["2", "3"]


def test_sender_and_keyword():
    assert [m.id for m in apply_filters(_msgs(), sender="แม่")] == ["1", "4"]
    assert [m.id for m in apply_filters(_msgs(), keyword="ใบแจ้งหนี้")] == ["2"]
    assert apply_filters(_msgs(), keyword="ไม่มีคำนี้") == []


def test_sender_stats():
    stats = sender_stats(_msgs())
    assert stats[0] == {"sender": "แม่", "count": 2}
    assert sum(s["count"] for s in stats) == 4


def test_to_data_uri():
    assert to_data_uri("image/png", "AAA") == "data:image/png;base64,AAA"
    assert to_data_uri("", "AAA") == ""
    assert to_data_uri("image/png", "") == ""
