"""05 - Search across rooms, and read the result honestly.

The point of this example is the truncated check. A filtered query has no
target row count, so loading older history is bounded by time. When the bound
wins, the room was not searched to the end, and "no match" is not something
the result can tell you. Always read the flag before you conclude anything.

Run: uv run python examples/05_search.py "invoice" --from 2026-09-01
"""

import argparse

from line_ext_msg import LineClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Search every room for a keyword.")
    parser.add_argument("keyword")
    parser.add_argument("--from", dest="date_from", help="only from this day, YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", help="only up to this day, YYYY-MM-DD")
    parser.add_argument("--limit-per-room", type=int, default=100,
                        help="rows to aim for per room (default 100). This is what "
                             "sets the scroll budget, so raising it searches deeper")
    args = parser.parse_args()

    with LineClient() as line:
        line.status()

        # The three ways to sweep rooms, cheapest first.
        #
        # unread_digest reads the room list once and never opens a room.
        digest = line.unread_digest()
        print(f"{len(digest)} rooms have unread messages")

        # unread_full opens every unread room in turn, so it costs seconds each.
        full = line.unread_full(limit_per_room=20)
        print(f"{len(full)} unread rooms read, {sum(len(h['messages']) for h in full)} messages")

        # search_all is the same walk with a keyword filter, and it is the most
        # expensive call in the library: one room open plus one scroll per room.
        report = line.search_all(
            args.keyword,
            date_from=args.date_from,
            date_to=args.date_to,
            limit_per_room=args.limit_per_room,
        )

        # A Report is a plain list of dicts shaped
        # {"room": {...}, "messages": [...], "truncated": bool}, so it drops
        # straight into json.dumps or .save().
        incomplete = []
        for hit in report:
            room = hit["room"]
            print(f"\n== {room['name']}: {len(hit['messages'])} matches ==")
            if hit["truncated"]:
                incomplete.append(room["name"])
                # Zero matches plus truncated means "not reached", not
                # "not there". The room is listed precisely so this is visible.
                print("   partial: the scroll budget ran out before the oldest message")
            for m in hit["messages"]:
                text = " ".join(m["text"].split())[:60]
                print(f"   {m['date']}  {m['sender'] or 'me'}: {text}")

        if incomplete:
            # Raising search_scroll_ms above limit_per_room * 1000ms changes
            # nothing, because the budget is the larger of the two. Raise
            # limit_per_room instead.
            print(f"\n{len(incomplete)} room(s) not searched to the end: {', '.join(incomplete)}")
            print("Raise --limit-per-room to search them deeper.")

        # Rooms that matched nothing AND were searched completely are left out of
        # the report, which is why its length is not the room count.
        print(f"\n{len(report)} room(s) in the report out of {len(line.list_rooms())} rooms")


if __name__ == "__main__":
    main()