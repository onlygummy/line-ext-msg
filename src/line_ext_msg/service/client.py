"""LineClient: single facade owning the whole lifecycle.

Typical use (also the shape MCP tools wrap)::

    with LineClient() as line:
        rooms = line.list_rooms(unread_only=True)
        msgs = line.get_messages("Family", limit=5)
"""

import logging
from dataclasses import asdict

from ..browser import process as _process
from ..config import paths
from ..config.settings import Settings
from ..domain.errors import LineError
from ..domain.models import Message, Room, StepResult
from ..output import storage as _storage
from ..output.progress import Steps
from ..scraper import messages as _messages
from ..scraper import rooms as _rooms
from . import diagnostics as _diagnostics
from . import maintenance as _maintenance
from . import readiness as _readiness

logger = logging.getLogger(__name__)


class LineClient:
    """Owns ensure-chrome, attach, page, and readiness. Use as context manager."""

    def __init__(self, settings: Settings | None = None, **overrides):
        self.settings = settings or Settings(**overrides)
        self._steps = Steps(_readiness.TOTAL_STEPS, quiet=self.settings.quiet)
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    # -- lifecycle ----------------------------------------------------

    def __enter__(self) -> "LineClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        """Detach CDP only; the debug Chrome stays open to keep the session."""
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None
            self._browser = self._context = self._page = None

    # -- startup checklist (also serves MCP line_status) --------------

    def status(self, wait_for_login: bool | None = None,
               login_timeout_ms: int | None = None) -> list[StepResult]:
        """Run the 5 readiness checks. Raises typed LineError on first failure."""
        return _readiness.run(self, wait_for_login, login_timeout_ms)

    def _ready_page(self):
        """Page guaranteed ready; runs status() once, then reuses the session."""
        if self._page is None:
            self.status()
        assert self._page is not None
        return self._page

    # -- domain API ---------------------------------------------------

    def list_rooms(self, unread_only: bool = False, query: str | None = None) -> list[Room]:
        """Rooms from the chats view, optionally filtered."""
        rooms = _rooms.list_rooms(self._ready_page(), self.settings)
        if unread_only:
            rooms = [r for r in rooms if r.unread > 0]
        if query:
            rooms = [r for r in rooms if query in r.name]
        return rooms

    def open_room(self, ref: int | str | Room) -> Room:
        """Open a room by index, data-mid, Room, or name substring."""
        rooms = self.list_rooms()
        return _rooms.open_room(self._ready_page(), ref, rooms, self.settings)

    def get_messages(
        self,
        room: int | str | Room | None = None,
        limit: int = 5,
        date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        time_from: str | None = None,
        time_to: str | None = None,
        sender: str | None = None,
        keyword: str | None = None,
        media_dir: str | None = None,
        include_media_data: bool = False,
        scroll: bool = True,
    ) -> list[Message]:
        """Latest messages, optionally opening a room first and filtering.

        Older rows are scrolled into view first (bounded by
        settings.messages_scroll_ms); scroll=False reads only what the
        DOM already holds. media_dir=None keeps the call side-effect
        free; set it to download image bubbles. include_media_data
        embeds data URIs (for MCP/AI, off by default).
        """
        if room is not None:
            rooms = self.list_rooms()
            _rooms.open_room(self._ready_page(), room, rooms, self.settings)
        return _messages.get_messages(
            self._ready_page(), self.settings, limit=limit, date=date,
            date_from=date_from, date_to=date_to, time_from=time_from,
            time_to=time_to, sender=sender, keyword=keyword, media_dir=media_dir,
            include_media_data=include_media_data, scroll=scroll,
        )

    def unread_digest(self) -> list[dict]:
        """Rooms with unread>0 plus latest preview: answers 'what is unread' in one call."""
        return [asdict(r) for r in self.list_rooms(unread_only=True)]

    def unread_full(self, date: str | None = None, limit_per_room: int = 20) -> list[dict]:
        """Unread rooms with their messages. date=None means today (local)."""
        from datetime import date as _date
        day = date or _date.today().isoformat()
        out = []
        for i, room in enumerate(self.list_rooms(unread_only=True)):
            logger.info("unread room %d/%d: %s", i + 1, len(self.list_rooms(unread_only=True)), room.name)
            rooms = self.list_rooms()
            _rooms.open_room(self._ready_page(), room, rooms, self.settings)
            msgs = self.get_messages(limit=limit_per_room, date=day)
            out.append({"room": asdict(room), "messages": [asdict(m) for m in msgs]})
        return out

    def search_all(
        self,
        keyword: str,
        date_from: str | None = None,
        date_to: str | None = None,
        rooms: list[int | str | Room] | None = None,
        limit_per_room: int = 100,
    ) -> list[dict]:
        """Search keyword across rooms. Returns only rooms with matches.

        Sequential (one room at a time); cost ~ seconds per room.
        """
        targets = self.list_rooms()
        if rooms is not None:
            wanted = []
            for ref in rooms:
                try:
                    wanted.append(_rooms.resolve_ref(ref, targets))
                except Exception:
                    continue
            targets = wanted
        out = []
        for i, room in enumerate(targets):
            logger.info("searching room %d/%d: %s", i + 1, len(targets), room.name)
            _rooms.open_room(self._ready_page(), room, self.list_rooms(), self.settings)
            msgs = self.get_messages(
                limit=limit_per_room, date_from=date_from, date_to=date_to, keyword=keyword,
            )
            if msgs:
                out.append({"room": asdict(room), "messages": [asdict(m) for m in msgs]})
        return out

    # -- debugging helpers --------------------------------------------

    def dump_page(self, path: str = paths.PAGE_DUMP) -> str:
        """Save the current chats DOM for selector tuning. No login required."""
        return _diagnostics.dump_page(self, path)

    def dump_room(self, ref: int | str | Room, path: str = paths.ROOM_DUMP) -> Room:
        """Open a room then save its DOM for message-selector tuning."""
        return _diagnostics.dump_room(self, ref, path)

    def clear_session(self, backup: bool = True) -> dict:
        """Wipe the LINE session only; extension install stays.

        backup=True saves a redacted probe to session/ first. Stops debug
        Chrome before the on-disk wipe, so the next run pops headed QR.
        """
        summary: dict = {}
        if backup:
            try:
                # Fail-fast probe: must not pop a headed QR window mid-wipe.
                try:
                    self.status(wait_for_login=False)
                except Exception:
                    pass
                summary["backup"] = self.save_probe(paths.PROBE_BEFORE_CLEAR_JSON)
            except Exception as e:
                summary["backup_error"] = str(e)[:120]
        try:
            summary["live"] = _maintenance.clear_live(self._ready_page())
        except Exception as e:
            summary["live_error"] = str(e)[:120]
        self.close()
        _process.terminate_debug_chrome(self.settings)
        summary["wiped"] = _maintenance.clear_on_disk(self.settings)
        return summary

    def probe_session(self) -> dict:
        """Redacted storage probe: shows where the login token lives.

        Key names with type and length only, never secret values.
        """
        return _diagnostics.probe_session(self)

    def save_probe(self, path: str = paths.PROBE_JSON) -> str:
        """Run probe_session and save JSON. The only probe method that writes."""
        return _diagnostics.save_probe(self, path)

    def save_rooms(
        self,
        path: str = paths.ROOMS_JSON,
        unread_only: bool = False,
        query: str | None = None,
    ) -> str:
        """Fetch rooms and save JSON. The only room method that writes files."""
        rooms = self.list_rooms(unread_only=unread_only, query=query)
        _storage.save_json(path, {"rooms": [asdict(r) for r in rooms]})
        return path

    def save_messages(
        self,
        ref: int | str | Room,
        limit: int = 5,
        date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        time_from: str | None = None,
        time_to: str | None = None,
        sender: str | None = None,
        keyword: str | None = None,
        media_dir: str | None = None,
        include_media_data: bool = False,
        scroll: bool = True,
        path: str | None = None,
    ) -> str:
        """Open room, fetch messages, save JSON. The only message method that writes files."""
        from datetime import datetime, timezone

        room = self.open_room(ref)
        msgs = self.get_messages(
            limit=limit, date=date, date_from=date_from, date_to=date_to,
            time_from=time_from, time_to=time_to, sender=sender, keyword=keyword,
            media_dir=media_dir, include_media_data=include_media_data,
            scroll=scroll,
        )
        out = path or paths.messages_json(room.index)
        _storage.save_json(out, {
            "room": asdict(room),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "messages": [asdict(m) for m in msgs],
        })
        return out


__all__ = ["LineClient", "LineError"]
