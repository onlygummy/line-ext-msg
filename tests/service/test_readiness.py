"""Headless QR login flow decisions (no browser, no real Tk)."""

import pytest

from line_ext_msg.domain.errors import QrDialogFailed
from line_ext_msg.service import readiness
from tests.helpers import make_settings

_URI = "data:image/png;base64,QUJD"


class _Page:
    def __init__(self, qr_uri=_URI, reload_uri=None):
        self.qr_uri = qr_uri
        self.reload_uri = reload_uri
        self.gotos = 0

    def evaluate(self, _js, _arg=None):
        return self.qr_uri

    def wait_for_timeout(self, _ms):
        pass

    def goto(self, _url, timeout=0):
        self.gotos += 1
        if self.reload_uri is not None:
            self.qr_uri = self.reload_uri


class _BoomPage(_Page):
    def evaluate(self, _js, _arg=None):
        raise RuntimeError("boom")


class _DebugPage(_Page):
    def evaluate(self, _js, _arg=None):
        return {"hasQrRoot": True, "qrCalvases": [[200, 200]], "qrDataLen": 5000}


class _PinPage(_Page):
    def evaluate(self, _js, _arg=None):
        return {"pin": "5239", "desc": "enter on phone"}


class _BadPayloadPage(_Page):
    def evaluate(self, _js, _arg=None):
        return "nope"


class _Dialog:
    """Replaces readiness.qr.QrDialog; records the lifecycle calls."""

    instances: list = []

    def __init__(self, png="session/qr.png", status="session/qr_status.json", zoom=2):
        self.png = png
        self.status = status
        self.zoom = zoom
        self.opened = None
        self.updated = []
        self.qr_shows = []
        self.pins = []
        self.finished = None
        self._alive = True
        _Dialog.instances.append(self)

    def open(self, data_uri):
        self.opened = data_uri

    def show_qr(self, data_uri):
        self.qr_shows.append(data_uri)
        self.updated.append(data_uri)

    def update(self, data_uri):
        self.updated.append(data_uri)
        return True

    def set_pin(self, pin, desc=""):
        self.pins.append((pin, desc))

    def alive(self):
        return self._alive

    def finish(self, state="cancel", keep_png=False):
        self.finished = (state, keep_png)


class _Client:
    def __init__(self, page, settings):
        self._page = page
        self.settings = settings
        self._context = None
        self._browser = None


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch):
    _Dialog.instances = []
    monkeypatch.setattr(readiness.qr, "QrDialog", _Dialog)
    # The reload path calls into the real readiness probe; stub it out.
    monkeypatch.setattr(readiness.session, "wait_ready", lambda page, settings: "ready")
    monkeypatch.setattr(readiness.session, "close_startup_tabs", lambda settings: None)
    monkeypatch.setattr(readiness.session, "close_extension_tabs", lambda settings: None)
    monkeypatch.setattr(readiness.time, "sleep", lambda _s: None)
    yield


def test_qr_data_returns_string():
    assert readiness._qr_data(_Page()) == _URI


def test_qr_data_empty_on_non_string():
    assert readiness._qr_data(_Page(qr_uri=123)) == ""


def test_qr_data_empty_on_error():
    assert readiness._qr_data(_BoomPage()) == ""


def test_qr_debug_returns_dict():
    info = readiness._qr_debug(_DebugPage())
    assert info.get("hasQrRoot") is True


def test_qr_debug_empty_on_bad_payload():
    assert readiness._qr_debug(_Page()) == {}


def test_login_pin_reads_fields():
    assert readiness._login_pin(_PinPage()) == ("5239", "enter on phone")


def test_login_pin_empty_on_bad_payload():
    assert readiness._login_pin(_BadPayloadPage()) == ("", "")


def test_qr_login_keeps_pin_until_done(monkeypatch):
    pins = {"n": 0}

    def fake_pin(page):
        pins["n"] += 1
        return ("5239", "d") if pins["n"] <= 2 else ("", "")

    monkeypatch.setattr(readiness, "_login_pin", fake_pin)
    monkeypatch.setattr(readiness, "_qr_data", lambda page: _URI)  # unchanged QR
    checks = {"n": 0}

    def fake_check(page, timeout_ms=0):
        checks["n"] += 1
        return (checks["n"] >= 4, "chat")

    monkeypatch.setattr(readiness.auth, "check_login", fake_check)
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "ok"
    dialog = _Dialog.instances[-1]
    assert ("5239", "d") in dialog.pins
    assert dialog.pins[-1] == ("5239", "d")  # never cleared
    assert dialog.qr_shows == []  # never flashed back to QR


def test_qr_login_returns_to_qr_on_new_uri(monkeypatch):
    pins = {"n": 0}

    def fake_pin(page):
        pins["n"] += 1
        return ("5239", "d") if pins["n"] == 1 else ("", "")

    monkeypatch.setattr(readiness, "_login_pin", fake_pin)
    uris = {"n": 0}

    def fake_qr(page):
        uris["n"] += 1
        return _URI if uris["n"] == 1 else "data:image/png;base64,TkVX"

    monkeypatch.setattr(readiness, "_qr_data", fake_qr)
    checks = {"n": 0}

    def fake_check(page, timeout_ms=0):
        checks["n"] += 1
        return (checks["n"] >= 3, "chat")

    monkeypatch.setattr(readiness.auth, "check_login", fake_check)
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "ok"
    assert _Dialog.instances[-1].qr_shows == ["data:image/png;base64,TkVX"]


def test_qr_login_passes_pin_to_dialog(monkeypatch):
    calls = {"n": 0}

    def fake_pin(page):
        calls["n"] += 1
        if calls["n"] >= 2:
            return ("5239", "enter on phone")
        return ("", "")

    monkeypatch.setattr(readiness, "_login_pin", fake_pin)
    monkeypatch.setattr(readiness.auth, "check_login",
                        lambda page, timeout_ms=0: (calls["n"] >= 3, "chat"))
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "ok"
    assert ("5239", "enter on phone") in _Dialog.instances[-1].pins


def test_wait_for_qr_returns_uri():
    assert readiness._wait_for_qr(_Page(), timeout_ms=0) == _URI


def test_wait_for_qr_empty_on_timeout():
    assert readiness._wait_for_qr(_Page(qr_uri=""), timeout_ms=0) == ""


def test_qr_login_ok_when_login_succeeds(monkeypatch):
    monkeypatch.setattr(readiness.auth, "check_login", lambda page, timeout_ms=0: (True, "chat"))
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "ok"
    assert _Dialog.instances[-1].opened == _URI
    assert _Dialog.instances[-1].finished == ("done", False)


def test_qr_login_waits_until_login(monkeypatch):
    calls = {"n": 0}

    def slow_login(page, timeout_ms=0):
        calls["n"] += 1
        return (calls["n"] >= 3, "chat")

    monkeypatch.setattr(readiness.auth, "check_login", slow_login)
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "ok"
    assert calls["n"] == 3


def test_qr_login_cancel_when_dialog_closed(monkeypatch):
    monkeypatch.setattr(readiness.auth, "check_login", lambda page, timeout_ms=0: (False, "login"))

    def dead(self):
        self._alive = False
        return False

    monkeypatch.setattr(_Dialog, "alive", dead)
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "cancel"
    assert _Dialog.instances[-1].finished == ("cancel", False)


def test_qr_login_refreshes_changed_qr(monkeypatch):
    monkeypatch.setattr(readiness.auth, "check_login", lambda page, timeout_ms=0: (True, "chat"))
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "ok"
    assert _Dialog.instances[-1].updated == []


def test_qr_login_falls_back_without_data_and_reloads():
    page = _Page(qr_uri="")
    client = _Client(page, make_settings(qr_ready_ms=0))
    assert readiness._qr_login(client) == "fallback"
    assert page.gotos == 1  # reloaded once before giving up
    assert not _Dialog.instances  # no dialog was opened


def test_qr_login_succeeds_after_reload(monkeypatch):
    monkeypatch.setattr(readiness.auth, "check_login", lambda page, timeout_ms=0: (True, "chat"))
    page = _Page(qr_uri="", reload_uri=_URI)
    client = _Client(page, make_settings(qr_ready_ms=0))
    assert readiness._qr_login(client) == "ok"
    assert page.gotos == 1
    assert _Dialog.instances[-1].opened == _URI


def test_qr_login_raises_when_dialog_cannot_open(monkeypatch):
    def boom(self, data_uri):
        raise QrDialogFailed("no dialog")

    monkeypatch.setattr(_Dialog, "open", boom)
    client = _Client(_Page(), make_settings())
    with pytest.raises(QrDialogFailed):
        readiness._qr_login(client)
    assert _Dialog.instances[-1].finished == ("cancel", True)


def test_install_extension_success_returns_to_headless(monkeypatch):
    calls = []
    monkeypatch.setattr(readiness.mode, "mode_of", lambda s: readiness.mode.HEADLESS)
    monkeypatch.setattr(readiness, "switch_mode",
                        lambda c, headless, open_page=True: calls.append(headless))
    monkeypatch.setattr(readiness.session, "open_store_page", lambda ctx, s: object())
    monkeypatch.setattr(readiness.session, "is_on_disk", lambda s: True)
    monkeypatch.setattr(readiness.chrome, "is_debug_ready", lambda s, timeout_sec=2: True)
    monkeypatch.setattr(readiness.session, "check_installed",
                        lambda ctx, s, b: (True, "found_on_disk=True"))
    client = _Client(_Page(), make_settings())
    installed, detail = readiness._install_extension(client, client.settings, "x")
    assert installed is True
    assert detail == "found_on_disk=True"
    assert calls == [False, True]  # headed to install, then back to headless


def test_install_extension_cancel_when_chrome_closed(monkeypatch):
    calls = []
    monkeypatch.setattr(readiness.mode, "mode_of", lambda s: readiness.mode.HEADLESS)
    monkeypatch.setattr(readiness, "switch_mode",
                        lambda c, headless, open_page=True: calls.append(headless))
    monkeypatch.setattr(readiness.session, "open_store_page", lambda ctx, s: object())
    monkeypatch.setattr(readiness.session, "is_on_disk", lambda s: False)
    monkeypatch.setattr(readiness.chrome, "is_debug_ready", lambda s, timeout_sec=2: False)
    client = _Client(_Page(), make_settings())
    installed, detail = readiness._install_extension(client, client.settings, "x")
    assert installed is False
    assert "ยกเลิก" in detail
    assert calls == [False]  # headed only, never switched back


def test_install_extension_already_headed(monkeypatch):
    calls = []
    monkeypatch.setattr(readiness.mode, "mode_of", lambda s: readiness.mode.HEADED)
    monkeypatch.setattr(readiness, "switch_mode",
                        lambda c, headless, open_page=True: calls.append(headless))
    monkeypatch.setattr(readiness.session, "open_store_page", lambda ctx, s: object())
    monkeypatch.setattr(readiness.session, "is_on_disk", lambda s: True)
    monkeypatch.setattr(readiness.chrome, "is_debug_ready", lambda s, timeout_sec=2: True)
    monkeypatch.setattr(readiness.session, "check_installed", lambda ctx, s, b: (True, "ok"))
    client = _Client(_Page(), make_settings(headless=False))
    installed, _ = readiness._install_extension(client, client.settings, "x")
    assert installed is True
    assert calls == [True]  # no headed switch, only back to headless


def test_ensure_headed_noop_when_already_headed(monkeypatch):
    calls = []
    monkeypatch.setattr(readiness.mode, "mode_of", lambda s: readiness.mode.HEADED)
    monkeypatch.setattr(readiness, "switch_mode", lambda c, headless: calls.append(headless))
    client = _Client(_Page(), make_settings(headless=False))
    assert readiness._ensure_headed(client) is False
    assert calls == []


def test_ensure_headed_switches_when_headless(monkeypatch):
    calls = []
    monkeypatch.setattr(readiness.mode, "mode_of", lambda s: readiness.mode.HEADLESS)
    monkeypatch.setattr(readiness, "switch_mode", lambda c, headless: calls.append(headless))
    client = _Client(_Page(), make_settings(headless=True))
    assert readiness._ensure_headed(client) is True
    assert calls == [False]
