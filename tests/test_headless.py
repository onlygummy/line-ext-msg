"""Headless is the default; headed is opt-in."""

import os

from line_ext_msg.settings import Settings


def test_headless_default_on():
    env = {k: v for k, v in os.environ.items() if k != "LINE_EXT_MSG_HEADLESS"}
    old = os.environ.pop("LINE_EXT_MSG_HEADLESS", None)
    try:
        assert Settings().headless is True
    finally:
        if old is not None:
            os.environ["LINE_EXT_MSG_HEADLESS"] = old


def test_headless_env_off():
    old = os.environ.get("LINE_EXT_MSG_HEADLESS")
    os.environ["LINE_EXT_MSG_HEADLESS"] = "0"
    try:
        assert Settings().headless is False
    finally:
        if old is None:
            del os.environ["LINE_EXT_MSG_HEADLESS"]
        else:
            os.environ["LINE_EXT_MSG_HEADLESS"] = old


def test_headless_override():
    assert Settings(headless=False).headless is False
