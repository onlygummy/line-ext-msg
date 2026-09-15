"""Checklist logger counts steps and marks skips."""

import logging

from line_ext_msg.output.progress import Steps


def test_checklist_counts(caplog):
    caplog.set_level(logging.INFO, logger="line_ext_msg")
    steps = Steps(3)
    assert steps.check("a", True) is True
    assert steps.check("b", False, "hint") is False
    steps.skip_rest("stop")
    out = caplog.text
    assert "[1/3] a ... OK" in out
    assert "[2/3] b ... FAIL" in out
    assert "hint" in out
    assert "[3/3] skip (stop)" in out


def test_quiet_logs_nothing(caplog):
    caplog.set_level(logging.INFO, logger="line_ext_msg")
    steps = Steps(2, quiet=True)
    steps.check("a", True)
    steps.detail("d")
    steps.skip_rest()
    assert caplog.text == ""


def test_selectors_present():
    from line_ext_msg.config.selectors import SELECTORS
    for key in ("room_list", "room_item", "room_name", "room_open",
                "message_list", "message_item", "sender", "text", "time"):
        assert SELECTORS[key], key
