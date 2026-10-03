"""07 - Log out of LINE.

Wipes the LINE session from the debug profile and keeps the extension, so the
next run asks for a QR again. This deletes data. It is not a cleanup call and
not a way to fix a broken session.

Before running it for real, know that after this every run needs a fresh QR
scan until a Chrome stays up.

Run: uv run python examples/07_logout.py          (asks first)
     uv run python examples/07_logout.py --yes    (no prompt)
"""

import argparse
import json

from line_ext_msg import LineClient, LineError


def main() -> None:
    parser = argparse.ArgumentParser(description="Log out of LINE in the debug profile.")
    parser.add_argument("--yes", action="store_true",
                        help="skip the confirmation; this really deletes the session")
    args = parser.parse_args()

    # Confirm before anything is destroyed. The CLI equivalent is
    # `line-ext-msg logout`, which asks the same question.
    if not args.yes:
        answer = input("Log out of LINE in the debug profile? Type yes to confirm > ").strip()
        if answer.lower() not in ("yes", "y"):
            print("Cancelled, nothing removed")
            return

    try:
        with LineClient() as line:
            # backup=True saves a redacted snapshot of the session storage
            # first, so you can see where the login lived if you need to debug
            # it later. It holds key names and sizes, never secret values.
            #
            # Logout works on a logged-out profile, which is why it runs before
            # any status() call that would wait for a QR.
            summary = line.logout(backup=True)
    except LineError as e:
        print(f"Logout failed: {type(e).__name__}: {e}")
        return

    # logout() reports what each step managed instead of raising, so read it.
    #   backup      path of the redacted snapshot, absent if it failed
    #   wiped       which storage folders were deleted on disk
    #   *_error     a step failed while the others still carried on
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if summary.get("backup_error") or summary.get("live_error"):
        print("Some steps failed, see the errors above. Chrome was still stopped.")

    print("The next run will show the QR dialog again.")


if __name__ == "__main__":
    main()