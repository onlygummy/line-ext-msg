"""02 - Export latest messages of one room to JSON.

Run: uv run python examples/02_latest_messages.py --room "Family" --limit 5
"""
import argparse

from line_ext_msg import LineClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--room", required=True, help="Room name substring")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    with LineClient() as line:
        line.status()
        msgs = line.get_messages(args.room, limit=args.limit, with_media=True)
        msgs = msgs.download_media("session/media")
        print(f"Saved {msgs.save('session/messages.json')}")


if __name__ == "__main__":
    main()
