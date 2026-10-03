"""The callback trust boundary: a host bug must not break the library."""

import logging

from line_ext_msg.domain.callbacks import call_callback


def test_no_callback_counts_as_continue():
    assert call_callback(None, "x", what="qr") is True


def test_a_return_value_of_none_continues():
    """Hosts commonly write a bare print or queue.put, which returns None."""
    assert call_callback(lambda value: None, "x", what="qr") is True


def test_returning_true_continues():
    assert call_callback(lambda value: True, "x", what="qr") is True


def test_returning_false_cancels():
    assert call_callback(lambda value: False, "x", what="qr") is False


def test_a_raising_callback_is_logged_and_ignored(caplog):
    def boom(value):
        raise RuntimeError("host is down")

    with caplog.at_level(logging.WARNING):
        assert call_callback(boom, "x", what="qr") is True
    assert "host is down" in caplog.text
    assert "qr" in caplog.text


def test_arguments_are_forwarded_in_order():
    seen: list = []
    call_callback(lambda pin, desc: seen.append((pin, desc)), "5239", "type it",
                  what="pin")
    assert seen == [("5239", "type it")]