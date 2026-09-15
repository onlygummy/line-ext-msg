"""Headless is the default; headed is opt-in."""

import os

from line_ext_msg.config.settings import Settings


def test_headless_default_on():
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


def test_qr_zoom_default():
    old = os.environ.pop("LINE_EXT_MSG_QR_ZOOM", None)
    try:
        assert Settings().qr_zoom == 2
    finally:
        if old is not None:
            os.environ["LINE_EXT_MSG_QR_ZOOM"] = old


def test_qr_zoom_override():
    assert Settings(qr_zoom=3).qr_zoom == 3


def test_qr_ready_ms_default():
    old = os.environ.pop("LINE_EXT_MSG_QR_READY_MS", None)
    try:
        assert Settings().qr_ready_ms == 20000
    finally:
        if old is not None:
            os.environ["LINE_EXT_MSG_QR_READY_MS"] = old


def test_debug_qr_override():
    assert Settings(debug_qr=True).debug_qr is True


def test_dialog_title_default():
    old = os.environ.pop("LINE_EXT_MSG_DIALOG_TITLE", None)
    try:
        assert Settings().dialog_title == "LINE"
    finally:
        if old is not None:
            os.environ["LINE_EXT_MSG_DIALOG_TITLE"] = old


def test_dialog_title_env_override():
    old = os.environ.get("LINE_EXT_MSG_DIALOG_TITLE")
    os.environ["LINE_EXT_MSG_DIALOG_TITLE"] = "Inbox"
    try:
        assert Settings().dialog_title == "Inbox"
    finally:
        if old is None:
            del os.environ["LINE_EXT_MSG_DIALOG_TITLE"]
        else:
            os.environ["LINE_EXT_MSG_DIALOG_TITLE"] = old


def test_dialog_title_constructor_override():
    assert Settings(dialog_title="Inbox").dialog_title == "Inbox"
