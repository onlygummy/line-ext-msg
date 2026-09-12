"""01 - List all LINE chat rooms.

Prerequisites: Chrome + LINE Extension installed + logged in
(profile %LOCALAPPDATA%\\line-chrome-debug).

Run: uv run python examples/01_list_rooms.py
"""
from line_ext_msg import LineClient


def main() -> None:
    with LineClient() as line:
        line.status()
        for room in line.list_rooms():
            unread = f" ({room.unread} ไม่อ่าน)" if room.unread else ""
            print(f"[{room.index}] {room.name}{unread}")


if __name__ == "__main__":
    main()
