# line-ext-msg

Pull messages (time + sender + text + date + read count) from the LINE Chrome Extension through Playwright. Ships as a Python library (`LineClient`) and a thin CLI. It attaches to your real Chrome and your own account, read-only.

## Install

```powershell
pip install line-ext-msg
```

Google Chrome must be installed. You do not need `playwright install`: the library attaches to the running Chrome over CDP and never uses the bundled chromium. Windows only for now.

## Quick start

```python
from line_ext_msg import LineClient

with LineClient(quiet=True) as line:
    line.status(wait_for_login=True)  # shows the QR dialog if a login is needed
    for room in line.list_rooms(unread_only=True):
        print(room.name, room.unread)
    for m in line.get_messages("Family", limit=20, keyword="invoice"):
        print(m.date, m.sender, m.text)
```

`LineClient` is a context manager. On first use it starts (or reuses) the debug Chrome on an isolated profile, and on exit it only detaches: Chrome keeps running so the session survives for the next run.

## LineClient at a glance

| Method | Returns | Notes |
|---|---|---|
| `status(wait_for_login=None, login_timeout_ms=None)` | `list[StepResult]` | runs the 5 readiness checks; raises a typed `LineError` on the first failure |
| `list_rooms(unread_only=False, query=None)` | `list[Room]` | `query` matches the room name substring |
| `open_room(ref)` | `Room` | `ref` is an index, a `data-mid`, a name substring, or a `Room` |
| `get_messages(room=None, limit=5, ...)` | `list[Message]` | date/time, sender, and keyword filters; optional media download |
| `unread_digest()` | `list[dict]` | rooms with `unread > 0`, as room dicts |
| `unread_full(date=None, limit_per_room=20)` | `list[dict]` | unread rooms with their messages (`date=None` means today) |
| `search_all(keyword, date_from=None, date_to=None, rooms=None, limit_per_room=100)` | `list[dict]` | every room that matched, one room at a time |
| `save_rooms(path=..., unread_only=False, query=None)` | `str` | writes JSON, returns the path |
| `save_messages(ref, path=None, ...)` | `str` | opens the room, writes JSON, returns the path |
| `dump_page(path=...)`, `dump_room(ref, path=...)` | `str` / `Room` | save raw DOM for selector tuning |
| `probe_session()`, `save_probe(path=...)` | `dict` / `str` | redacted storage probe (key names and lengths only) |
| `clear_session(backup=True)` | `dict` | wipes the LINE session, keeps the extension |
| `close()` | `None` | detaches CDP; Chrome keeps running |

`get_messages` also accepts `date`, `date_from`, `date_to`, `time_from`, `time_to`, `sender`, `keyword`, `media_dir`, `include_media_data`, and `scroll`.

## Recipes

Filter by date and keyword, then count senders:

```python
from line_ext_msg import LineClient, sender_stats

with LineClient(quiet=True) as line:
    line.status()
    msgs = line.get_messages("Work", date_from="2026-09-01", keyword="invoice")
    for row in sender_stats(msgs):
        print(row["sender"], row["count"])
```

Download image bubbles and embed them as data URIs (useful for AI pipelines):

```python
with LineClient(quiet=True) as line:
    line.status()
    msgs = line.get_messages("Family", limit=50, media_dir="media", include_media_data=True)
    for m in msgs:
        if m.type == "image":
            print(m.media, len(m.media_data))  # local path and data URI
```

Save results to JSON (`save_*` are the only methods with side effects on disk):

```python
with LineClient(quiet=True) as line:
    line.status()
    rooms_path = line.save_rooms(unread_only=True)
    msgs_path = line.save_messages("Family", limit=100)
    print(rooms_path, msgs_path)
```

Handle failures with typed errors:

```python
from line_ext_msg import LineClient, LineError, LoginRequired, RoomNotFound

with LineClient(quiet=True) as line:
    try:
        line.status()
        room = line.open_room("Family")
    except LoginRequired:
        ...   # not logged in; see Authentication and session
    except RoomNotFound as e:
        print(e.available)   # the room names that were visible
    except LineError as e:
        ...   # any other typed failure
```

## Authentication and session

`status()` runs five checks (Chrome, CDP attach, extension, page ready, login) and raises a typed error on the first failure: `ChromeNotReady`, `AttachFailed`, `ExtensionMissing`, `AppNotReady`, `LoginRequired`, or `QrDialogFailed`.

- With `quiet=True` (recommended for a service) it does not block: if no one is logged in it raises `LoginRequired` right away.
- With `status(wait_for_login=True)` it shows the QR in a small Tk dialog on the machine, waits until you scan or close it, and asks for the PIN code on the phone when LINE requires it. Use `login_timeout_ms` to bound the wait.

The dialog is currently the only login UI: there is no callback yet for an embedding app to fetch the QR image or the PIN and render it itself. A headless service should either keep a logged-in Chrome running, or run once interactively to log in and then reuse that instance.

The LINE session is tied to the running Chrome process, not to disk. The token stays in Local Storage (`lcs_secure_<mid>`, about 3.2 KB), but the key that decrypts it lives in the extension's sandboxed `ltsmSandbox.html`, which has no persistent storage, so a fresh Chrome asks for the QR again. The library therefore never restarts a running Chrome just to match a preferred mode: a live instance is reused and stays logged in, so you scan the QR once per Chrome lifetime. Closing Chrome or rebooting requires a new scan. `clear_session()` wipes the session on purpose.

## Logging

The library emits nothing on import (it carries a `NullHandler`). To see progress and diagnostics, configure the package logger:

```python
import logging
from line_ext_msg.output.logging import configure

configure(logging.INFO)   # attaches a stderr handler to the "line_ext_msg" logger
```

Or attach your own handlers to the `line_ext_msg` logger. The CLI configures it for you and adds `--verbose` (DEBUG), `--quiet-log` (WARNING and above), `--log-level {debug,info,warning,error}`, and `--log-file PATH`. Results go to stdout; logs go to stderr.

## Models and JSON

`Room` (frozen dataclass): `index`, `id` (data-mid), `name`, `unread`, `last_preview`, `last_time`.

`Message` (frozen dataclass): `id`, `date` (`YYYY-MM-DD`), `ts` (ISO 8601), `sender`, `from_me`, `type` (`text` / `sticker` / `image` / `system` / `file`), `text`, `read_count`, `media` (local path), `media_data` (data URI, opt-in).

`StepResult` (frozen dataclass): `name`, `passed`, `detail`. Both models serialize with `dataclasses.asdict`.

`save_messages` writes this shape:

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

`unread_digest`, `unread_full`, and `search_all` return plain dicts (room dicts, and `{"room": ..., "messages": [...]}` for the latter two), not models.

## Settings

All knobs live in the frozen `Settings` dataclass and can be set in code or through environment variables.

```python
from line_ext_msg import LineClient, Settings

settings = Settings(headless=True, qr_zoom=3, quiet=True)
with LineClient(settings) as line:
    ...
```

| Environment variable | Default | Meaning |
|---|---|---|
| `LINE_EXT_MSG_PROFILE` | `%LOCALAPPDATA%\line-chrome-debug` | isolated debug profile |
| `LINE_EXT_MSG_PORT` | `9222` | CDP debug port |
| `LINE_EXT_MSG_HEADLESS` | `1` | run Chrome without a window |
| `LINE_EXT_MSG_QUIET` | off | do not wait, keep the checklist silent |
| `LINE_EXT_MSG_QR_ZOOM` | `2` | QR dialog zoom (1-4) |
| `LINE_EXT_MSG_QR_READY_MS` | `20000` | how long to wait for the QR canvas |
| `LINE_EXT_MSG_ROOMS_SCROLL_MS` | `4000` | room list scroll budget |
| `LINE_EXT_MSG_MSGS_SCROLL_MS` | `8000` | message backfill scroll budget |
| `LINE_EXT_MSG_LOGIN_WAIT_MS` | `300000` | login wait for the headed fallback |
| `LINE_EXT_MSG_READY_MS` | `30000` | app render timeout |
| `LINE_EXT_MSG_SELECTOR_MS` | `15000` | selector wait timeout |
| `LINE_EXT_MSG_OPEN_MS` | `3000` | fallback wait after opening a room |

## CLI

The same client is exposed as a thin CLI. Results print to stdout and progress goes to stderr.

```powershell
line-ext-msg                        # pick a room in the terminal, print to screen only
line-ext-msg --save                 # also write session/rooms.json and session/messages_<index>.json
line-ext-msg --unread               # only rooms with unread messages
line-ext-msg --search "invoice"     # search every room and summarise the hits
line-ext-msg --status               # check Chrome and login, then stop (keepalive)
line-ext-msg --verbose              # DEBUG logs
line-ext-msg --help                 # full flag list
```

On first run the CLI starts Chrome on the isolated profile. If the LINE extension is missing it opens a headed window at the Web Store, waits until the extension is installed, then returns to headless by itself. When a QR scan is needed it captures the QR and shows it in a centered `LINE` dialog (zoom via `LINE_EXT_MSG_QR_ZOOM`), waits until you scan or close it, and shows the PIN code when LINE asks for one. `--clear-session` wipes the session (asks for confirmation).

## Limitations

- Room and message lists are virtualized; the library scrolls to load more within a time budget. Disable with `scroll=False` or set the scroll budget to 0.
- Only what the UI renders is readable; there is no per-message read API.
- `unread_digest`, `unread_full`, and `search_all` return dicts, not models.
- The QR dialog is the only login UI; there is no callback for an app to render the QR itself.
- The session is tied to the running Chrome process, so keep Chrome alive to avoid scanning again.
- `from_me` is a heuristic (no username means your own message) and is not yet confirmed with a dump that contains your own messages.
- Windows only for now: Chrome discovery and process control use Windows paths and PowerShell.

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

## Troubleshooting

If rooms cannot be read after a LINE UI update, save the DOM and send it to tune the selectors:

```powershell
line-ext-msg --dump             # chats DOM -> session/dumps/line_dom.html
line-ext-msg --dump-room 0      # room DOM  -> session/dumps/line_room.html
# selectors live in src/line_ext_msg/config/selectors.py
```

Add `--debug-qr` when the QR capture fails; it logs redacted login-page diagnostics.
