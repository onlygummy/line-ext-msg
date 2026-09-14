"""LineClient: single facade owning the whole lifecycle.

Typical use (also the shape MCP tools wrap)::

    with LineClient() as line:
        rooms = line.list_rooms(unread_only=True)
        msgs = line.get_messages("ครอบครัว", limit=5)
"""

from dataclasses import asdict

from . import auth
from . import chrome as _chrome
from . import messages as _messages
from . import rooms as _rooms
from . import session as _session
from . import storage as _storage
from .errors import (
    AppNotReady,
    AttachFailed,
    ChromeNotReady,
    ExtensionMissing,
    LineError,
    LoginRequired,
)
from .models import Message, Room, StepResult
from .progress import Steps
from .settings import Settings


class LineClient:
    """Owns ensure-chrome, attach, page, and readiness. Use as context manager."""

    def __init__(self, settings: Settings | None = None, **overrides):
        self.settings = settings or Settings(**overrides)
        self._steps = Steps(5, quiet=self.settings.quiet)
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

    def status(
        self,
        wait_for_login: bool | None = None,
        login_timeout_ms: int | None = None,
    ) -> list[StepResult]:
        """Run the 5 readiness checks. Raises typed LineError on first failure.

        When the login screen is showing and waiting is enabled, keep
        tracking it until chat rows appear instead of failing at once.
        Default waits in interactive use, stays fail-fast when quiet
        (library/MCP) unless the caller opts in explicitly.
        """
        steps = self._steps
        if not self.settings.quiet:
            print("[0/5] เริ่มตรวจเงื่อนไข...", flush=True)
        results: list[StepResult] = []

        def record(name: str, passed: bool, detail: str = "", hint: str = "") -> StepResult:
            if detail:
                steps.detail(detail)
            steps.check(name, passed, "" if passed else hint)
            result = StepResult(name=name, passed=passed, detail=detail or hint)
            results.append(result)
            return result

        try:
            _chrome.ensure_chrome(self.settings)
        except ChromeNotReady as e:
            record("Chrome debug พร้อม", False, str(e))
            steps.skip_rest("หยุดก่อน")
            raise
        record("Chrome debug พร้อม", True)

        try:
            self._pw, self._browser, self._context = _session.connect(self.settings)
        except AttachFailed as e:
            record("เกาะเบราว์เซอร์", False, str(e))
            steps.skip_rest("หยุดก่อน")
            raise
        record("เกาะเบราว์เซอร์", True)

        installed, detail = _session.check_installed(self._context, self.settings, self._browser)
        if not record("Extension ติดตั้ง", installed,
                       detail=detail, hint=f"ติดตั้งเองจาก: {self.settings.webstore_url}").passed:
            _session.open_store_page(self._context, self.settings)
            steps.skip_rest("รอติดตั้งก่อน")
            raise ExtensionMissing(f"ติดตั้งเองจาก: {self.settings.webstore_url}")

        self._page = _session.ensure_line_page(self._context, self.settings, self._browser)
        state = _session.wait_ready(self._page, self.settings)
        if not record("หน้า LINE พร้อม", state == "ready",
                       detail=f"state={state}", hint="แอปโหลดไม่เสร็จในเวลาที่กำหนด ลองรันใหม่").passed:
            steps.skip_rest("หยุดก่อน")
            raise AppNotReady("แอปโหลดไม่เสร็จในเวลาที่กำหนด ลองรันใหม่")

        logged_in, reason = auth.check_login(self._page, self.settings.login_poll_ms)
        # Interactive CLI waits by default; quiet library use stays fail-fast.
        should_wait = wait_for_login if wait_for_login is not None else not self.settings.quiet
        wait_ms = login_timeout_ms if login_timeout_ms is not None else self.settings.login_wait_ms
        if not logged_in and reason == "login" and should_wait and wait_ms > 0:
            if not self.settings.quiet:
                print("ยังไม่ล็อกอิน กรุณาล็อกอินในหน้าต่าง Chrome ที่เปิดไว้ โปรแกรมกำลังรอ...", flush=True)
                print("กด Ctrl+C เพื่อยกเลิก", flush=True)
            last_ping = [0]

            def _tick(elapsed_ms: int) -> None:
                # Throttle progress to one line per ~10s to avoid log spam.
                if self.settings.quiet:
                    return
                if elapsed_ms - last_ping[0] >= 10000:
                    last_ping[0] = elapsed_ms
                    print(f"  ... รอการล็อกอิน ({elapsed_ms // 1000} วิ)", flush=True)

            logged_in, reason = auth.wait_for_login(self._page, wait_ms, on_tick=_tick)
            if logged_in:
                record("ล็อกอินแล้ว", True, detail="ล็อกอินสำเร็จระหว่างรอ")
                return results
        detail = "โครงหน้าเว็บไม่ตรง selector ที่รู้จัก" if reason == "unknown" and not logged_in else ""
        if not record("ล็อกอินแล้ว", logged_in,
                       detail=detail, hint="เปิดแท็บ LINE ล็อกอินด้วย QR/อีเมลก่อน แล้วรันใหม่").passed:
            steps.skip_rest("รอ login ก่อน")
            raise LoginRequired("ยังไม่ล็อกอิน LINE")
        return results

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
            if not self.settings.quiet:
                print(f"  ... ห้อง {i + 1}: {room.name}", flush=True)
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
            if not self.settings.quiet:
                print(f"  ... ค้นห้อง {i + 1}/{len(targets)}: {room.name}", flush=True)
            _rooms.open_room(self._ready_page(), room, self.list_rooms(), self.settings)
            msgs = self.get_messages(
                limit=limit_per_room, date_from=date_from, date_to=date_to, keyword=keyword,
            )
            if msgs:
                out.append({"room": asdict(room), "messages": [asdict(m) for m in msgs]})
        return out

    # -- debugging helpers --------------------------------------------

    def dump_page(self, path: str = "session/dumps/line_dom.html") -> str:
        """Save current chats DOM for selector tuning. No login required."""
        import os

        from . import chrome as _c

        _c.ensure_chrome(self.settings)
        if self._pw is None:
            self._pw, self._browser, self._context = _session.connect(self.settings)
        assert self._context is not None
        page = _session.ensure_line_page(self._context, self.settings, self._browser)
        state = _session.wait_ready(page, self.settings)
        if os.path.dirname(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(page.content())
        return state

    def dump_room(self, ref: int | str | Room, path: str = "session/dumps/line_room.html") -> Room:
        """Open a room then save its DOM for message-selector tuning."""
        import os

        room = self.open_room(ref)
        assert self._page is not None
        if os.path.dirname(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self._page.content())
        return room

    def probe_session(self) -> dict:
        """Redacted storage probe: shows where the login token lives.

        Key names with type and length only, never secret values.
        Use the result to decide keepalive vs token-restore work.
        """
        from . import auth as _auth
        from . import probe as _probe

        page = self._ready_page()
        logged_in, reason = _auth.check_login(page, self.settings.login_poll_ms)
        data = _probe.probe_extension_storage(page)
        data["logged_in"] = logged_in
        data["login_reason"] = reason
        data["targets"] = _probe.list_line_targets(self.settings)
        return data

    def save_probe(self, path: str = "session/session_probe.json") -> str:
        """Run probe_session and save JSON. The only probe method that writes."""
        data = self.probe_session()
        _storage.save_json(path, data)
        return path

    def save_rooms(
        self,
        path: str = "session/rooms.json",
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
        out = path or f"session/messages_{room.index}.json"
        _storage.save_json(out, {
            "room": asdict(room),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "messages": [asdict(m) for m in msgs],
        })
        return out


__all__ = ["LineClient", "LineError"]
