"""LineClient: single facade owning the whole lifecycle.

Typical use (also the shape MCP tools wrap)::

    with LineClient(quiet=True) as line:
        rooms = line.list_rooms(unread_only=True)
        rooms.save("rooms.json")
        msgs = line.get_messages("Family", limit=5)
        msgs.save("messages.json")

Queries return results only; saving, media download, and session wiping
are separate, explicit calls.
"""

import logging
from dataclasses import asdict

from ..browser import process as _process
from ..config import paths
from ..config.settings import Settings
from ..domain.errors import LineError
from ..domain.models import Room, StepResult
from ..output.progress import Steps
from ..results import Dom, Messages, Probe, Report, Rooms
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

    def list_rooms(self, unread_only: bool = False, query: str | None = None) -> Rooms:
        """Rooms from the chats view, optionally filtered. Returns a Rooms result."""
        rooms = _rooms.list_rooms(self._ready_page(), self.settings)
        if unread_only:
            rooms = [r for r in rooms if r.unread > 0]
        if query:
            rooms = [r for r in rooms if query in r.name]
        return Rooms(rooms)

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
        with_media: bool = False,
        scroll: bool = True,
    ) -> Messages:
        """Latest messages, optionally opening a room first and filtering.

        Older rows are scrolled into view first (bounded by
        settings.messages_scroll_ms); scroll=False reads only what the
        DOM already holds. with_media fetches image bubbles in memory as
        data URIs (no files); call Messages.download_media to write them.
        The returned Messages carries the opened room so save() writes it.
        """
        room_obj: Room | None = None
        if room is not None:
            room_obj = _rooms.open_room(self._ready_page(), room, self.list_rooms(), self.settings)
        msgs = _messages.get_messages(
            self._ready_page(), self.settings, limit=limit, date=date,
            date_from=date_from, date_to=date_to, time_from=time_from,
            time_to=time_to, sender=sender, keyword=keyword,
            with_media=with_media, scroll=scroll,
        )
        if room_obj is not None:
            msgs.room = room_obj
        return msgs

    def unread_digest(self) -> Report:
        """Rooms with unread>0 plus latest preview, as a Report."""
        return Report(asdict(r) for r in self.list_rooms(unread_only=True))

    def unread_full(self, date: str | None = None, limit_per_room: int = 20) -> Report:
        """Unread rooms with their messages. date=None means today (local)."""
        from datetime import date as _date
        day = date or _date.today().isoformat()
        out = Report()
        unread = self.list_rooms(unread_only=True)
        for i, room in enumerate(unread):
            logger.info("unread room %d/%d: %s", i + 1, len(unread), room.name)
            _rooms.open_room(self._ready_page(), room, self.list_rooms(), self.settings)
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
    ) -> Report:
        """Search keyword across rooms. Returns only rooms with matches.

        Sequential (one room at a time); cost ~ seconds per room.
        """
        targets: list[Room] = list(self.list_rooms())
        if rooms is not None:
            wanted: list[Room] = []
            for ref in rooms:
                try:
                    wanted.append(_rooms.resolve_ref(ref, targets))
                except Exception:
                    continue
            targets = wanted
        out = Report()
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

    def dump_page(self) -> Dom:
        """Return the chats DOM for selector tuning. No login required."""
        state, html = _diagnostics.read_page(self)
        return Dom(html, state=state)

    def dump_room(self, ref: int | str | Room) -> Dom:
        """Open a room and return its DOM for message-selector tuning."""
        room, html = _diagnostics.read_room(self, ref)
        return Dom(html, room=room)

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
                summary["backup"] = self.probe_session().save(paths.PROBE_BEFORE_CLEAR_JSON)
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

    def probe_session(self) -> Probe:
        """Redacted storage probe: shows where the login token lives.

        Key names with type and length only, never secret values.
        """
        return Probe(_diagnostics.probe_session(self))


__all__ = ["LineClient", "LineError"]
