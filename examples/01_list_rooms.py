"""01 - List the chat rooms LINE knows about.

Shows the two list filters and, more importantly, which Room field is safe
to keep: id is stable, index is not.

Run: uv run python examples/01_list_rooms.py

Everything in this example imports from the top-level package only. The
subpackages under line_ext_msg are implementation details, so reaching into
them is what breaks first on an upgrade.
"""

from line_ext_msg import LineClient


def main() -> None:
    # The context manager is the normal way in. Leaving the block detaches
    # from Chrome and leaves the browser running, which is what keeps the
    # session alive for the next run.
    with LineClient() as line:
        # status() runs the five readiness checks once. Call it before looping
        # so a broken setup fails immediately instead of half way through.
        line.status()

        rooms = line.list_rooms()
        print(f"{len(rooms)} rooms\n")
        for room in rooms:
            unread = f"  {room.unread} unread" if room.unread else ""
            print(f"[{room.index}] {room.name}{unread}")
            print(f"      id  {room.id}")
            if room.last_preview:
                print(f"      last {room.last_time}  {' '.join(room.last_preview.split())}")

        # Keep room.id, never room.index. id is the LINE data-mid and means the
        # same conversation on every run; index is only where the row happened
        # to sit in the rendered list, so it points at a different room as soon
        # as anything is added, removed or reordered.
        #
        # The list is virtualized, so list_rooms scrolls to load more within
        # rooms_scroll_ms. A long chat list may not fully fit in that budget.

        unread_rooms = line.list_rooms(unread_only=True)
        print(f"\n{len(unread_rooms)} rooms with unread messages")
        for room in unread_rooms:
            print(f"  {room.name} ({room.unread})")

        # query is a plain case-sensitive substring test on the name. Note the
        # difference from open_room("name"), which matches case-insensitively.
        matches = line.list_rooms(query="LINE")
        print(f"\n{len(matches)} rooms whose name contains 'LINE'")
        for room in matches:
            print(f"  {room.name}")


if __name__ == "__main__":
    main()