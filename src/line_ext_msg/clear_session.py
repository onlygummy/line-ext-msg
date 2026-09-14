"""Clear only the LINE extension session. Keeps the install and profile.

Two layers: live clear via JS while Chrome runs (localStorage,
chrome.storage, IndexedDB), then on-disk wipe of the LevelDB/IndexedDB
folders after Chrome stops (JS alone leaves IndexedDB blocked while the
page holds it open). Never touches the user's normal Chrome profile.
"""

import os
import shutil

from playwright.sync_api import Page

from .settings import Settings

# Folders under <profile>/Default wiped on disk. Extension install dir
# (Default/Extensions/<id>) is intentionally excluded.
_ON_DISK_DIRS = ("Local Storage", "IndexedDB")


def profile_default_dir(settings: Settings) -> str:
    """<profile>/Default directory holding extension storage."""
    from .chrome import expand

    return os.path.join(expand(settings.profile_dir), "Default")


def clear_live(page: Page) -> dict:
    """Clear session areas via JS. Returns counts before/after (redacted)."""
    return page.evaluate(
        """async () => {
            const o = {lsBefore: 0, idbBefore: []};
            try { o.lsBefore = Object.keys(window.localStorage || {}).length; }
            catch (e) { o.lsErr = String(e).slice(0, 80); }
            try {
                if (indexedDB && indexedDB.databases)
                    o.idbBefore = (await indexedDB.databases()).map(d => d.name || '');
            } catch (e) { o.idbErr = String(e).slice(0, 80); }
            try { window.localStorage.clear(); } catch (e) { o.lsErr = String(e).slice(0, 80); }
            try {
                if (window.chrome && chrome.storage && chrome.storage.local)
                    await chrome.storage.local.clear();
                if (window.chrome && chrome.storage && chrome.storage.session)
                    await chrome.storage.session.clear();
                o.clearedExtStorage = true;
            } catch (e) { o.extErr = String(e).slice(0, 80); }
            try {
                o.lsAfter = Object.keys(window.localStorage || {}).length;
                if (indexedDB && indexedDB.databases)
                    o.idbAfter = (await indexedDB.databases()).map(d => d.name || '');
            } catch (e) { o.afterErr = String(e).slice(0, 80); }
            return o;
        }"""
    )


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
