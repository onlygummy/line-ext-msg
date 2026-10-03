"""08 - Embed the library: render the QR yourself, and watch a scan run.

This is the shape an MCP server or a web backend needs. The library's Tk QR
dialog only works for a human sitting at the machine, so a host that needs to
put the QR in front of its own user passes on_qr and on_pin instead and never
lets a window open.

Two things make that safe. Supplying a callback suppresses the dialog, so
nothing pops up on a server that has no desktop. And login_timeout_ms bounds
the wait, which matters more here than with the dialog: without a window there
is no user who can close it, so the timeout is the only thing that ends the
wait besides a successful login.

Run: uv run python examples/08_embed_login.py --room "Family"

Note there is no LINE session in the demo: on_qr and on_pin just print what
they received, which is enough to see the wiring.
"""

import argparse
import json

from line_ext_msg import LineClient, LoginTimeout, ScanProgress

# What a real host would keep per session and hand to its own UI. Printing it
# stands in for "send this to the client that is asking".
challenge: dict = {}


def on_qr(data_uri: str) -> None:
    """Receive the login QR as a PNG data URI."""
    challenge["qr"] = data_uri
    print(f"[qr] data URI, {len(data_uri)} chars "
          f"(send this to your client as an <img src=...>)")


def on_pin(pin: str, desc: str) -> None:
    """Receive the verification PIN to type on the phone."""
    challenge["pin"] = pin
    print(f"[pin] {pin} - {desc or 'type this on the phone'}")


def on_status(state: str) -> None:
    """Receive the phases that carry no payload of their own.

    The one that matters is "verifying". After the code is submitted, LINE
    moves to a view of its own and recovering takes a few seconds. A host that
    keeps showing the code through that stretch looks like it hung, so drop the
    payload and show a spinner instead. The absence of an event means keep
    whatever you have, which is why there is no "go back to the PIN" event.
    """
    if state == "verifying":
        challenge.pop("qr", None)
        challenge.pop("pin", None)
        print("[status] submitted; LINE is switching views, nothing to do")
        return
    # done | failed | cancelled
    print(f"[status] {state}")


def on_progress(tick: ScanProgress) -> None:
    """One tick per room, carrying the truncated flag with it."""
    flag = " (partial)" if tick.truncated else ""
    print(f"[{tick.index}/{tick.total}] {tick.room.name}: {tick.matched} hits{flag}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Drive the login UI from the host.")
    parser.add_argument("--room", help="room to read once logged in")
    parser.add_argument("--timeout-s", type=float, default=180.0,
                        help="bound the login wait (default 180)")
    args = parser.parse_args()

    # wait_for_login is deliberately left unset here: this example wants the
    # wait. An unattended caller would pass wait_for_login=False instead, and
    # then a missing session raises LoginRequired rather than opening a flow.
    with LineClient(on_qr=on_qr, on_pin=on_pin, on_status=on_status) as line:
        try:
            line.status(login_timeout_ms=int(args.timeout_s * 1000))
        except LoginTimeout:
            # Reached when nobody scanned in time. Decide what that means for
            # your product: alert, queue for later, or drop the session.
            print(f"no login within {args.timeout_s:.0f}s; "
                  f"challenge was {'sent' if challenge else 'never needed'}")
            return
        print("logged in")

        if args.room:
            msgs = line.get_messages(args.room, limit=10)
            print(json.dumps([{"date": m.date, "sender": m.sender, "text": m.text}
                              for m in msgs], indent=2))

        # A search walks rooms one at a time, so on_progress is what makes it
        # observable instead of a silence that lasts minutes.
        report = line.search_all("invoice", on_progress=on_progress)
        partial = [hit["room"]["name"] for hit in report if hit["truncated"]]
        print(f"\n{len(report)} room(s) matched, {len(partial)} partial")


if __name__ == "__main__":
    main()