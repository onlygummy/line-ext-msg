"""System rows: clock prefix strip, stats exclusion, line prefix."""

from line_ext_msg.cli import _who
from line_ext_msg.domain.filters import sender_stats
from line_ext_msg.domain.models import Message
from line_ext_msg.scraper.extract import clean_system_text


def _msg(sender="A", type="text", text="hi"):
    return Message(id="1", date="2026-09-11", ts="2026-09-11T15:43:20",
                   sender=sender, from_me=False, type=type, text=text)


def test_strips_clock_prefix():
    assert clean_system_text("3:43 PMw.siri  joined the group.") == "w.siri  joined the group."
    assert clean_system_text("10:37 AMKannn  joined the group.") == "Kannn  joined the group."
    assert clean_system_text("8:05 hello") == "hello"


def test_leaves_normal_text_alone():
    assert clean_system_text("hello world") == "hello world"
    assert clean_system_text("") == ""


def test_stats_skips_system_rows():
    stats = sender_stats([_msg("A"), _msg("", "system", "x joined"), _msg("A")])
    assert stats == [{"sender": "A", "count": 2}]


def test_who_prefix():
    assert _who("May") == "May: "
    assert _who("") == ""
