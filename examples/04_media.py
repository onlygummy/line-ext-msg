"""04 - Fetch image messages and decide what to keep.

Media is opt-in and comes in two steps: fetch into memory, then write only
what you want on disk. Nothing is saved until the second step runs.

Run: uv run python examples/04_media.py "Family" --out session/media
"""

import argparse
from pathlib import Path

from line_ext_msg import LineClient, RoomNotFound


def main() -> None:
    parser = argparse.ArgumentParser(description="Download image bubbles.")
    parser.add_argument("room", help="room name substring, index, or data-mid")
    parser.add_argument("--limit", type=int, default=20,
                        help="how many messages to scan (default 20)")
    parser.add_argument("--out", default="session/media", help="image directory")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with LineClient() as line:
        line.status()
        try:
            room = line.open_room(args.room)
        except RoomNotFound as e:
            print(f"No room matched {e.ref!r}. Visible: {', '.join(e.available) or '-'}")
            return

        # with_media=True fetches every image bubble in the window and keeps it
        # as a data URI in memory. No file is created. The cost is one round
        # trip per image, so keep the limit small unless you really need them
        # all: this is the expensive flag in the whole library.
        msgs = line.get_messages(room, limit=args.limit, with_media=True)

        images = [m for m in msgs if m.type == "image" and m.media_data]
        print(f"{len(images)} image messages out of {len(msgs)} in {room.name}")
        if not images:
            return

        # download_media writes the files and returns a NEW Messages. Message is
        # a frozen dataclass, so entries are rebuilt rather than mutated, and the
        # original result is left untouched.
        #
        # The default include_data=False then drops the data URI from each entry,
        # which is what you want once the bytes are on disk.
        saved = msgs.download_media(str(out))
        print("\nwrote to disk, data URIs dropped:")
        for m in saved:
            if m.type == "image":
                print(f"  {Path(m.media).name}  media={m.media}  media_data={m.media_data!r}")

        # include_data=True keeps the data URI alongside the written file. That
        # is what an AI pipeline wants, because the bytes are already in the
        # payload and there is no second read.
        inline = msgs.download_media(str(out / "inline"), include_data=True)
        ready = [m for m in inline if m.type == "image" and m.media_data]
        print(f"\n{len(ready)} entries keep both the file and the data URI")
        if ready:
            head = ready[0]
            print(f"  {head.date}  {len(head.media_data)} chars, starts {head.media_data[:32]}")


if __name__ == "__main__":
    main()