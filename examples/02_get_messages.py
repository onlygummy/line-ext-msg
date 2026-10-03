"""02 - Read messages from one room and summarise them.

Shows how to point at a room, what to do when it is not there, and how to
turn the result into something you can count.

Run: uv run python examples/02_get_messages.py "Family" --limit 50
"""

import argparse

from line_ext_msg import LineClient, RoomNotFound, Settings, sender_stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Read one room.")
    parser.add_argument("room", help="room name substring, index, or data-mid")
    parser.add_argument("--limit", type=int, default=20,
                        help="how many messages to return (default 20)")
    parser.add_argument("--date", help="only this day, YYYY-MM-DD")
    parser.add_argument("--sender", help="only messages from this sender")
    parser.add_argument("--budget-s", type=float, default=None,
                        help="seconds to spend loading older messages (default 8)")
    args = parser.parse_args()

    # Settings is the single place for runtime knobs. Every field also reads a
    # LINE_EXT_MSG_* environment variable, so anything not set here can still
    # come from outside the process.
    if args.budget_s is None:
        settings = Settings()
    else:
        settings = Settings(messages_scroll_ms=int(args.budget_s * 1000))

    with LineClient(settings) as line:
        line.status()

        # A room can be named by substring, by index, by data-mid, or passed as
        # a Room object from list_rooms(). Name matching is case-insensitive.
        try:
            room = line.open_room(args.room)
        except RoomNotFound as e:
            # e.available is the list of rooms that were actually visible,
            # which usually answers the question better than the message does.
            print(f"No room matched {e.ref!r}. Rooms that were visible:")
            for name in e.available:
                print(f"  {name}")
            return

        # Give get_messages the Room object rather than a name: it skips a second
        # lookup, and it means the result knows where it came from, so
        # Messages.save() can record the room. Without it, a call with no room
        # argument reads whichever room happens to be open.
        msgs = line.get_messages(room, limit=args.limit, date=args.date, sender=args.sender)

        if not msgs:
            print(f"{room.name}: nothing matched.")
            return

        # scroll_stop says why loading older messages ended: 'need' means the
        # limit was reached, 'top' means the oldest message was reached, 'date'
        # means it stopped at a date boundary. 'budget' is the one to act on,
        # because it means there is more history that was not read.
        print(f"{room.name}: {len(msgs)} messages (backfill ended on {msgs.scroll_stop})\n")
        for m in msgs:
            who = m.sender or "me"
            text = " ".join(m.text.split())[:70]
            print(f"{m.date} {m.ts[11:16]}  {who}: {text}")

        # Messages is a plain list and Message is a plain frozen dataclass, so
        # there is nothing to unwrap before you sort, group or serialise them.
        #
        # sender is empty on your own messages and from_me is a heuristic based
        # on that, so treat it as a hint rather than a fact.
        print("\nby sender")
        for row in sender_stats(msgs):
            print(f"  {row['sender']}: {row['count']}")


if __name__ == "__main__":
    main()