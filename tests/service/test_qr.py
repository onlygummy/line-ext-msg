"""QR dialog controller: data URI decoding and shared-file lifecycle."""

import base64
import json
import os

import pytest

from line_ext_msg.domain.errors import QrDialogFailed
from line_ext_msg.service import qr


def _png_uri(payload: bytes = b"abc") -> str:
    return "data:image/png;base64," + base64.b64encode(payload).decode("ascii")


def test_data_uri_to_bytes_roundtrip():
    assert qr.data_uri_to_bytes(_png_uri(b"hello")) == b"hello"


def test_data_uri_to_bytes_empty_and_bad():
    assert qr.data_uri_to_bytes("") == b""
    assert qr.data_uri_to_bytes("not-a-data-uri") == b""
    assert qr.data_uri_to_bytes("data:image/png;base64,!!!!") == b""


def test_update_writes_png_once_per_uri(tmp_path):
    png = str(tmp_path / "qr.png")
    dialog = qr.QrDialog(png=png, status=str(tmp_path / "status.json"))
    assert dialog.update(_png_uri(b"first")) is True
    assert open(png, "rb").read() == b"first"
    # Same data URI: no rewrite.
    assert dialog.update(_png_uri(b"first")) is False
    assert dialog.update(_png_uri(b"second")) is True
    assert open(png, "rb").read() == b"second"


def test_update_ignores_empty_data(tmp_path):
    png = str(tmp_path / "qr.png")
    dialog = qr.QrDialog(png=png, status=str(tmp_path / "status.json"))
    assert dialog.update("") is False
    assert not os.path.exists(png)


def test_finish_removes_files(tmp_path):
    png = str(tmp_path / "qr.png")
    status = str(tmp_path / "status.json")
    dialog = qr.QrDialog(png=png, status=status)
    dialog.update(_png_uri())
    with open(status, "w", encoding="utf-8") as f:
        json.dump({"state": "waiting"}, f)
    dialog.finish("done")
    assert not os.path.exists(png)
    assert not os.path.exists(status)


def test_finish_keeps_png_on_request(tmp_path):
    png = str(tmp_path / "qr.png")
    status = str(tmp_path / "status.json")
    dialog = qr.QrDialog(png=png, status=status)
    dialog.update(_png_uri())
    dialog.finish("cancel", keep_png=True)
    assert os.path.exists(png)
    assert not os.path.exists(status)


def test_open_raises_when_spawn_fails(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise OSError("no process")

    monkeypatch.setattr(qr.subprocess, "Popen", boom)
    dialog = qr.QrDialog(png=str(tmp_path / "qr.png"), status=str(tmp_path / "status.json"))
    with pytest.raises(QrDialogFailed):
        dialog.open(_png_uri())
    # The PNG is kept so the user can still open it by hand.
    assert os.path.exists(dialog.png)


def test_set_pin_writes_status(tmp_path):
    status = str(tmp_path / "status.json")
    dialog = qr.QrDialog(png=str(tmp_path / "qr.png"), status=status)
    dialog.set_pin("5239", "enter on phone")
    with open(status, encoding="utf-8") as f:
        data = json.load(f)
    assert data == {"state": "waiting", "pin": "5239", "desc": "enter on phone"}


def test_clamp_zoom_bounds():
    assert qr.clamp_zoom(2) == 2
    assert qr.clamp_zoom(0) == qr.MIN_ZOOM
    assert qr.clamp_zoom(9) == qr.MAX_ZOOM
    assert qr.clamp_zoom("bad") == 2


def test_format_pin_spaces_digits():
    assert qr.format_pin("5239") == "5 2 3 9"
    assert qr.format_pin(" 5239 ") == "5 2 3 9"


def test_format_pin_short_or_empty():
    assert qr.format_pin("") == ""
    assert qr.format_pin("5") == "5"


def test_center_xy_grid():
    assert qr.center_xy(400, 200, 1000, 800) == (300, 270)
    assert qr.center_xy(1000, 800, 1000, 800) == (0, 0)
    assert qr.center_xy(2000, 100, 1000, 800) == (0, 315)


def test_open_passes_zoom_to_viewer(tmp_path, monkeypatch):
    captured = {}

    class _Proc:
        def poll(self):
            return 0

    def fake_popen(args, **_k):
        captured["args"] = args
        return _Proc()

    monkeypatch.setattr(qr.subprocess, "Popen", fake_popen)
    dialog = qr.QrDialog(png=str(tmp_path / "qr.png"), status=str(tmp_path / "status.json"),
                         zoom=3)
    dialog.open(_png_uri())
    assert "--zoom" in captured["args"]
    assert captured["args"][captured["args"].index("--zoom") + 1] == "3"
