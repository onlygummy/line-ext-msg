"""Thin CLI over LineClient: parse args, print results.

Results go to stdout; progress and diagnostics go through logging on
stderr, so piping the results stays clean.
"""
import argparse
import logging
import sys

from .config import paths
from .config.settings import Settings
from .domain.errors import LineError
from .domain.models import Room
from .output.logging import configure
from .service.client import LineClient


def _oneline(text: str) -> str:
    """Join a message for terminal output: newlines become spaces.

    Stored Message.text and JSON files keep the original line breaks;
    only screen output is flattened.
    """
    return " ".join((text or "").splitlines())


def _display(m) -> str:
    """Full text on one line, or a media label when the bubble has no text."""
    if m.text:
        return _oneline(m.text)
    if m.type == "image":
        return f"[image: {m.media or 'download failed'}]"
    if m.type == "sticker":
        return "[sticker]"
    if m.type == "system":
        return _oneline(m.text)
    return f"[{m.type}]"


def _display_dict(m: dict) -> str:
    """Dict version of _display for search hits (plain dicts, not Message)."""
    text = _oneline(m.get("text") or "")
    if text:
        return text
    if m.get("type") == "image":
        return f"[image: {m.get('media') or 'download failed'}]"
    if m.get("type") == "sticker":
        return "[sticker]"
    return f"[{m.get('type')}]"


def _who(sender: str) -> str:
    """Sender prefix for one output line; system rows have none."""
    return f"{sender}: " if sender else ""


def pick_room(rooms: list[Room]) -> Room:
    """Show rooms in the terminal and return the user choice."""
    print("\nChat rooms:")
    for r in rooms:
        unread = f" ({r.unread} unread)" if r.unread else ""
        print(f"  [{r.index}] {r.name}{unread}")
    while True:
        raw = input("Room number > ").strip()
        if raw.isdigit() and any(r.index == int(raw) for r in rooms):
            return next(r for r in rooms if r.index == int(raw))
        print("Invalid number, try again")


def ask_limit(default: int = 5) -> int:
    """Ask how many messages to fetch. Empty = default, 0 = all rendered."""
    while True:
        raw = input(f"How many messages (default {default}, 0=all) > ").strip()
        if not raw:
            return default
        if raw.isdigit():
            return int(raw)
        print("Invalid number, try again")


def _configure_logging(args) -> None:
    """Pick the log level from the flags and attach handlers."""
    level = logging.INFO
    if args.verbose:
        level = logging.DEBUG
    elif args.quiet_log:
        level = logging.WARNING
    if args.log_level:
        level = getattr(logging, args.log_level.upper(), level)
    if args.debug_scroll or args.debug_qr:
        level = min(level, logging.DEBUG)
    configure(level, log_file=args.log_file)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pull messages from the LINE Chrome Extension")
    parser.add_argument("--limit", type=int, default=None,
                        help="number of latest messages (ask when picking a room if omitted)")
    parser.add_argument("--date", default=None, help="only this day, YYYY-MM-DD")
    parser.add_argument("--date-from", default=None, help="from this day, YYYY-MM-DD")
    parser.add_argument("--date-to", default=None, help="up to this day, YYYY-MM-DD")
    parser.add_argument("--time-from", default=None, help="from this time, HH:MM")
    parser.add_argument("--time-to", default=None, help="up to this time, HH:MM")
    parser.add_argument("--sender", default=None, help="filter sender name (substring)")
    parser.add_argument("--keyword", default=None, help="search text (substring)")
    parser.add_argument("--search", default=None, metavar="KEYWORD",
                        help="search every room and summarise the hits")
    parser.add_argument("--unread", action="store_true", help="only rooms with unread messages")
    parser.add_argument("--save", action="store_true",
                        help="write session/rooms.json and session/messages_*.json (default: screen only)")
    parser.add_argument("--dump", action="store_true",
                        help="save the raw DOM for selector tuning (session/dumps/)")
    parser.add_argument("--dump-room", type=int, default=None, metavar="INDEX",
                        help="open room INDEX and save its DOM for message selector tuning (session/dumps/)")
    parser.add_argument("--wait-login", dest="wait_login", action="store_true", default=None,
                        help="wait on the login screen until login finishes (default)")
    parser.add_argument("--no-wait-login", dest="no_wait_login", action="store_true",
                        help="stop as soon as the login screen shows")
    parser.add_argument("--login-timeout-s", type=float, default=None, metavar="SEC",
                        help="timeout for the headed fallback (default 300); the QR dialog waits until closed")
    parser.add_argument("--no-scroll-msgs", dest="no_scroll_msgs", action="store_true",
                        help="read only what is on screen, do not scroll back")
    parser.add_argument("--scroll-budget-s", type=float, default=None, metavar="SEC",
                        help="base scroll budget in seconds (default 8)")
    parser.add_argument("--search-scroll-budget-s", dest="search_scroll_budget_s", type=float,
                        default=None, metavar="SEC",
                        help="lower bound in seconds for the per-room scroll budget when a "
                             "filter is set (default 60); --limit raises it further")
    parser.add_argument("--debug-scroll", dest="debug_scroll", action="store_true", default=None,
                        help="log scroll telemetry each round")
    parser.add_argument("--status", action="store_true",
                        help="check Chrome and login, then stop (keepalive check)")
    parser.add_argument("--probe-session", action="store_true",
                        help="write a redacted session/session_probe.json to see where the token lives")
    parser.add_argument("--headless", dest="headless", action="store_true", default=None,
                        help="run Chrome without a window (default)")
    parser.add_argument("--headed", dest="headed", action="store_true",
                        help="start Chrome with a window (for the QR scan)")
    parser.add_argument("--qr-zoom", dest="qr_zoom", type=int, default=None, metavar="N",
                        help="zoom the QR in the dialog N times (default 2, range 1-4)")
    parser.add_argument("--dialog-title", dest="dialog_title", default=None, metavar="TEXT",
                        help="window title and header text of the QR dialog (default LINE)")
    parser.add_argument("--debug-qr", dest="debug_qr", action="store_true", default=None,
                        help="log login-page diagnostics when the QR capture fails (no secrets)")
    parser.add_argument("--verbose", action="store_true", help="log at DEBUG level")
    parser.add_argument("--quiet-log", dest="quiet_log", action="store_true",
                        help="log only warnings and errors")
    parser.add_argument("--log-level", dest="log_level", default=None,
                        choices=["debug", "info", "warning", "error"],
                        help="explicit log level (overrides --verbose/--quiet-log)")
    parser.add_argument("--log-file", dest="log_file", default=None, metavar="PATH",
                        help="also write detailed logs to this file")

    # Subcommands are optional: every query flag above must keep working on
    # its own, so `line-ext-msg --unread` must not require a command.
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    logout_parser = sub.add_parser(
        "logout",
        help="log out of LINE in the debug profile (keeps the extension)",
        description="Log out of LINE in the debug profile. Wipes the session and "
                    "keeps the extension installed.")
    logout_parser.add_argument("--yes", action="store_true",
                               help="skip the confirmation")
    return parser


def _settings_from_args(args) -> Settings | None:
    overrides: dict = {}
    if args.login_timeout_s is not None:
        overrides["login_wait_ms"] = int(args.login_timeout_s * 1000)
    if args.scroll_budget_s is not None:
        overrides["messages_scroll_ms"] = int(args.scroll_budget_s * 1000)
    if args.search_scroll_budget_s is not None:
        overrides["search_scroll_ms"] = int(args.search_scroll_budget_s * 1000)
    if args.debug_scroll:
        overrides["debug_scroll"] = True
    if args.headed:
        overrides["headless"] = False
    elif args.headless:
        overrides["headless"] = True
    if args.qr_zoom is not None:
        overrides["qr_zoom"] = args.qr_zoom
    if args.dialog_title is not None:
        overrides["dialog_title"] = args.dialog_title
    if args.debug_qr:
        overrides["debug_qr"] = True
    return Settings(**overrides) if overrides else None


def main():
    parser = _build_parser()
    args = parser.parse_args()
    _configure_logging(args)

    wait_flag = None
    if args.no_wait_login:
        wait_flag = False
    elif args.wait_login:
        wait_flag = True
    wait_ms = int(args.login_timeout_s * 1000) if args.login_timeout_s is not None else None
    settings = _settings_from_args(args)

    try:
        with LineClient(settings) as line:
            # Logout runs before status(): it must work while logged out, and
            # status() now waits for the QR by default.
            if args.command == "logout":
                if not args.yes:
                    raw = input("Log out of LINE in the debug profile? Type yes to confirm > ").strip()
                    if raw.lower() not in ("yes", "y"):
                        print("Cancelled, nothing removed")
                        return
                summary = line.logout(backup=True)
                print(f"Logged out: backup={summary.get('backup')} wiped={summary.get('wiped')}")
                return
            if args.dump:
                dom = line.dump_page()
                print(f"Saved {dom.save(paths.PAGE_DUMP)} (state={dom.state}). Send this file to tune selectors.")
                return
            line.status(wait_for_login=wait_flag, login_timeout_ms=wait_ms)
            if args.status:
                print("Chrome + LINE ready (keepalive OK; closing the CLI keeps Chrome running)")
                return
            if args.probe_session:
                data = line.probe_session()
                print(f"Saved {data.save(paths.PROBE_JSON)} (redacted, key names only)")
                print(f"login={data.get('logged_in')} session_keys={len(data.get('session_keys', {}))} "
                      f"local_keys={len(data.get('local_keys', {}))} targets={len(data.get('targets', []))}")
                return
            if args.dump_room is not None:
                dom = line.dump_room(args.dump_room)
                room_name = dom.room.name if dom.room is not None else "?"
                print(f"Saved {dom.save(paths.ROOM_DUMP)} (room {room_name}). Send this file to tune message selectors.")
                return
            rooms = line.list_rooms(unread_only=args.unread)
            if not rooms:
                print(f"Could not read the room list. Run --dump and send {paths.PAGE_DUMP}.")
                return
            if args.save:
                print(f"Saved {rooms.save(paths.ROOMS_JSON)} ({len(rooms)} rooms)")
            if args.search:
                partial: list[str] = []
                for hit in line.search_all(args.search,
                                           date_from=args.date_from or args.date,
                                           date_to=args.date_to or args.date):
                    name = hit["room"]["name"]
                    print(f"\n== {name} ({len(hit['messages'])} messages) ==")
                    if hit.get("truncated"):
                        partial.append(name)
                        print("   (partial: the scroll budget ran out before the oldest message)")
                    for m in hit["messages"]:
                        print(f"[{m['date']} {m['ts']}] {_who(m['sender'])}{_display_dict(m)}")
                # A room that hit the budget may match further back, so say so
                # rather than letting an empty list read as "no match".
                if partial:
                    print(f"\nPartial scan, search further back with a bigger budget "
                          f"(--search-scroll-budget-s): {', '.join(partial)}")
                return
            chosen = pick_room(rooms)
            limit = max(0, args.limit) if args.limit is not None else ask_limit()
            filt = dict(limit=limit, date=args.date, date_from=args.date_from,
                        date_to=args.date_to, time_from=args.time_from, time_to=args.time_to,
                        sender=args.sender, keyword=args.keyword,
                        with_media=True, scroll=not args.no_scroll_msgs)
            print(f"Opening room {chosen.name} ...", flush=True)
            msgs = line.get_messages(chosen, **filt)
            if not msgs:
                print("Opened the room but could not read messages")
                print(f"Run line-ext-msg --dump-room {chosen.index} and send {paths.ROOM_DUMP}")
                return
            msgs = msgs.download_media(paths.MEDIA_DIR)
            if args.save:
                print(f"Saved {msgs.save(paths.messages_json(chosen.index))}")
            for m in msgs:
                print(f"[{m.date} {m.ts}] {_who(m.sender)}{_display(m)}")
            print("Tip: keep the debug Chrome window open to avoid logging in again", flush=True)
    except KeyboardInterrupt:
        print("\nCancelled while waiting")
    except LineError as e:
        print(e, file=sys.stderr)


if __name__ == "__main__":
    main()
