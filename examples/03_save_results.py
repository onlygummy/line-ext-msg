"""03 - Save results to disk.

No query writes anything. .save(path) is the only step that creates a file,
which is what makes a read-only call safe to run anywhere: nothing appears on
disk unless you ask for it.

Run: uv run python examples/03_save_results.py --room "Family"
"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from line_ext_msg import LineClient, RoomNotFound


def main() -> None:
    parser = argparse.ArgumentParser(description="Save rooms and messages as JSON.")
    parser.add_argument("--room", default="", help="room name substring; empty takes the first room")
    parser.add_argument("--out", default="session", help="output directory (default session)")
    args = parser.parse_args()

    # Pick your own paths. The library has a session/ convention of its own, but
    # line_ext_msg.config.paths is not public API, so do not import it.
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with LineClient() as line:
        line.status()

        # Rooms.save writes {"rooms": [...]}. The result is a plain list, so you
        # can also filter it yourself and skip the helper entirely.
        rooms = line.list_rooms(unread_only=True)
        print(f"wrote {rooms.save(str(out / 'unread_rooms.json'))} ({len(rooms)} rooms)")

        try:
            room = line.open_room(args.room) if args.room else line.list_rooms()[0]
        except RoomNotFound as e:
            print(f"No room matched {e.ref!r}. Visible: {', '.join(e.available) or '-'}")
            return

        msgs = line.get_messages(room, limit=100)

        # Messages.save writes {"room": ..., "fetched_at": ..., "messages": [...]}.
        # The room and fetched_at keys are only there because get_messages was
        # given a Room object; read messages without one and the file holds
        # nothing but "messages", which is hard to interpret a week later.
        print(f"wrote {msgs.save(str(out / 'messages.json'))}")

        # save() is a convenience, not a boundary. The models are plain frozen
        # dataclasses, so build whatever shape the rest of your system wants.
        # Note the room id here, not the index.
        snapshot = {
            "room_id": room.id,
            "room_name": room.name,
            "truncated": msgs.scroll_stop == "budget",
            "messages": [asdict(m) for m in msgs],
        }
        path = out / "snapshot.json"
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {path} (own shape, room keyed by id)")


if __name__ == "__main__":
    main()