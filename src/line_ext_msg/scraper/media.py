"""Image bubble fetch: read blob URLs inside the page as data URIs.

Fetching has to happen while the row is still rendered (the blob lives in
the page), so this returns a data URI in memory and never writes files.
``Messages.download_media`` writes the data URIs to disk later.
"""

from __future__ import annotations

from ..browser import js
from ..config.selectors import SELECTORS


def to_data_uri(mime: str, b64: str) -> str:
    """Build a data URI from mime + base64. Pure (unit-testable)."""
    if not mime or not b64:
        return ""
    return f"data:{mime};base64,{b64}"


def _fetch_blob(page, src: str) -> tuple[str, str]:
    """Fetch a blob: URL inside the page. Returns (mime, base64), ('', '') on failure."""
    try:
        payload = page.evaluate(js.FETCH_BLOB, src)
        if not isinstance(payload, dict):
            return "", ""
        return payload.get("mime", "") or "", payload.get("data", "") or ""
    except Exception:
        return "", ""


def fetch_image(page, row) -> str:
    """Data URI of one image bubble, '' when there is no blob image."""
    try:
        img = row.locator(SELECTORS["image"]).locator("img").first
        src = img.get_attribute("src") or ""
        if not src.startswith("blob:"):
            return ""
        mime, data = _fetch_blob(page, src)
        if not data:
            return ""
        return to_data_uri(mime, data)
    except Exception:
        return ""
