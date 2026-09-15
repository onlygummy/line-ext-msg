"""Session storage probe: find where the LINE login token lives.

Read-only spike for the restart-scoped session question. Never returns
secret values, only key names with type and length, so the output file is
safe to share when tuning persistence.
"""

import json
import os
import urllib.request

from playwright.sync_api import Page

from ..browser import auth, js, session
from ..config.settings import Settings
from ..domain.models import Room
from ..output import storage


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
        raw = page.evaluate(js.PROBE_STORAGE)
    except Exception as e:
        return {"url": url, "errors": [f"evaluate:{e}"]}
    if not isinstance(raw, dict):
        return {"url": url, "errors": ["bad-payload"]}
    raw_errors = raw.get("errors")
    errors: list = raw_errors if isinstance(raw_errors, list) else []
    raw_ls = raw.get("lsKeys")
    ls_keys: list = raw_ls if isinstance(raw_ls, list) else []
    raw_idbs = raw.get("idbs")
    idbs: list = raw_idbs if isinstance(raw_idbs, list) else []
    try:
        cookie_count = int(raw.get("cookieCount") or 0)
    except (TypeError, ValueError):
        cookie_count = -1
    raw_lens = raw.get("lsLens")
    ls_lens: dict = raw_lens if isinstance(raw_lens, dict) else {}
    # Redacted lengths only, never values.
    ls_sizes: dict = {}
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
    out: list[dict] = []
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


def _write(path: str, content: str) -> None:
    """Write text, creating the parent directory when needed."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def dump_page(client, path: str) -> str:
    """Save the current chats DOM for selector tuning. No login required."""
    from ..browser import chrome as _chrome

    _chrome.ensure_chrome(client.settings)
    if client._pw is None:
        client._pw, client._browser, client._context = session.connect(client.settings)
    page = session.ensure_line_page(client._context, client.settings, client._browser)
    state = session.wait_ready(page, client.settings)
    _write(path, page.content())
    return state


def dump_room(client, ref, path: str) -> Room:
    """Open a room then save its DOM for message-selector tuning."""
    room = client.open_room(ref)
    _write(path, client._page.content())
    return room


def probe_session(client) -> dict:
    """Redacted storage probe: shows where the login token lives.

    Key names with type and length only, never secret values. Use the
    result to decide keepalive vs token-restore work.
    """
    page = client._ready_page()
    logged_in, reason = auth.check_login(page, client.settings.login_poll_ms)
    data = probe_extension_storage(page)
    data["logged_in"] = logged_in
    data["login_reason"] = reason
    data["targets"] = list_line_targets(client.settings)
    return data


def save_probe(client, path: str) -> str:
    """Run probe_session and save JSON. The only probe function that writes."""
    storage.save_json(path, probe_session(client))
    return path
