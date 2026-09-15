"""Result containers: query values that know how to save themselves.

Read methods return these so a query never touches disk on its own; the
caller decides where (and whether) to write by calling ``.save(path)``.
Each type subclasses the matching builtin, so iterating, indexing, and
equality keep working as before.
"""

from __future__ import annotations

import base64
import os
from dataclasses import asdict, replace
from datetime import datetime, timezone

from .domain.models import Room
from .output import storage

# Chosen from the blob MIME when writing media files.
MIME_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in value)[:60]


def _write_media(media_dir: str, msg_id: str, data_uri: str) -> str:
    """Decode a data URI and write it to media_dir. '' when it cannot decode."""
    header, _, payload = data_uri.partition(",")
    mime = header[5:].split(";", 1)[0] if header.startswith("data:") else ""
    try:
        blob = base64.b64decode(payload)
    except Exception:
        return ""
    os.makedirs(media_dir, exist_ok=True)
    path = os.path.join(media_dir, f"{_safe_name(msg_id)}.{MIME_EXT.get(mime, 'bin')}")
    with open(path, "wb") as f:
        f.write(blob)
    return path


class Rooms(list):
    """list[Room] that saves itself as {"rooms": [...]}."""

    def save(self, path: str) -> str:
        storage.save_json(path, {"rooms": [asdict(r) for r in self]})
        return path


class Messages(list):
    """list[Message] with the room it came from plus save and media helpers."""

    room: Room | None = None

    def save(self, path: str) -> str:
        payload: dict = {}
        if self.room is not None:
            payload["room"] = asdict(self.room)
            payload["fetched_at"] = _timestamp()
        payload["messages"] = [asdict(m) for m in self]
        storage.save_json(path, payload)
        return path

    def download_media(self, media_dir: str, include_data: bool = False) -> Messages:
        """Write image data URIs to disk and return a new Messages.

        Message is frozen, so updated items are rebuilt. media_data is kept
        only when include_data is True. Messages without an image or without
        fetched data pass through unchanged.
        """
        out = Messages()
        out.room = self.room
        for m in self:
            if m.type != "image" or not m.media_data:
                out.append(m)
                continue
            path = _write_media(media_dir, m.id, m.media_data)
            out.append(replace(m, media=path, media_data=m.media_data if include_data else ""))
        return out


class Report(list):
    """list[dict] of query results that saves itself as a JSON array."""

    def save(self, path: str) -> str:
        storage.save_json(path, list(self))
        return path


class Probe(dict):
    """dict probe result that saves itself as JSON."""

    def save(self, path: str) -> str:
        storage.save_json(path, dict(self))
        return path


class Dom(str):
    """Raw DOM with the room it came from and the render state, plus save()."""

    room: Room | None = None
    state: str = ""

    def __new__(cls, value: str, room: Room | None = None, state: str = "") -> Dom:
        obj = super().__new__(cls, value)
        obj.room = room
        obj.state = state
        return obj

    def save(self, path: str) -> str:
        storage.save_text(path, str(self))
        return path
