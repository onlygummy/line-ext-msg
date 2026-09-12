"""Checklist printer counts steps and marks skips."""

from line_ext_msg.progress import Steps


def test_checklist_counts(capsys):
    steps = Steps(3)
    assert steps.check("a", True) is True
    assert steps.check("b", False, "hint") is False
    steps.skip_rest("stop")
    out = capsys.readouterr().out
    assert "[1/3] a ... ผ่าน" in out
    assert "[2/3] b ... ไม่ผ่าน" in out
    assert "hint" in out
    assert "[3/3] ข้าม (stop)" in out


def test_quiet_prints_nothing(capsys):
    steps = Steps(2, quiet=True)
    steps.check("a", True)
    steps.detail("d")
    steps.skip_rest()
    assert capsys.readouterr().out == ""


def test_selectors_present():
    from line_ext_msg.settings import SELECTORS
    for key in ("room_list", "room_item", "room_name", "room_open",
                "message_list", "message_item", "sender", "text", "time"):
        assert SELECTORS[key], key
