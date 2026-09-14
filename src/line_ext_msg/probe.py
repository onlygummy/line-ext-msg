"""Session storage probe: find where the LINE login token lives.

Read-only spike for the restart-scoped session question. Never returns
secret values, only key names with type and length, so the output file is
safe to share when tuning persistence.
"""

import json
import urllib.request

from playwright.sync_api import Page

from .settings import Settings


def summarize_dict(data) -> dict:
    """Redacted summary of a storage dict: {key: {type, len}}.

    Pure (unit-testable). Values are never included.
    """
    if not isinstance(data, dict):
        return {}
    out: dict = {}
    for key, val in data.items():
        name = str(key)
        if isinstance(val, str):
            out[name] = {"type": "str", "len": len(val)}
        elif isinstance(val, (int, float, bool)):
            out[name] = {"type": type(val).__name__, "len": len(str(val))}
        elif isinstance(val, (list, dict)):
            try:
                size = len(val)
            except Exception:
                size = -1
            out[name] = {"type": type(val).__name__, "len": size}
        elif val is None:
            out[name] = {"type": "none", "len": 0}
        else:
            out[name] = {"type": type(val).__name__, "len": -1}
    return out


def probe_extension_storage(page: Page) -> dict:
    """Inspect extension storage areas from inside the LINE page.

    Returns key summaries only. Missing APIs are reported in `errors`
    instead of raising, so a partial probe is still useful.
    """
    try:
        url = page.url or ""
    except Exception:
        url = ""
    try:
        raw = page.evaluate(
            """async () => {
                const out = {session: null, local: null, lsKeys: [], lsLens: {},
                             idbs: [], cookieCount: 0, errors: []};
                try {
                    if (chrome && chrome.storage && chrome.storage.session) {
                        out.session = await chrome.storage.session.get(null);
                    } else { out.errors.push('no-session-api'); }
                } catch (e) { out.errors.push('session:' + (e && e.message || e)); }
                try {
                    if (chrome && chrome.storage && chrome.storage.local) {
                        out.local = await chrome.storage.local.get(null);
                    } else { out.errors.push('no-local-api'); }
                } catch (e) { out.errors.push('local:' + (e && e.message || e)); }
                try {
                    out.lsKeys = Object.keys(window.localStorage || {});
                    for (const k of out.lsKeys) {
                        try { out.lsLens[k] = (window.localStorage.getItem(k) || '').length; }
                        catch (e) { out.lsLens[k] = -1; }
                    }
                } catch (e) { out.errors.push('ls:' + (e && e.message || e)); }
                try {
                    if (indexedDB && indexedDB.databases) {
                        out.idbs = (await indexedDB.databases()).map(d => d.name || '');
                    }
                } catch (e) { out.errors.push('idb:' + (e && e.message || e)); }
                try {
                    const c = document.cookie || '';
                    out.cookieCount = c ? c.split(';').length : 0;
                } catch (e) { out.errors.push('cookie:' + (e && e.message || e)); }
                return out;
            }"""
        )
    except Exception as e:
        return {"url": url, "errors": [f"evaluate:{e}"]}
    if not isinstance(raw, dict):
        return {"url": url, "errors": ["bad-payload"]}
    errors = raw.get("errors") if isinstance(raw.get("errors"), list) else []
    ls_keys = raw.get("lsKeys") if isinstance(raw.get("lsKeys"), list) else []
    idbs = raw.get("idbs") if isinstance(raw.get("idbs"), list) else []
    try:
        cookie_count = int(raw.get("cookieCount") or 0)
    except (TypeError, ValueError):
        cookie_count = -1
    ls_lens = raw.get("lsLens") if isinstance(raw.get("lsLens"), dict) else {}
    # Redacted lengths only, never values.
    ls_sizes = {}
    for k in ls_keys[:100]:
        try:
            ls_sizes[str(k)] = int(ls_lens.get(k, -1))
        except (TypeError, ValueError):
            ls_sizes[str(k)] = -1
    return {
        "url": url,
        "session_keys": summarize_dict(raw.get("session")),
        "local_keys": summarize_dict(raw.get("local")),
        "local_storage_keys": [str(k) for k in ls_keys][:100],
        "local_storage_lens": ls_sizes,
        "indexed_dbs": [str(k) for k in idbs][:100],
        "cookie_count": cookie_count,
        "errors": [str(e) for e in errors][:20],
    }


def list_line_targets(settings: Settings) -> list:
    """CDP targets belonging to the LINE extension (read-only)."""
    try:
        with urllib.request.urlopen(f"{settings.cdp_endpoint}/json/list", timeout=3) as res:
            targets = json.loads(res.read().decode("utf-8", errors="ignore"))
    except Exception:
        return []
    out = []
    if not isinstance(targets, list):
        return out
    for t in targets:
        if not isinstance(t, dict):
            continue
        url = t.get("url") or ""
        if settings.extension_id not in url:
            continue
        out.append({
            "type": t.get("type") or "",
            "title": (t.get("title") or "")[:120],
            "url": url[:300],
        })
    return out
