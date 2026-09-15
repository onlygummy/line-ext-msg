"""Headless/headed state machine: transitions without a real browser."""

import pytest

from line_ext_msg.browser import mode
from line_ext_msg.domain.errors import ChromeNotReady
from tests.helpers import make_settings


def test_mode_of_absent(monkeypatch):
    monkeypatch.setattr(mode.chrome, "is_debug_ready", lambda s, timeout_sec=2: False)
    assert mode.mode_of(make_settings()) == mode.ABSENT


def test_mode_of_headless_and_headed(monkeypatch):
    monkeypatch.setattr(mode.chrome, "is_debug_ready", lambda s, timeout_sec=2: True)
    monkeypatch.setattr(mode.chrome, "is_headless", lambda s, timeout_sec=2: True)
    assert mode.mode_of(make_settings()) == mode.HEADLESS
    monkeypatch.setattr(mode.chrome, "is_headless", lambda s, timeout_sec=2: False)
    assert mode.mode_of(make_settings()) == mode.HEADED


def test_desired_mode_follows_settings():
    assert mode.desired_mode(make_settings(headless=True)) == mode.HEADLESS
    assert mode.desired_mode(make_settings(headless=False)) == mode.HEADED


def test_converge_noop_when_already_desired(monkeypatch):
    stopped = []
    monkeypatch.setattr(mode, "stop", lambda *a, **k: stopped.append(True))
    out = mode.converge(
        make_settings(headless=True),
        probe=lambda s: mode.HEADLESS,
    )
    assert out == mode.HEADLESS
    assert stopped == []


def test_converge_switches_and_verifies(monkeypatch):
    state = {"mode": mode.HEADLESS}
    stopped = []

    def fake_stop(settings, browser=None, on_event=None, wait_port=None):
        stopped.append(True)
        state["mode"] = None
        return "graceful"

    def fake_start(settings):
        state["mode"] = mode.HEADLESS if settings.headless else mode.HEADED

    monkeypatch.setattr(mode, "stop", fake_stop)
    out = mode.converge(
        make_settings(headless=False),
        probe=lambda s: state["mode"],
        starter=fake_start,
    )
    assert out == mode.HEADED
    assert stopped == [True]


def test_converge_retries_once(monkeypatch):
    state = {"mode": mode.HEADLESS, "starts": 0}
    monkeypatch.setattr(mode, "stop", lambda *a, **k: "force")

    def fake_start(settings):
        state["starts"] += 1
        # First start lands in the wrong mode; the retry fixes it.
        if state["starts"] >= 2:
            state["mode"] = mode.HEADED

    out = mode.converge(
        make_settings(headless=False),
        probe=lambda s: state["mode"],
        starter=fake_start,
    )
    assert out == mode.HEADED
    assert state["starts"] == 2


def test_converge_raises_when_mode_never_matches(monkeypatch):
    monkeypatch.setattr(mode, "stop", lambda *a, **k: "force")
    with pytest.raises(ChromeNotReady):
        mode.converge(
            make_settings(headless=False),
            probe=lambda s: mode.HEADLESS,
            starter=lambda s: None,
        )


class _Browser:
    def __init__(self, fail=False):
        self.fail = fail
        self.closed = 0

    def close(self):
        self.closed += 1
        if self.fail:
            raise RuntimeError("beforeunload blocked close")


def test_stop_graceful_avoids_force_kill(monkeypatch):
    monkeypatch.setattr(mode.chrome, "is_debug_ready", lambda s, timeout_sec=2: True)
    killed = []
    monkeypatch.setattr(mode.process, "terminate_debug_chrome", lambda s: killed.append(True))
    browser = _Browser()
    out = mode.stop(make_settings(), browser, wait_port=lambda s, t: True)
    assert out == "graceful"
    assert browser.closed == 1
    assert killed == []


def test_stop_falls_back_to_force_kill(monkeypatch):
    monkeypatch.setattr(mode.chrome, "is_debug_ready", lambda s, timeout_sec=2: True)
    killed = []
    monkeypatch.setattr(mode.process, "terminate_debug_chrome", lambda s: killed.append(True))
    browser = _Browser(fail=True)
    out = mode.stop(make_settings(), browser, wait_port=lambda s, t: True)
    assert out == "force"
    assert killed == [True]


def test_stop_absent_leaves_process_alone(monkeypatch):
    monkeypatch.setattr(mode.chrome, "is_debug_ready", lambda s, timeout_sec=2: False)
    killed = []
    monkeypatch.setattr(mode.process, "terminate_debug_chrome", lambda s: killed.append(True))
    assert mode.stop(make_settings()) == mode.ABSENT
    assert killed == []
