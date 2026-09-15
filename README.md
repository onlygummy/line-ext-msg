# line-ext-msg

Pull messages (time + sender + text + date + read count) from the LINE Chrome Extension through Playwright. It attaches to your real Chrome and your own account, read-only.

## Install

```powershell
pip install line-ext-msg
```

Google Chrome must be installed. You do not need `playwright install`: the tool attaches to the running Chrome over CDP and never uses the bundled chromium.

## CLI

```powershell
line-ext-msg                       # pick a room in the terminal, print to screen only
line-ext-msg --save                # also write session/rooms.json and session/messages_<index>.json
line-ext-msg --unread              # only rooms with unread messages
line-ext-msg --limit 10 --date 2026-09-12
line-ext-msg --date-from 2026-09-01 --date-to 2026-09-12 --keyword "invoice"
line-ext-msg --search "invoice"    # search every room and summarise the hits
line-ext-msg --status              # check Chrome and login, then stop (keepalive)
line-ext-msg --probe-session       # write a redacted session/session_probe.json
line-ext-msg --qr-zoom 3           # zoom the QR in the dialog 3 times (default 2, range 1-4)
line-ext-msg --debug-qr            # log login-page diagnostics when the QR capture fails
line-ext-msg --verbose             # DEBUG logs (--quiet-log, --log-level, --log-file too)
line-ext-msg --clear-session       # wipe the LINE session (asks for confirmation)
```

First run: the tool starts Chrome on an isolated profile at `%LOCALAPPDATA%\line-chrome-debug` (Chrome 136+ ignores `--remote-debugging-port` on the default profile). If the LINE extension is missing it opens a headed window at the Web Store, waits until the extension is installed, then returns to headless by itself.

It normally runs headless with no Chrome window. When a QR scan is needed it captures the QR from the login page and shows it in a centered `LINE` dialog (2x zoom, change with `--qr-zoom` or `LINE_EXT_MSG_QR_ZOOM`). The dialog waits until you scan or close it (the X). If LINE then asks for a verification code, the dialog switches to show that code so you can type it on the phone, and goes back to the QR only when a genuinely new QR appears.

Before falling back to a headed Chrome window (`--headed` forces a window, `--headless` forces quiet), it waits for the QR canvas, then reloads the page once and retries, because a reused SPA can get stuck. Add `--debug-qr` to see why a capture failed, and tune the wait with `LINE_EXT_MSG_QR_READY_MS` (default 20000). All output files live under `session/` (git-ignored).

Mode switching closes Chrome gracefully over CDP first and only force-kills as a fallback.

The LINE session is tied to the running Chrome process, not to disk. The token stays in Local Storage (`lcs_secure_<mid>`, about 3.2 KB), but the key that decrypts it lives in the extension's sandboxed `ltsmSandbox.html`, which has no persistent storage, so a fresh Chrome asks for the QR again. The tool therefore never restarts a running Chrome just to match a preferred mode: a live instance is reused and stays logged in, so you scan the QR once per Chrome lifetime (closing Chrome or rebooting requires a new scan). `--headless`/`--headed` only apply when a fresh Chrome starts.

### Logging

Results go to stdout; progress and diagnostics go to stderr through the `line_ext_msg` logger. The CLI configures it for you. Flags: `--verbose` (DEBUG), `--quiet-log` (WARNING and above), `--log-level {debug,info,warning,error}`, and `--log-file PATH` for a detailed log. Embedding applications configure the same logger through `line_ext_msg.output.logging.configure`, or attach their own handlers; importing the package emits nothing.

## JSON output

```json
{
  "room": { "index": 0, "id": "CXX...", "name": "Family", "unread": 3,
            "last_preview": "did you eat", "last_time": "8:13 AM" },
  "fetched_at": "2026-09-12T01:00:00+00:00",
  "messages": [
    { "id": "0178...", "date": "2026-09-12", "ts": "2026-09-12T08:13:00",
      "sender": "Mom", "from_me": false, "type": "text",
      "text": "did you eat", "read_count": null }
  ]
}
```

## Limitations

- Room and message lists are virtualized; the tool scrolls to load more within a time budget (`LINE_EXT_MSG_ROOMS_SCROLL_MS`, `LINE_EXT_MSG_MSGS_SCROLL_MS`). Disable with `--no-scroll-msgs` or set the value to 0.
- Only what the UI renders is readable; there is no per-message read API.
- The session is tied to the running Chrome process. When a new login is needed the tool shows the QR in the `LINE` dialog. Wipe the session with `--clear-session` (keeps the extension).
- `from_me` is a heuristic (no username means your own message) and is not yet confirmed with a dump that contains your own messages.
- Windows only for now. Chrome discovery and process control use Windows paths and PowerShell.

## Project layout

The package is split into layers with one-way imports and no cycles.

```
src/line_ext_msg/
  config/    settings, constants, and default paths (no I/O)
  domain/    models, typed errors, pure filters (no browser)
  browser/   everything that touches Chrome/Playwright: process, CDP, login, mode, JS
  scraper/   DOM to models: scroll, extract, media, rooms, messages
  output/    JSON storage, checklist logger, logging setup
  service/   LineClient facade, readiness, diagnostics, QR dialog
  cli.py     entry point
```

The public API is only `line_ext_msg/__init__.py` (`LineClient`, `Room`, `Message`, `StepResult`, `Settings`, `sender_stats`, and the typed errors). Subpackages are implementation details and may change without notice.

## Development

```powershell
uv sync --extra dev
uv run ruff check src tests
uv run mypy
uv run pytest
uv build
```

## If rooms cannot be read (LINE UI update)

```powershell
line-ext-msg --dump             # chats DOM -> session/dumps/line_dom.html
line-ext-msg --dump-room 0      # room DOM  -> session/dumps/line_room.html
# send the file to tune the selectors in src/line_ext_msg/config/selectors.py
```
