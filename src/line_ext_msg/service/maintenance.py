"""Clear only the LINE extension session. Keeps the install and profile.

Two layers: live clear via JS while Chrome runs (localStorage,
chrome.storage, IndexedDB), then on-disk wipe of the LevelDB/IndexedDB
folders after Chrome stops (JS alone leaves IndexedDB blocked while the
page holds it open). Never touches the user's normal Chrome profile.
"""

import os
import shutil

from playwright.sync_api import Page

from ..browser import js
from ..config.settings import Settings

# Folders under <profile>/Default wiped on disk. Extension install dir
# (Default/Extensions/<id>) is intentionally excluded.
_ON_DISK_DIRS = ("Local Storage", "IndexedDB")


def profile_default_dir(settings: Settings) -> str:
    """<profile>/Default directory holding extension storage."""
    from ..browser.process import expand

    return os.path.join(expand(settings.profile_dir), "Default")


def clear_live(page: Page) -> dict:
    """Clear session areas via JS. Returns counts before/after (redacted)."""
    return page.evaluate(js.CLEAR_STORAGE)


def clear_on_disk(settings: Settings) -> list:
    """Delete LevelDB/IndexedDB folders. Chrome must already be stopped."""
    base = profile_default_dir(settings)
    wiped = []
    for name in _ON_DISK_DIRS:
        path = os.path.join(base, name)
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)
            wiped.append(name)
    return wiped
