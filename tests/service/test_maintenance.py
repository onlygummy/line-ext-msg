"""Clear-session touches only extension storage, never the install."""

import os

from line_ext_msg.config.settings import Settings
from line_ext_msg.service import maintenance as clear_session


def test_wipe_dirs_exclude_install():
    assert "Extensions" not in clear_session._ON_DISK_DIRS
    assert set(clear_session._ON_DISK_DIRS) == {"Local Storage", "IndexedDB"}


def test_profile_default_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LINE_EXT_MSG_PROFILE", str(tmp_path))
    got = clear_session.profile_default_dir(Settings())
    assert got == os.path.join(str(tmp_path), "Default")


def test_clear_on_disk_missing_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("LINE_EXT_MSG_PROFILE", str(tmp_path))
    assert clear_session.clear_on_disk(Settings()) == []
