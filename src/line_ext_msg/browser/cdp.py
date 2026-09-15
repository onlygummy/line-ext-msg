"""CDP HTTP endpoints in one place: target list, target close, version.

The debug Chrome exposes plain HTTP endpoints on the CDP port. All of them
are reached from here so the URL shape, the timeout, and the "unreachable
means empty" policy live in a single module.
"""

import json
import logging
import urllib.request

from ..config.settings import Settings

logger = logging.getLogger(__name__)


def _get_json(settings: Settings, path: str, timeout_sec: float):
    """GET a CDP path and parse JSON; None when unreachable or unparsable."""
    try:
        with urllib.request.urlopen(
            f"{settings.cdp_endpoint}{path}", timeout=timeout_sec
        ) as res:
            return json.loads(res.read().decode("utf-8", errors="ignore"))
    except Exception as e:
        logger.debug("CDP %s failed: %s", path, e)
        return None


def list_targets(settings: Settings, timeout_sec: float = 3) -> list[dict]:
    """CDP target list; [] when the endpoint is down or answers oddly."""
    data = _get_json(settings, "/json/list", timeout_sec)
    if not isinstance(data, list):
        return []
    return [t for t in data if isinstance(t, dict)]


def close_target(settings: Settings, target_id: str, timeout_sec: float = 3) -> bool:
    """Ask CDP to close one target; True when the call went through."""
    try:
        with urllib.request.urlopen(
            f"{settings.cdp_endpoint}/json/close/{target_id}", timeout=timeout_sec
        ) as res:
            res.read()
        return True
    except Exception as e:
        logger.debug("CDP close %s failed: %s", target_id, e)
        return False


def version(settings: Settings, timeout_sec: float = 2) -> dict:
    """Raw /json/version payload; {} when unreachable or not a dict."""
    data = _get_json(settings, "/json/version", timeout_sec)
    return data if isinstance(data, dict) else {}
