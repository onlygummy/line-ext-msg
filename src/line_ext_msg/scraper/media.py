"""Image bubble download: fetch blob URLs in-page, save files, build data URIs."""

from __future__ import annotations

from ..browser import js
from ..config.selectors import SELECTORS

_MIME_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}


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


def download_image(
    page,
    row,
    media_dir: str | None,
    include_data: bool,
    msg_id: str,
) -> tuple[str, str]:
    """Fetch one image bubble. Returns (local path, data URI); '' when skipped/failed."""
    import base64
    import os

    if not media_dir and not include_data:
        return "", ""
    try:
        img = row.locator(SELECTORS["image"]).locator("img").first
        src = img.get_attribute("src") or ""
        if not src.startswith("blob:"):
            return "", ""
        mime, data = _fetch_blob(page, src)
        if not data:
            return "", ""
        path = ""
        if media_dir:
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in msg_id)[:60]
            os.makedirs(media_dir, exist_ok=True)
            path = os.path.join(media_dir, f"{safe}.{_MIME_EXT.get(mime, 'bin')}")
            with open(path, "wb") as f:
                f.write(base64.b64decode(data))
        return path, to_data_uri(mime, data) if include_data else ""
    except Exception:
        return "", ""
