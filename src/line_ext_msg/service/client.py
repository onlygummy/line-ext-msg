"""LineClient: single facade owning the whole lifecycle.

Typical use (also the shape MCP tools wrap)::

    with LineClient(quiet=True) as line:
        rooms = line.list_rooms(unread_only=True)
        rooms.save("rooms.json")
        msgs = line.get_messages("Family", limit=5)
        msgs.save("messages.json")

Queries return results only; saving, media download, and logging out
are separate, explicit calls.
"""

import logging
from dataclasses import asdict

from ..browser import process as _process
from ..config import paths
from ..config.settings import Settings
from ..domain.callbacks import (
    PinCallback,
    ProgressCallback,
    QrCallback,
    StatusCallback,
    call_callback,
)
from ..domain.errors import LineError
from ..domain.models import Room, ScanProgress, StepResult
from ..output.progress import Steps
from ..results import Dom, Messages, Probe, Report, Rooms
from ..scraper import messages as _messages
from ..scraper import rooms as _rooms
from . import diagnostics as _diagnostics
from . import maintenance as _maintenance
from . import readiness as _readiness

logger = logging.getLogger(__name__)


class LineClient:
    """Owns ensure-chrome, attach, page, and readiness. Use as context manager.

    wait_for_login sets the instance-wide login policy so a host does not have
    to repeat it at every call site: without it, any method that needs a ready
    page would silently fall back to waiting for a QR, which is wrong for an
    unattended service. Pass False there and the whole client fails fast.

on_qr and on_pin hand the login UI to the host instead of the Tk dialog.
    Supplying any of them suppresses the dialog, so set on_qr to receive the QR
    and on_pin to receive the code. on_status carries the phases that have no
    payload of their own, which is how a host learns to stop showing a code the
    user already submitted. The wait is still bounded by login_timeout_ms.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        wait_for_login: bool | None = None,
        on_qr: QrCallback | None = None,
        on_pin: PinCallback | None = None,
        on_status: StatusCallback | None = None,
        **overrides,
    ):
        self.settings = settings or Settings(**overrides)
        self._steps = Steps(_readiness.TOTAL_STEPS, quiet=self.settings.quiet)
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        # Kept on the instance because every method that needs a ready page
        # inherits them through status().
        self._wait_policy = wait_for_login
        self.on_qr = on_qr
        self.on_pin = on_pin
        self.on_status = on_status

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
        """Run the 5 readiness checks. Raises typed LineError on first failure.

        wait_for_login decides whether a login screen opens the QR dialog and
        waits, or raises LoginRequired at once. Precedence is the argument
        here, then the value given to the constructor, then waiting. Left unset
        it waits, because a library that assumes an interactive desktop is not
        safe to embed; an unattended caller passes wait_for_login=False once, to
        the constructor or here. settings.quiet only silences the checklist.
        """
        if wait_for_login is None:
            wait_for_login = self._wait_policy
        return _readiness.run(self, wait_for_login, login_timeout_ms)

    def _ready_page(self):
        """Page guaranteed ready; runs status() once, then reuses the session.

        The implicit status() call inherits the instance wait policy, so a
        client built with wait_for_login=False stays fail-fast even when the
        caller never passes the flag, and a client that did not set one still
        opens the QR dialog on its first query.
        """
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

    def unread_full(self, date: str | None = None, limit_per_room: int = 20,
                     on_progress: ProgressCallback | None = None) -> Report:
        """Unread rooms with their messages. date=None means today (local).

        Each entry carries "truncated": true when the backfill scroll hit its
        time budget, which means older messages of that day may be missing.

        An entry can come back empty while the room still shows unread: the
        unread messages may predate `date`. Compare room["unread"] with the
        message count before reading an empty list as "nothing pending".

        on_progress gets one ScanProgress per room as it is read, carrying the
        same truncated flag, so a host can report progress on a scan that takes
        a minute per room without polling.
        """
        from datetime import date as _date
        day = date or _date.today().isoformat()
        out = Report()
        unread = self.list_rooms(unread_only=True)
        for i, room in enumerate(unread):
            logger.info("unread room %d/%d: %s", i + 1, len(unread), room.name)
            # Pass the list we already have: re-reading it per room scrolls the
            # whole chat list again for every room.
            _rooms.open_room(self._ready_page(), room, unread, self.settings)
            msgs = self.get_messages(limit=limit_per_room, date=day)
            truncated = msgs.scroll_stop == "budget"
            call_callback(
                on_progress,
                ScanProgress(room=room, index=i + 1, total=len(unread),
                             matched=len(msgs), truncated=truncated),
                what="progress",
            )
            out.append({"room": asdict(room), "messages": [asdict(m) for m in msgs],
                        "truncated": truncated})
        return out

    def search_all(
        self,
        keyword: str,
        date_from: str | None = None,
        date_to: str | None = None,
        rooms: list[int | str | Room] | None = None,
        limit_per_room: int = 100,
        on_progress: ProgressCallback | None = None,
    ) -> Report:
        """Search keyword across rooms. Sequential, one room at a time.

        Returns rooms that matched, each entry carrying "truncated": true when
        the backfill scroll hit its time budget before the older edge. Such a
        room is listed even when it matched nothing, because a partial scan
        cannot claim a keyword is absent; an empty "messages" with
        "truncated": true means "not reached", not "not there". Raise
        settings.search_scroll_ms, or settings.scroll_cap_ms when the limit
        itself is the ceiling, to finish those rooms.

        on_progress gets one ScanProgress per room, including the truncated
        ones, so a host can report both progress and partial results as they
        happen instead of only at the end.
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
        partial: list[str] = []
        for i, room in enumerate(targets):
            logger.info("searching room %d/%d: %s", i + 1, len(targets), room.name)
            _rooms.open_room(self._ready_page(), room, targets, self.settings)
            msgs = self.get_messages(
                limit=limit_per_room, date_from=date_from, date_to=date_to, keyword=keyword,
            )
            truncated = msgs.scroll_stop == "budget"
            if truncated:
                partial.append(room.name)
            call_callback(
                on_progress,
                ScanProgress(room=room, index=i + 1, total=len(targets),
                             matched=len(msgs), truncated=truncated),
                what="progress",
            )
            if msgs or truncated:
                out.append({"room": asdict(room), "messages": [asdict(m) for m in msgs],
                            "truncated": truncated})
        if partial:
            logger.warning(
                "%d room(s) hit the scroll budget before the older edge, so their "
                "results are partial (raise LINE_EXT_MSG_SEARCH_SCROLL_MS): %s",
                len(partial), ", ".join(partial))
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

    def logout(self, backup: bool = True) -> dict:
        """Log out of LINE by wiping the session; extension install stays.

        This also stops the debug Chrome, so the next status() finds no
        session and asks for a new QR scan. That is deliberate: the extension
        keeps the session token in memory, so wiping storage alone would leave
        a Chrome that looks logged in and cannot be trusted.

        backup=True saves a redacted probe to session/ first.
        """
        summary: dict = {}
        if backup:
            try:
                # Fail-fast probe: must not pop a headed QR window mid-wipe.
                try:
                    self.status(wait_for_login=False)
                except Exception:
                    pass
                summary["backup"] = self.probe_session().save(paths.PROBE_BEFORE_LOGOUT_JSON)
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

    def clear_session(self, backup: bool = True) -> dict:
        """Deprecated alias for logout(); call logout() instead.

        Kept so an app written against 1.x or 2.x does not break on upgrade.
        Note it stops the debug Chrome too, exactly like logout() does.
        """
        logger.warning("clear_session() is deprecated; call logout() instead")
        return self.logout(backup=backup)

    def probe_session(self) -> Probe:
        """Redacted storage probe: shows where the login token lives.

        Key names with type and length only, never secret values.
        """
        return Probe(_diagnostics.probe_session(self))


__all__ = ["LineClient", "LineError"]
