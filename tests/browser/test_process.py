"""Force-kill paths: the recorded PID fast path and the PowerShell fallback."""

import subprocess

from line_ext_msg.browser import process
from tests.helpers import make_settings


def _use_temp_pid_file(monkeypatch, tmp_path):
    """Redirect the PID file to tmp_path and return it."""
    target = tmp_path / "session" / "chrome.pid"
    monkeypatch.setattr(process.paths, "CHROME_PID", str(target))
    return target


def test_pid_roundtrip(monkeypatch, tmp_path):
    _use_temp_pid_file(monkeypatch, tmp_path)
    settings = make_settings()
    assert process.read_pid(settings) is None
    process.write_pid(settings, 4321)
    assert process.read_pid(settings) == 4321
    process.clear_pid(settings)
    assert process.read_pid(settings) is None


def test_read_pid_ignores_garbage(monkeypatch, tmp_path):
    target = _use_temp_pid_file(monkeypatch, tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("not-a-pid", encoding="utf-8")
    assert process.read_pid(make_settings()) is None


def _record_runs(monkeypatch, responses):
    """Capture every subprocess.run command; responses maps argv[0] to stdout."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        out = responses.get(cmd[0], "")
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_terminate_kills_recorded_tree_with_one_taskkill(monkeypatch, tmp_path):
    _use_temp_pid_file(monkeypatch, tmp_path)
    settings = make_settings()
    process.write_pid(settings, 111)
    calls = _record_runs(monkeypatch, {})
    process.terminate_debug_chrome(settings)
    assert calls == [["taskkill", "/F", "/PID", "111", "/T"]]
    assert process.read_pid(settings) is None


def test_terminate_scans_when_no_pid_recorded(monkeypatch, tmp_path):
    _use_temp_pid_file(monkeypatch, tmp_path)
    calls = _record_runs(monkeypatch, {"powershell": "222\n333\n"})
    process.terminate_debug_chrome(make_settings())
    killed = [c for c in calls if c[0] == "taskkill"]
    assert killed == [
        ["taskkill", "/F", "/PID", "222", "/T"],
        ["taskkill", "/F", "/PID", "333", "/T"],
    ]


def test_terminate_falls_back_when_recorded_pid_is_stale(monkeypatch, tmp_path):
    _use_temp_pid_file(monkeypatch, tmp_path)
    settings = make_settings()
    process.write_pid(settings, 999)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        # The stale PID fails; the enumeration finds the real one.
        if cmd[0] == "taskkill" and cmd[3] == "999":
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="not found")
        out = "444\n" if cmd[0] == "powershell" else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    process.terminate_debug_chrome(settings)
    assert ["taskkill", "/F", "/PID", "444", "/T"] in calls
    assert process.read_pid(settings) is None
