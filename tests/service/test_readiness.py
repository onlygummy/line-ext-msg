"""Headless QR login flow decisions (no browser, no real Tk)."""

import logging

import pytest

from line_ext_msg.domain.errors import (
    AppNotReady,
    LoginRequired,
    LoginTimeout,
    QrDialogFailed,
)
from line_ext_msg.output.progress import Steps
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

    def __init__(self, png="session/qr.png", status="session/qr_status.json", zoom=2,
                 title="LINE"):
        self.png = png
        self.status = status
        self.zoom = zoom
        self.title = title
        self.opened = None
        self.updated = []
        self.qr_shows = []
        self.pins = []
        self.verifying = []
        self.resumed = []
        self.finished = None
        # Every lifecycle call in order, so a test can assert the sequence the
        # dialog walks rather than just the calls that happened.
        self.calls: list[str] = []
        self._alive = True
        _Dialog.instances.append(self)

    def open(self, data_uri):
        self.opened = data_uri
        self.calls.append("open")

    def set_verifying(self):
        self.verifying.append(True)
        self.calls.append("verifying")

    def resume(self):
        self.resumed.append(True)
        self.calls.append("resume")

    def show_qr(self, data_uri):
        self.qr_shows.append(data_uri)
        self.updated.append(data_uri)

    def update(self, data_uri):
        self.updated.append(data_uri)
        return True

    def set_pin(self, pin, desc=""):
        self.pins.append((pin, desc))
        self.calls.append("pin")

    def alive(self):
        return self._alive

    def finish(self, state="cancel", keep_png=False):
        self.finished = (state, keep_png)
        self.calls.append(f"finish:{state}")


class _ClosedDialog(_Dialog):
    """A dialog the user already closed, so the wait ends on the next round."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._alive = False


class _Client:
    def __init__(self, page, settings):
        self._page = page
        self.settings = settings
        self._context = None
        self._browser = None
        # Mirrors LineClient: the checklist silence follows settings.quiet,
        # and the login UI callbacks default to the Tk dialog.
        self._steps = Steps(readiness.TOTAL_STEPS, quiet=settings.quiet)
        self.on_qr = None
        self.on_pin = None
        self.on_status = None


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
    assert _Dialog.instances[-1].finished == ("cancelled", False)


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
    # failed, not cancelled: the user closed nothing.
    assert _Dialog.instances[-1].finished == ("failed", True)


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
    assert "cancelled" in detail
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


def _patch_startup(monkeypatch, logged_in: bool, reason: str) -> None:
    """Stub the four startup checks so run() reaches the login decision."""
    monkeypatch.setattr(readiness.chrome, "is_debug_ready", lambda s, timeout_sec=2: True)
    monkeypatch.setattr(readiness.session, "connect", lambda s: (None, None, None))
    monkeypatch.setattr(readiness.session, "check_installed", lambda ctx, s, b: (True, "ok"))
    monkeypatch.setattr(readiness.session, "ensure_line_page", lambda ctx, s, b: _Page())
    monkeypatch.setattr(readiness.session, "wait_ready", lambda page, settings: "ready")
    monkeypatch.setattr(readiness.auth, "check_login",
                        lambda page, timeout_ms: (logged_in, reason))


def _stub_qr_login(monkeypatch, outcome: str, calls: list) -> None:
    """Replace the QR wait, recording the timeout it was handed.

    Recording timeout_ms is the point: run() has to pass the budget through,
    since a stub that ignored it would let that plumbing rot unnoticed.
    """
    def _fake(client, timeout_ms=None, on_qr=None, on_pin=None, on_status=None):
        calls.append(timeout_ms)
        return outcome

    monkeypatch.setattr(readiness, "_qr_login", _fake)


def _stub_chats_view(monkeypatch, result: str, calls: list) -> None:
    monkeypatch.setattr(readiness.session, "ensure_chats_view",
                        lambda page, settings: calls.append(result) or result)


def test_should_wait_defaults_to_true():
    assert readiness._should_wait(None) is True
    assert readiness._should_wait(True) is True
    assert readiness._should_wait(False) is False


def test_run_waits_for_login_by_default_even_when_quiet(monkeypatch):
    _patch_startup(monkeypatch, logged_in=False, reason="login")
    calls: list = []
    _stub_qr_login(monkeypatch, "cancel", calls)
    # quiet=True only silences the checklist: the wait still happens.
    client = _Client(_Page(), make_settings(quiet=True))
    with pytest.raises(LoginRequired):
        readiness.run(client)
    assert calls == [300000]


def test_run_hands_the_login_timeout_to_the_qr_wait(monkeypatch):
    """login_timeout_ms used to reach only the headed fallback, so the QR
    dialog itself was bounded by nothing."""
    _patch_startup(monkeypatch, logged_in=False, reason="login")
    calls: list = []
    _stub_qr_login(monkeypatch, "cancel", calls)
    client = _Client(_Page(), make_settings(quiet=True))
    with pytest.raises(LoginRequired):
        readiness.run(client, login_timeout_ms=180000)
    assert calls == [180000]


def test_run_reports_a_timed_out_login_as_login_timeout(monkeypatch):
    _patch_startup(monkeypatch, logged_in=False, reason="login")
    _stub_qr_login(monkeypatch, "timeout", [])
    client = _Client(_Page(), make_settings(quiet=True))
    with pytest.raises(LoginTimeout):
        readiness.run(client, login_timeout_ms=1000)


def test_login_timeout_is_catchable_as_login_required():
    """The subclassing is the whole point: existing handlers keep working."""
    assert issubclass(LoginTimeout, LoginRequired)


def test_run_fails_fast_when_wait_for_login_is_false(monkeypatch):
    _patch_startup(monkeypatch, logged_in=False, reason="login")
    calls: list = []
    _stub_qr_login(monkeypatch, "cancel", calls)
    client = _Client(_Page(), make_settings(quiet=True))
    with pytest.raises(LoginRequired):
        readiness.run(client, wait_for_login=False)
    assert calls == []


def test_run_does_not_wait_when_the_login_budget_is_zero(monkeypatch):
    _patch_startup(monkeypatch, logged_in=False, reason="login")
    calls: list = []
    _stub_qr_login(monkeypatch, "cancel", calls)
    client = _Client(_Page(), make_settings(quiet=True, login_wait_ms=0))
    with pytest.raises(LoginRequired):
        readiness.run(client)
    assert calls == []


def test_run_does_not_wait_when_selectors_do_not_match(monkeypatch, caplog):
    _patch_startup(monkeypatch, logged_in=False, reason="unknown")
    calls: list = []
    _stub_qr_login(monkeypatch, "cancel", calls)
    # An unknown reason means the selectors missed, not that a login is
    # pending, so no QR dialog and the mismatch is reported instead.
    client = _Client(_Page(), make_settings(quiet=False))
    with caplog.at_level(logging.INFO):
        with pytest.raises(LoginRequired):
            readiness.run(client)
    assert calls == []
    assert "known selectors" in caplog.text


def test_run_returns_after_a_successful_wait(monkeypatch):
    _patch_startup(monkeypatch, logged_in=False, reason="login")
    calls: list = []
    _stub_qr_login(monkeypatch, "ok", calls)
    client = _Client(_Page(), make_settings(quiet=True))
    steps = readiness.run(client)
    assert calls == [300000]
    assert steps[-1].name == "Logged in"
    assert steps[-1].passed is True


def test_run_checks_the_chats_view_after_a_login_wait(monkeypatch):
    """LINE lands on its own view after auth, so the route has to be
    re-checked once logged in, not only before the login screen."""
    _patch_startup(monkeypatch, logged_in=False, reason="login")
    _stub_qr_login(monkeypatch, "ok", [])
    chats: list = []
    _stub_chats_view(monkeypatch, "navigated", chats)
    client = _Client(_Page(), make_settings(quiet=True))
    readiness.run(client)
    assert chats == ["navigated"]


def test_run_checks_the_chats_view_when_already_logged_in(monkeypatch):
    _patch_startup(monkeypatch, logged_in=True, reason="chat")
    chats: list = []
    _stub_chats_view(monkeypatch, "already", chats)
    client = _Client(_Page(), make_settings(quiet=True))
    readiness.run(client)
    assert chats == ["already"]


def test_run_does_not_raise_when_the_chats_view_cannot_be_reached(monkeypatch, caplog):
    """status() still passes so an embedding app can poll it; list_rooms is
    the call that refuses to read a page that is not the chats view."""
    _patch_startup(monkeypatch, logged_in=True, reason="chat")
    _stub_chats_view(monkeypatch, "failed", [])
    client = _Client(_Page(), make_settings(quiet=True))
    with caplog.at_level(logging.WARNING):
        steps = readiness.run(client)
    assert steps[-1].passed is True
    assert "could not reach the chats view" in caplog.text


def _script_login(monkeypatch, reasons, cap=200):
    """check_login replays a reason sequence, repeating the last one.

    The cap turns a wait loop that never reaches its exit condition into a
    failure instead of a hung test run.
    """
    script = list(reasons)
    calls = {"n": 0}

    def fake_check_login(page, timeout_ms=0):
        calls["n"] += 1
        if calls["n"] > cap:
            raise AssertionError("check_login polled too often: the loop never ended")
        reason = script.pop(0) if len(script) > 1 else script[0]
        return reason == "chat", reason

    monkeypatch.setattr(readiness.auth, "check_login", fake_check_login)


def test_qr_login_recovers_when_line_lands_on_another_view(monkeypatch):
    """The reported bug: after the PIN step the page matched neither the login
    screen nor the chats list, and the loop spun until the dialog was closed."""
    _script_login(monkeypatch, ["login", "login", "unknown", "unknown",
                                "unknown", "unknown", "chat"])
    chats: list = []
    _stub_chats_view(monkeypatch, "navigated", chats)
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "ok"
    assert chats == ["navigated"]


def test_qr_login_gives_up_instead_of_spinning(monkeypatch):
    _script_login(monkeypatch, ["unknown"])
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    # The dialog is still open (alive), so only the give-up path can end this.
    assert readiness._qr_login(client) == "stuck"


def test_qr_login_bounds_the_number_of_reloads(monkeypatch):
    """A page that never recovers must not reload the SPA forever."""
    _script_login(monkeypatch, ["unknown"])
    chats: list = []
    _stub_chats_view(monkeypatch, "already", chats)
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "stuck"
    assert len(chats) == readiness._UNKNOWN_RECOVERIES


def test_qr_login_stops_when_the_reload_reports_failure(monkeypatch):
    _script_login(monkeypatch, ["unknown"])
    chats: list = []
    _stub_chats_view(monkeypatch, "failed", chats)
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "stuck"
    assert chats == ["failed"]


def test_qr_login_does_not_reload_while_the_login_screen_is_up(monkeypatch):
    """A reload here would throw away a half-entered PIN."""
    monkeypatch.setattr(readiness.qr, "QrDialog", _ClosedDialog)
    _script_login(monkeypatch, ["login", "login", "login", "login", "login",
                                "login", "login", "login", "login", "login"])
    chats: list = []
    _stub_chats_view(monkeypatch, "already", chats)
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "cancel"
    assert chats == []


def test_qr_login_grace_resets_when_the_login_screen_returns(monkeypatch):
    """Rounds on the login screen must not add up towards the give-up.

    Eighteen unclassified rounds are spread across login rounds, so without a
    reset the loop would have given up long before reaching the final 'chat'.
    One recovery is expected: the four trailing unknowns are consecutive.
    """
    reasons = ["unknown", "unknown", "login"] * 6 + ["unknown"] * 4 + ["chat"]
    _script_login(monkeypatch, reasons)
    chats: list = []
    _stub_chats_view(monkeypatch, "already", chats)
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "ok"
    assert len(chats) == 1


def test_run_reports_an_unmatched_page_as_app_not_ready(monkeypatch):
    _patch_startup(monkeypatch, logged_in=False, reason="login")
    _stub_qr_login(monkeypatch, "stuck", [])
    client = _Client(_Page(), make_settings(quiet=True))
    with pytest.raises(AppNotReady) as err:
        readiness.run(client)
    assert "--dump" in str(err.value)


def _fake_clock(monkeypatch, step_ms: float = 1.0):
    """Replace time.monotonic with a deterministic advancing clock.

    The wait loop does no real sleeping, so wall-clock time barely moves while
    it spins. Without this the deadline would be untestable.
    """
    ticks = {"n": 0}

    def fake_monotonic():
        ticks["n"] += 1
        return ticks["n"] * step_ms / 1000.0

    monkeypatch.setattr(readiness.time, "monotonic", fake_monotonic)
    return ticks


def test_qr_login_gives_up_when_the_timeout_expires(monkeypatch):
    """The QR wait used to have no deadline: only a human closing the dialog
    or an unmatched page could end it. login_timeout_ms never reached here."""
    _fake_clock(monkeypatch)
    # cap=200 in _script_login turns a missing deadline into a failed assertion
    # rather than a hung test run.
    _script_login(monkeypatch, ["login"])
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client, 5) == "timeout"


def test_qr_login_closes_the_dialog_after_a_timeout(monkeypatch):
    """The viewer subprocess must not be left behind when the wait ends."""
    _fake_clock(monkeypatch)
    _script_login(monkeypatch, ["login"])
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    readiness._qr_login(client, 5)
    assert _Dialog.instances[0].finished == ("failed", False)


def test_qr_login_without_a_timeout_still_ends_on_success(monkeypatch):
    """None keeps the old unbounded behaviour for callers that want it."""
    _script_login(monkeypatch, ["login", "chat"])
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "ok"


def test_qr_login_hands_the_qr_to_the_host_instead_of_a_dialog(monkeypatch):
    seen: list = []
    _script_login(monkeypatch, ["login", "chat"])
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client, on_qr=seen.append) == "ok"
    assert seen == [_URI]
    # No viewer process at all: that is the point on a machine with no desktop.
    assert _Dialog.instances == []


def test_qr_login_hands_the_pin_to_the_host(monkeypatch):
    pins: list = []
    _script_login(monkeypatch, ["login", "login", "chat"])
    monkeypatch.setattr(readiness, "_login_pin", lambda page: ("5239", "type it on the phone"))
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(
        client,
        on_qr=lambda uri: None,
        on_pin=lambda pin, desc: pins.append((pin, desc)),
    ) == "ok"
    assert pins == [("5239", "type it on the phone")] * 2


def test_qr_login_suppresses_the_dialog_for_a_pin_only_host(monkeypatch):
    """Either callback replaces the dialog, so a server never pops a window."""
    _script_login(monkeypatch, ["login", "chat"])
    monkeypatch.setattr(readiness, "_login_pin", lambda page: ("5239", ""))
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client, on_pin=lambda pin, desc: None) == "ok"
    assert _Dialog.instances == []


def test_qr_login_lets_the_host_cancel_on_the_first_qr(monkeypatch):
    _script_login(monkeypatch, ["login"])
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client, on_qr=lambda uri: False) == "cancel"


def test_qr_login_lets_the_host_cancel_from_the_pin(monkeypatch):
    _script_login(monkeypatch, ["login"])
    monkeypatch.setattr(readiness, "_login_pin", lambda page: ("5239", ""))
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client, on_qr=lambda uri: None,
                               on_pin=lambda pin, desc: False) == "cancel"


def test_qr_login_survives_a_raising_callback(monkeypatch, caplog):
    """A rendering bug in the host must not strand a login halfway through."""

    def boom(uri):
        raise RuntimeError("host is down")

    _script_login(monkeypatch, ["login", "chat"])
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    with caplog.at_level(logging.WARNING):
        assert readiness._qr_login(client, on_qr=boom) == "ok"
    assert "host is down" in caplog.text


def test_run_passes_the_client_callbacks_to_the_qr_wait(monkeypatch):
    """The callbacks live on the client so every entry point inherits them."""
    _patch_startup(monkeypatch, logged_in=False, reason="login")
    seen: dict = {}

    def fake_qr_login(client, timeout_ms=None, on_qr=None, on_pin=None, on_status=None):
        seen["timeout"] = timeout_ms
        seen["on_qr"] = on_qr
        seen["on_pin"] = on_pin
        seen["on_status"] = on_status
        return "cancel"

    monkeypatch.setattr(readiness, "_qr_login", fake_qr_login)
    host_qr = lambda uri: None  # noqa: E731
    host_status = lambda state: None  # noqa: E731
    client = _Client(_Page(), make_settings(quiet=True))
    client.on_qr = host_qr
    client.on_status = host_status
    with pytest.raises(LoginRequired):
        readiness.run(client, login_timeout_ms=5000)
    assert seen == {"timeout": 5000, "on_qr": host_qr, "on_pin": None,
                    "on_status": host_status}


# -- the login state machine ------------------------------------------------


def test_terminal_state_truth_table():
    assert readiness._terminal_state(True, False, False) == "done"
    assert readiness._terminal_state(False, True, False) == "failed"
    assert readiness._terminal_state(False, False, True) == "failed"
    assert readiness._terminal_state(False, False, False) == "cancelled"
    # Logging in wins over any stale flag from an earlier round.
    assert readiness._terminal_state(True, True, True) == "done"


def test_terminal_state_names_match_the_dialog_copy():
    """The two renderers share one vocabulary, so every terminal state the flow
    can produce must exist in the table the viewer renders from."""
    from line_ext_msg.service import qr

    for logged, timed_out, stuck in [(True, False, False), (False, True, False),
                                     (False, False, True), (False, False, False)]:
        assert readiness._terminal_state(logged, timed_out, stuck) in qr.TERMINAL_STATES


def test_unknown_puts_the_dialog_into_verifying(monkeypatch):
    """Nothing the user can do at that point, so the dialog must stop asking."""
    _script_login(monkeypatch, ["login", "unknown", "chat"])
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "ok"
    assert _Dialog.instances[0].verifying == [True]


def test_a_recovered_login_screen_puts_the_pin_back(monkeypatch):
    """One unknown can be a rendering hiccup, so the previous step returns."""
    _script_login(monkeypatch, ["login", "unknown", "login", "chat"])
    monkeypatch.setattr(readiness, "_login_pin", lambda page: ("5239", ""))
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "ok"
    assert _Dialog.instances[0].resumed == [True]


def test_an_ordinary_login_never_enters_verifying(monkeypatch):
    _script_login(monkeypatch, ["login", "login", "chat"])
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "ok"
    assert _Dialog.instances[0].verifying == []
    assert _Dialog.instances[0].resumed == []


def test_a_successful_login_closes_the_dialog_as_done(monkeypatch):
    _script_login(monkeypatch, ["login", "chat"])
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "ok"
    assert _Dialog.instances[0].finished[0] == "done"


def test_a_timeout_closes_the_dialog_as_failed_not_cancelled(monkeypatch):
    """Nobody closed anything, so reporting a cancel blames the user."""
    _fake_clock(monkeypatch)
    _script_login(monkeypatch, ["login"])
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client, 5) == "timeout"
    assert _Dialog.instances[0].finished[0] == "failed"


def test_an_unmatched_page_closes_the_dialog_as_failed(monkeypatch):
    _script_login(monkeypatch, ["unknown"])
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "stuck"
    assert _Dialog.instances[0].finished[0] == "failed"


def test_a_closed_dialog_still_reads_as_cancelled(monkeypatch):
    monkeypatch.setattr(readiness.qr, "QrDialog", _ClosedDialog)
    _script_login(monkeypatch, ["login"])
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "cancel"
    assert _Dialog.instances[0].finished[0] == "cancelled"


def test_host_receives_the_verifying_phase(monkeypatch):
    """The host that renders the QR has the same four dead seconds, so the
    phase has to reach it too."""
    seen: list = []
    _script_login(monkeypatch, ["login", "unknown", "unknown", "chat"])
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client, on_qr=lambda uri: None,
                               on_status=seen.append) == "ok"
    assert seen[0] == "verifying"
    assert _Dialog.instances == []


def test_host_is_told_when_the_login_finishes(monkeypatch):
    seen: list = []
    _script_login(monkeypatch, ["login", "chat"])
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client, on_qr=lambda uri: None,
                               on_status=seen.append) == "ok"
    assert seen == ["done"]


def test_a_status_only_host_still_suppresses_the_dialog(monkeypatch):
    _script_login(monkeypatch, ["login", "chat"])
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client, on_status=lambda state: None) == "ok"
    assert _Dialog.instances == []


def test_the_host_is_not_told_about_its_own_cancellation(monkeypatch):
    """It pressed the button, so reporting it back would be noise."""
    seen: list = []
    _script_login(monkeypatch, ["login"])
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client, on_qr=lambda uri: False,
                               on_status=seen.append) == "cancel"
    assert seen == []


def test_the_dialog_walks_the_states_in_order(monkeypatch):
    """The order is what the dialog looks like to a user: QR, then the code,
    then a spinner while LINE switches views, then done. The per-payload shape
    is pinned in tests/service/test_qr.py against a real status file; this
    pins the sequence the loop drives.
    """
    _script_login(monkeypatch, ["login", "unknown", "unknown", "chat"])
    monkeypatch.setattr(readiness, "_login_pin", lambda page: ("5239", "type it"))
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "ok"

    dialog = _Dialog.instances[0]
    # The dedup that keeps this at one entry lives in the real QrDialog, so the
    # double records every round; the sequence is what matters here.
    assert dialog.calls[0] == "open"
    assert dialog.calls[1] == "pin"
    assert dialog.calls[2] == "verifying"
    assert dialog.calls[-1] == "finish:done"
    assert dialog.pins == [("5239", "type it")] * 3


def test_the_dialog_restores_the_code_when_the_login_screen_returns(monkeypatch):
    _script_login(monkeypatch, ["login", "unknown", "login", "chat"])
    monkeypatch.setattr(readiness, "_login_pin", lambda page: ("5239", "type it"))
    _stub_chats_view(monkeypatch, "already", [])
    client = _Client(_Page(), make_settings())
    assert readiness._qr_login(client) == "ok"

    dialog = _Dialog.instances[0]
    # Entering and leaving verifying must alternate, not stack.
    assert dialog.verifying == [True]
    assert dialog.resumed == [True]
