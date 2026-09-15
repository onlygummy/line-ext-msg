"""CDP HTTP endpoints: target list, target close, version (no browser)."""

import json

from line_ext_msg.browser import cdp
from tests.helpers import make_settings


class _Res:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _patch_urlopen(monkeypatch, payload, calls=None):
    def fake_urlopen(url, timeout=0):
        if calls is not None:
            calls.append(url)
        return _Res(payload)

    monkeypatch.setattr(cdp.urllib.request, "urlopen", fake_urlopen)


def _patch_urlopen_boom(monkeypatch):
    def boom(url, timeout=0):
        raise OSError("connection refused")

    monkeypatch.setattr(cdp.urllib.request, "urlopen", boom)


def test_list_targets_keeps_only_dicts(monkeypatch):
    _patch_urlopen(monkeypatch, json.dumps([{"id": "a"}, "junk", {"id": "b"}]).encode())
    assert cdp.list_targets(make_settings()) == [{"id": "a"}, {"id": "b"}]


def test_list_targets_empty_when_unreachable(monkeypatch):
    _patch_urlopen_boom(monkeypatch)
    assert cdp.list_targets(make_settings()) == []


def test_list_targets_empty_on_non_list_payload(monkeypatch):
    _patch_urlopen(monkeypatch, json.dumps({"not": "a list"}).encode())
    assert cdp.list_targets(make_settings()) == []


def test_close_target_hits_the_close_endpoint(monkeypatch):
    settings = make_settings()
    calls = []
    _patch_urlopen(monkeypatch, b"", calls)
    assert cdp.close_target(settings, "abc") is True
    assert calls == [f"{settings.cdp_endpoint}/json/close/abc"]


def test_close_target_false_when_unreachable(monkeypatch):
    _patch_urlopen_boom(monkeypatch)
    assert cdp.close_target(make_settings(), "abc") is False


def test_version_returns_the_payload(monkeypatch):
    _patch_urlopen(monkeypatch, json.dumps({"Browser": "Chrome/136"}).encode())
    assert cdp.version(make_settings()) == {"Browser": "Chrome/136"}


def test_version_empty_when_unreachable(monkeypatch):
    _patch_urlopen_boom(monkeypatch)
    assert cdp.version(make_settings()) == {}


def test_version_empty_on_non_dict_payload(monkeypatch):
    _patch_urlopen(monkeypatch, json.dumps(["nope"]).encode())
    assert cdp.version(make_settings()) == {}
