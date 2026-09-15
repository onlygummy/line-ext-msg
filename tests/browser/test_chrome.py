"""CDP probes and the debug-Chrome boot path (no real browser)."""

import pytest

from line_ext_msg.browser import chrome
from line_ext_msg.domain.errors import ChromeNotReady
from tests.helpers import make_settings


@pytest.fixture(autouse=True)
def _clear_version_cache():
    """The version cache is module state; keep tests independent."""
    chrome._version_cache.clear()
    yield
    chrome._version_cache.clear()


def test_probe_reads_the_endpoint_once(monkeypatch):
    calls = []

    def fake_version(settings, timeout_sec=2):
        calls.append(settings.cdp_endpoint)
        return {"Browser": "Chrome/136", "User-Agent": "HeadlessChrome/136"}

    monkeypatch.setattr(chrome.cdp, "version", fake_version)
    assert chrome.probe(make_settings()) == (True, True)
    assert len(calls) == 1


def test_probe_reports_absent_on_failure(monkeypatch):
    monkeypatch.setattr(chrome.cdp, "version", lambda settings, timeout_sec=2: {})
    assert chrome.probe(make_settings()) == (False, False)


def test_ready_and_headless_share_one_fetch(monkeypatch):
    calls = []

    def fake_version(settings, timeout_sec=2):
        calls.append(settings.cdp_endpoint)
        return {"Browser": "Chrome/136"}

    monkeypatch.setattr(chrome.cdp, "version", fake_version)
    settings = make_settings()
    assert chrome.is_debug_ready(settings) is True
    assert chrome.is_headless(settings) is False
    assert len(calls) == 1, "the second read must come from the cache"


def test_invalidate_forces_a_refetch(monkeypatch):
    calls = []

    def fake_version(settings, timeout_sec=2):
        calls.append(settings.cdp_endpoint)
        return {"Browser": "Chrome/136"}

    monkeypatch.setattr(chrome.cdp, "version", fake_version)
    settings = make_settings()
    chrome.is_debug_ready(settings)
    chrome.invalidate(settings)
    chrome.is_debug_ready(settings)
    assert len(calls) == 2


def test_ensure_chrome_reuses_a_running_instance(monkeypatch):
    # A headed instance must be reused even when settings ask for headless:
    # restarting would drop the in-memory LINE session.
    monkeypatch.setattr(chrome, "probe", lambda s: (True, False))
    started = []
    monkeypatch.setattr(chrome, "start_chrome_debug", lambda s: started.append(True))
    chrome.ensure_chrome(make_settings(headless=True))
    assert started == []


def test_ensure_chrome_starts_when_absent(monkeypatch):
    monkeypatch.setattr(chrome, "probe", lambda s: (False, False))
    started = []
    monkeypatch.setattr(chrome, "start_chrome_debug", lambda s: started.append(True))
    chrome.ensure_chrome(make_settings())
    assert started == [True]


def test_ensure_chrome_adds_the_port_hint_on_failure(monkeypatch):
    monkeypatch.setattr(chrome, "probe", lambda s: (False, False))

    def boom(settings):
        raise ChromeNotReady("port in use")

    monkeypatch.setattr(chrome, "start_chrome_debug", boom)
    with pytest.raises(ChromeNotReady) as err:
        chrome.ensure_chrome(make_settings(port=9333))
    assert "9333" in str(err.value)


class _Child:
    pid = 4242


def test_start_records_pid_and_skips_first_run(monkeypatch, tmp_path):
    captured = {}
    written = []

    monkeypatch.setattr(chrome.process, "find_chrome_exe", lambda: "chrome.exe")
    monkeypatch.setattr(chrome.process, "is_profile_locked", lambda data_dir: False)
    monkeypatch.setattr(chrome.process, "expand", lambda path: str(tmp_path))
    monkeypatch.setattr(chrome.process, "write_pid", lambda s, pid: written.append(pid))
    monkeypatch.setattr(chrome, "_wait_debug_port", lambda s: None)
    monkeypatch.setattr(chrome, "invalidate", lambda s: None)

    def fake_popen(args, **kwargs):
        captured["args"] = args
        return _Child()

    monkeypatch.setattr(chrome.subprocess, "Popen", fake_popen)
    chrome.start_chrome_debug(make_settings(headless=True))

    args = captured["args"]
    assert "--no-first-run" in args
    assert "--no-default-browser-check" in args
    assert "--disable-notifications" in args
    assert "--hide-crash-restore-bubble" in args
    assert "--headless=new" in args
    assert written == [4242]


def test_wait_debug_port_returns_once_ready(monkeypatch):
    answers = iter([False, True])
    monkeypatch.setattr(
        chrome, "is_debug_ready", lambda s, timeout_sec=2, use_cache=True: next(answers)
    )
    monkeypatch.setattr(chrome.time, "sleep", lambda seconds: None)
    chrome._wait_debug_port(make_settings())


def test_wait_debug_port_raises_after_the_budget(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(chrome.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(chrome.time, "sleep", lambda seconds: clock.update(t=clock["t"] + 5.0))
    monkeypatch.setattr(chrome, "is_debug_ready", lambda *a, **k: False)
    with pytest.raises(ChromeNotReady):
        chrome._wait_debug_port(make_settings())
