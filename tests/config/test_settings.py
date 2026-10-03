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


def test_qr_zoom_in_range_is_left_alone():
    for zoom in (1, 2, 3, 4):
        assert Settings(qr_zoom=zoom).qr_zoom == zoom


def test_qr_zoom_below_range_is_clamped_up():
    """Tk's PhotoImage.zoom rejects these, and the viewer process runs with
    stderr discarded, so an unclamped value would be a blank silent dialog."""
    assert Settings(qr_zoom=0).qr_zoom == 1
    assert Settings(qr_zoom=-3).qr_zoom == 1


def test_qr_zoom_above_range_is_clamped_down():
    assert Settings(qr_zoom=99).qr_zoom == 4


def test_scroll_cap_default_is_five_minutes():
    """The value the code used to hardcode in two places."""
    old = os.environ.pop("LINE_EXT_MSG_SCROLL_CAP_MS", None)
    try:
        assert Settings().scroll_cap_ms == 300000
    finally:
        if old is not None:
            os.environ["LINE_EXT_MSG_SCROLL_CAP_MS"] = old


def test_scroll_cap_env_override():
    old = os.environ.get("LINE_EXT_MSG_SCROLL_CAP_MS")
    os.environ["LINE_EXT_MSG_SCROLL_CAP_MS"] = "900000"
    try:
        assert Settings().scroll_cap_ms == 900000
    finally:
        if old is None:
            del os.environ["LINE_EXT_MSG_SCROLL_CAP_MS"]
        else:
            os.environ["LINE_EXT_MSG_SCROLL_CAP_MS"] = old
