"""06 - Run unattended: a scheduler, a bot, a CI job.

Two rules matter here.

The wait policy belongs on the constructor. quiet=True only silences the
startup checklist, and it never meant fail-fast; wait_for_login=False is what
makes this unattended. Setting it once means no call site can forget it, and a
method that runs status() on its own cannot quietly start waiting for a human
who is not there.

Before running this, log in once by hand and leave that Chrome up:

    uv run line-ext-msg     # scan the QR, then Ctrl+C

The session lives in the Chrome process, so keeping that process alive between
runs is what avoids a new QR every time. close() only detaches; it never kills
Chrome.

Run: uv run python examples/06_headless_service.py --room "Family"
"""

import argparse
import logging
import sys

from line_ext_msg import (
    ChatsViewMissing,
    LineClient,
    LineError,
    LoginRequired,
    RoomNotFound,
    Settings,
)

logger = logging.getLogger("example-service")


def fetch(room_ref: str, limit: int = 20):
    """Read a room and return the Messages result."""
    # quiet keeps the five-step checklist off stdout, which matters when
    # stdout is a pipe and only your results should travel through it.
    settings = Settings(quiet=True)

    with LineClient(settings, wait_for_login=False) as line:
        # wait_for_login=False is what makes this unattended: the QR path is
        # skipped entirely and a missing session raises LoginRequired at once.
        line.status()
        room = line.open_room(room_ref)
        msgs = line.get_messages(room, limit=limit)

        # A truncated backfill is not an error, it is a caveat. Log it and let
        # the caller decide whether partial data is good enough.
        if msgs.scroll_stop == "budget":
            logger.warning("%s: backfill hit the scroll budget, results are partial", room.name)
        return msgs


def main() -> int:
    # Progress goes through logging, never print: a service usually has no
    # terminal, and stdout is often reserved for results.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Read one room without a terminal.")
    parser.add_argument("--room", required=True, help="room name substring, index, or data-mid")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    try:
        msgs = fetch(args.room, args.limit)
    except LoginRequired:
        # No session at all. Report it and exit; waiting would hang the job.
        logger.error("no LINE session available. Log in once by hand with line-ext-msg")
        return 2
    except ChatsViewMissing:
        # The tab is on some other view, so rooms cannot be read at all. This
        # is usually a LINE UI change: run --dump and look at the DOM.
        logger.error("the LINE tab is not on the chats view; run line-ext-msg --dump")
        return 3
    except RoomNotFound as e:
        logger.error("no room matched %r; visible: %s", e.ref, ", ".join(e.available) or "-")
        return 4
    except LineError as e:
        # Every failure in this library is a LineError subclass, so one except
        # clause is a safe catch-all. Branch on the type when the difference
        # matters, as above.
        logger.error("%s: %s", type(e).__name__, e)
        return 1

    for m in msgs:
        text = " ".join(m.text.split())[:60]
        print(f"{m.date} {m.sender or 'me'}: {text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())