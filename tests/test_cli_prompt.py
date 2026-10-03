"""CLI prompts and display: ask_limit answers, full one-line text."""

from unittest.mock import patch

import pytest

from line_ext_msg.cli import _build_parser, _display, _oneline, ask_limit
from line_ext_msg.domain.models import Message


def test_empty_returns_default():
    with patch("builtins.input", return_value=""):
        assert ask_limit() == 5
        assert ask_limit(default=10) == 10


def test_number_returns_int():
    with patch("builtins.input", return_value="20"):
        assert ask_limit() == 20


def test_zero_means_all():
    with patch("builtins.input", return_value="0"):
        assert ask_limit() == 0


def test_invalid_retries():
    with patch("builtins.input", side_effect=["xx", "-5", "7"]):
        assert ask_limit() == 7


def _msg(text, type="text"):
    return Message(id="1", date="2026-09-12", ts="2026-09-12T07:12:28",
                   sender="May", from_me=False, type=type, text=text)


def test_oneline_joins_breaks():
    assert _oneline("@All\n\nhello") == "@All  hello"
    assert _oneline("a\r\nb") == "a b"
    assert _oneline("plain") == "plain"


def test_display_returns_full_text():
    long_text = "x" * 200
    assert _display(_msg(long_text)) == long_text


def test_display_joins_multiline():
    assert _display(_msg("@All\n\nhello")) == "@All  hello"


def test_subcommand_is_optional():
    """Every query flag must keep working without naming a subcommand."""
    assert _build_parser().parse_args([]).command is None


def test_query_flags_still_parse_without_a_subcommand():
    args = _build_parser().parse_args(["--unread", "--limit", "3"])
    assert args.command is None
    assert args.unread is True
    assert args.limit == 3


def test_logout_subcommand_with_yes():
    args = _build_parser().parse_args(["logout", "--yes"])
    assert args.command == "logout"
    assert args.yes is True


def test_logout_subcommand_asks_by_default():
    assert _build_parser().parse_args(["logout"]).yes is False


def test_clear_session_flag_is_gone():
    """The old flag was replaced by the subcommand and must not come back."""
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["--clear-session"])
