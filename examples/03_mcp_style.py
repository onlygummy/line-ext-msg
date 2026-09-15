"""03 - MCP-style function: no CLI, no input(), returns dict.

This is the shape an MCP server (separate repo) can import directly:
    from line_ext_msg import LineClient

Run: uv run python examples/03_mcp_style.py
"""
from dataclasses import asdict

from line_ext_msg import LineClient
from line_ext_msg.domain.errors import LineError


def get_messages(room_name: str, limit: int = 5) -> dict:
    """Return latest messages of the first room matching room_name."""
    try:
        with LineClient(quiet=True) as line:
            line.status()
            room = line.open_room(room_name)
            msgs = line.get_messages(limit=limit)
            return {"ok": True, "room": asdict(room),
                    "messages": [asdict(m) for m in msgs]}
    except LineError as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def unread_digest() -> dict:
    """Rooms with unread messages plus latest preview."""
    try:
        with LineClient(quiet=True) as line:
            line.status()
            return {"ok": True, "rooms": line.unread_digest()}
    except LineError as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    import json

    print(json.dumps(get_messages("ครอบครัว"), ensure_ascii=False, indent=2))
