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

## Embedding

A host that is not an interactive terminal needs two things the plain API cannot give it: a login it can render itself, and progress on a scan that takes a minute per room.

```python
from line_ext_msg import LineClient, ScanProgress

pending: dict = {}          # what the host shows the user

def on_qr(data_uri: str) -> None:
    pending["qr"] = data_uri         # a PNG data URI, send it to your client

def on_pin(pin: str, desc: str) -> None:
    pending["pin"] = pin             # the code to type on the phone

def on_status(state: str) -> None:
    if state == "verifying":
        pending.pop("qr", None)      # submitted; nothing left for the user to do
        pending.pop("pin", None)
    else:                            # done | failed | cancelled
        pending.clear()

def on_progress(tick: ScanProgress) -> None:
    print(f"{tick.index}/{tick.total} {tick.room.name}: {tick.matched} hits"
          + (" (partial)" if tick.truncated else ""))

with LineClient(on_qr=on_qr, on_pin=on_pin,
                on_status=on_status) as line:
    try:
        line.status(login_timeout_ms=180_000)   # bounded, raises LoginTimeout
    except LoginTimeout:
        return send_login_challenge(pending["qr"], pending["pin"])
    report = line.search_all("invoice", on_progress=on_progress)
```

Four rules cover it:

- `wait_for_login` on the constructor is the policy for the whole client, so a query that triggers `status()` on its own cannot quietly start waiting for a human. Precedence is the `status()` argument, then the constructor value, then waiting.
- Supplying any login callback replaces the Tk dialog rather than adding to it, because on a server there is no desktop for a window. Set `on_qr` to receive the QR and `on_pin` to receive the code. Return `False` from either to end the wait.
- `on_status` carries only the phases that have no payload of their own. A host keeps showing its last `on_qr` or `on_pin` value until one arrives, which is why there is no "go back to the PIN" event.
- Every callback is a trust boundary: an exception in one is logged and ignored, so a bug in the host's rendering cannot strand a login.

### Login phases

The Tk dialog and `on_status` share one vocabulary. The viewer renders the same names, so the two renderers cannot drift apart.

| State | Pill | What the user sees | Terminal |
|---|---|---|---|
| `waiting` | Waiting | the QR, "Scan with the LINE app" | no |
| `pin` | Enter code | the code, "Enter this code in the LINE app" | no |
| `verifying` | Signing in | a spinner, "LINE is opening your chats" | no |
| `done` | Done | nothing, the window closes | yes |
| `failed` | Could not continue | nothing, the window closes | yes |
| `cancelled` | Cancelled | nothing, the window closes | yes |

`verifying` is not cosmetic. Once the code is submitted, LINE moves to a view of its own that is neither the login screen nor the chat list, and recovering from that takes a few seconds. Showing the submitted code through that stretch reads as a hang. A timeout or an unmatched page closes the dialog as `failed` rather than `cancelled`, because the user did not close anything.

## LineClient at a glance

| Method | Returns | Notes |
|---|---|---|
| `status(wait_for_login=None, login_timeout_ms=None)` | `list[StepResult]` | runs the 5 readiness checks, waits for the QR by default, then makes sure the chats view is the one rendered; raises a typed `LineError` on the first failure |
| `list_rooms(unread_only=False, query=None)` | `Rooms` | `list[Room]`; `query` matches the room name substring |
| `open_room(ref)` | `Room` | `ref` is an index, a `data-mid`, a name substring, or a `Room` |
| `get_messages(room=None, limit=5, ...)` | `Messages` | `list[Message]`; date/time, sender, and keyword filters |
| `unread_digest()` | `Report` | rooms with `unread > 0`, as room dicts |
| `unread_full(date=None, limit_per_room=20, on_progress=None)` | `Report` | unread rooms with their messages (`date=None` means today) |
| `search_all(keyword, date_from=None, date_to=None, rooms=None, limit_per_room=100, on_progress=None)` | `Report` | every room that matched, one room at a time |
| `dump_page()` | `Dom` | raw chats DOM for selector tuning |
| `dump_room(ref)` | `Dom` | opens the room and returns its DOM |
| `probe_session()` | `Probe` | redacted storage probe (key names and lengths only) |
| `logout(backup=True)` | `dict` | logs out of LINE, wipes the session, stops the debug Chrome, keeps the extension |
| `clear_session(backup=True)` | `dict` | deprecated alias for `logout()`, kept for 1.x and 2.x callers |
| `close()` | `None` | detaches CDP; Chrome keeps running |

`get_messages` also accepts `date`, `date_from`, `date_to`, `time_from`, `time_to`, `sender`, `keyword`, `with_media`, and `scroll`.

### Results and saving

Queries never touch disk. They return a small result type that subclasses the plain builtin (`Rooms` and `Messages` are lists, `Report` is a list of dicts, `Probe` is a dict, `Dom` is a str) and adds `.save(path)`, which writes the file and returns the path. `Messages` also carries `.room` and a `.download_media(dir)` helper.

```python
rooms = line.list_rooms(unread_only=True)   # no I/O
rooms.save("session/rooms.json")            # writes {"rooms": [...]}

msgs = line.get_messages("Family", with_media=True)  # images in memory
msgs = msgs.download_media("session/media")          # writes the image files
msgs.save("session/messages.json")                   # writes room + fetched_at + messages
```

Upgrading from 1.x: the old `save_rooms`, `save_messages`, and `save_probe` methods are gone, and `get_messages` no longer takes `media_dir` or `include_media_data`. Call `.save(path)` on the result instead, and move image fetching to `with_media=True` plus `download_media(dir)`. `clear_session` is a deprecated alias for `logout()` and logs a warning; it is kept so 1.x and 2.x callers keep working, and will be removed in a future major version.

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
    msgs = line.get_messages("Family", limit=50, with_media=True)
    msgs = msgs.download_media("media", include_data=True)
    for m in msgs:
        if m.type == "image":
            print(m.media, len(m.media_data))  # local path and data URI
```

Save results to JSON (`.save` is the only step with side effects on disk):

```python
with LineClient(quiet=True) as line:
    line.status()
    rooms_path = line.list_rooms(unread_only=True).save("session/rooms.json")
    msgs_path = line.get_messages("Family", limit=100).save("session/messages.json")
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

`status()` runs five checks (Chrome, CDP attach, extension, page ready, login) and raises a typed error on the first failure: `ChromeNotReady`, `AttachFailed`, `ExtensionMissing`, `AppNotReady`, `LoginRequired`, `LoginTimeout`, or `QrDialogFailed`.

- `status()` waits by default: when no one is logged in it shows the QR in a small Tk dialog on the machine, waits until you scan or close it, and asks for the PIN code on the phone when LINE requires it.
- `login_timeout_ms` bounds that wait, dialog or callback driven. On expiry the call raises `LoginTimeout`, which is a `LoginRequired` subclass: catch it first when the two cases need different handling, since "no session stored" and "session needed but nobody scanned in time" call for different responses. A value of `0` or less skips the QR attempt entirely and fails fast with `LoginRequired`.
- With `status(wait_for_login=False)` it does not block: if no one is logged in it raises `LoginRequired` right away. Pass `wait_for_login=False` to the constructor instead and every method that needs a ready page inherits it.

The Tk dialog is the built-in login UI. To render the QR yourself, pass `on_qr` (and `on_pin`) to the constructor; see [Embedding](#embedding). Supplying any of them suppresses the dialog, so set `on_qr` to get the QR.

The LINE session is tied to the running Chrome process, not to disk. The token stays in Local Storage (`lcs_secure_<mid>`, about 3.2 KB), but the key that decrypts it lives in the extension's sandboxed `ltsmSandbox.html`, which has no persistent storage, so a fresh Chrome asks for the QR again. The library therefore never restarts a running Chrome just to match a preferred mode: a live instance is reused and stays logged in, so you scan the QR once per Chrome lifetime. Closing Chrome or rebooting requires a new scan. `logout()` wipes the session on purpose.

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

`Messages.save` writes this shape (room and `fetched_at` only when the result knows its room):

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

`unread_digest`, `unread_full`, and `search_all` return a `Report` (a list of dicts: room dicts, and `{"room": ..., "messages": [...], "truncated": ...}` for the latter two), not models.

### Partial scans

A filtered query has no target row count, so the backfill scroll runs until the oldest message, a date boundary, or the time budget. When the budget runs out first the result is partial, and the library says so instead of letting an empty list read as "no match":

- `search_all` and `unread_full` entries carry `truncated: true` for those rooms, and a truncated room is listed even when it matched nothing
- `line-ext-msg --search` prints which rooms were partial and how to dig deeper
- `Messages.scroll_stop` carries the raw reason: `need`, `top`, `date`, `budget`, `disabled`, or `detached`

Raise `search_scroll_ms` (or pass `--search-scroll-budget-s`) when a room keeps coming back truncated. It is a lower bound, so raising it past `limit * 1000ms` has no effect; raise `limit_per_room` for a bigger scan, and `scroll_cap_ms` if the limit is what runs into the ceiling. `unread_full` and `search_all` also accept `on_progress`, which reports each room as it is read along with the same `truncated` flag.

An `unread_full` entry can come back with no messages while the room still shows unread, because the unread ones predate `date`. Compare `room["unread"]` with the message count before reading an empty list as "nothing pending".

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
| `LINE_EXT_MSG_EXTENSION` | the published LINE id | extension id to open and to require on disk |
| `LINE_EXT_MSG_HEADLESS` | `1` | run Chrome without a window |
| `LINE_EXT_MSG_QUIET` | off | keep the checklist silent |
| `LINE_EXT_MSG_QR_ZOOM` | `2` | QR dialog zoom, clamped to 1-4 |
| `LINE_EXT_MSG_DIALOG_TITLE` | `LINE` | window title of the QR dialog |
| `LINE_EXT_MSG_QR_READY_MS` | `20000` | how long to wait for the QR canvas |
| `LINE_EXT_MSG_ROOMS_SCROLL_MS` | `8000` | room list scroll budget |
| `LINE_EXT_MSG_CHATS_ENSURE_MS` | `10000` | how long to wait for the chat list after switching to the chats view |
| `LINE_EXT_MSG_MSGS_SCROLL_MS` | `8000` | message backfill scroll budget |
| `LINE_EXT_MSG_SEARCH_SCROLL_MS` | `60000` | lower bound for the per-room scroll budget when a filter is set (keyword, sender, date); the `limit` raises it further, so 0 does not disable scrolling |
| `LINE_EXT_MSG_SCROLL_CAP_MS` | `300000` | ceiling on the budget the `limit` asks for; 0 or less removes it |
| `LINE_EXT_MSG_LOGIN_MS` | `10000` | how long the login state check waits before it gives up |
| `LINE_EXT_MSG_LOGIN_WAIT_MS` | `300000` | login wait, for the headed fallback and the QR dialog alike |
| `LINE_EXT_MSG_READY_MS` | `30000` | app render timeout |
| `LINE_EXT_MSG_SELECTOR_MS` | `15000` | selector wait timeout |
| `LINE_EXT_MSG_OPEN_MS` | `3000` | fallback wait after opening a room |
| `LINE_EXT_MSG_STOP_GRACEFUL_MS` | `3000` | how long a graceful Chrome close may take before the force kill |
| `LINE_EXT_MSG_READY_SETTLE_MS` | `200` | extra settle after the app looks ready |
| `LINE_EXT_MSG_DEBUG_QR` | off | log redacted login-page diagnostics when the QR capture fails |
| `LINE_EXT_MSG_DEBUG_SCROLL` | off | log scroll telemetry each round |
| `LINE_EXT_MSG_DEBUG_ROOMS` | off | log the ids of room rows skipped for having no name |

## CLI

The same client is exposed as a thin CLI. Results print to stdout and progress goes to stderr.

```powershell
line-ext-msg                        # pick a room in the terminal, print to screen only
line-ext-msg --save                 # also write session/rooms.json and session/messages_<index>.json
line-ext-msg --unread               # only rooms with unread messages
line-ext-msg --search "invoice"     # search every room and summarise the hits
line-ext-msg --search "invoice" --search-scroll-budget-s 180   # dig deeper per room
line-ext-msg --status               # check Chrome and login, then stop (keepalive)
line-ext-msg --verbose              # DEBUG logs
line-ext-msg logout                 # log out of LINE and wipe the session
line-ext-msg --help                 # full flag list
```

On first run the CLI starts Chrome on the isolated profile. If the LINE extension is missing it opens a headed window at the Web Store, waits until the extension is installed, then returns to headless by itself. When a QR scan is needed it captures the QR and shows it in a centered `LINE` dialog (zoom via `LINE_EXT_MSG_QR_ZOOM`), waits until you scan or close it, and shows the PIN code when LINE asks for one. The `logout` subcommand wipes the session and asks for confirmation; `logout --yes` skips the prompt.

## Limitations

- Room and message lists are virtualized; the library scrolls to load more within a time budget. Disable with `scroll=False` or `LINE_EXT_MSG_MSGS_SCROLL_MS=0`; those are the only off switches, since a filtered query raises its own budget from `search_scroll_ms` and the `limit`.
- A filtered query stops at the oldest message, a date, or its budget, whichever comes first. Its budget is `max(search_scroll_ms, min(limit * 1000ms, scroll_cap_ms))`, so it is never shorter than the unfiltered one. A search over a long history can report `truncated` rather than pretending it reached the beginning.
- Only the chats view is read. The friends and groups view is never used as a room list, so a LINE build that only offers that view raises `ChatsViewMissing` instead of returning names that are not conversations.
- Only what the UI renders is readable; there is no per-message read API.
- `unread_digest`, `unread_full`, and `search_all` return a `Report` (list of dicts), not models.
- `download_media` only writes what `with_media=True` already fetched; it does not re-open the room.
- Supplying a login callback replaces the Tk dialog, so set `on_qr` to receive the QR and `on_pin` to receive the code. Set none to keep the dialog.
- Debug Chrome starts with `--disable-notifications` and `--hide-crash-restore-bubble`, so web and push notifications stay off and the restore bubble never appears after a force kill. Toasts an extension raises through `chrome.notifications` are not covered.
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
  output/    JSON and text storage, checklist logger, logging setup
  results.py savable query results: Rooms, Messages, Report, Probe, Dom
  service/   LineClient facade, readiness, diagnostics, QR dialog
  cli.py     entry point
```

Each layer may import only the ones listed below. `domain` is the shared
vocabulary (models and typed errors), so every layer may import it.

| Layer | May import |
| --- | --- |
| `config` | nothing |
| `domain` | nothing |
| `output` | `config`, `domain` |
| `results` | `domain`, `output` |
| `browser` | `config`, `domain` |
| `scraper` | `config`, `domain`, `browser`, `results` |
| `service` | every layer above |
| `cli` | `service`, `config`, `domain`, `output` |

`results` is the savable result layer, so `scraper` reaches `output` (the file
writers) through it.

The public API is only `line_ext_msg/__init__.py` (`LineClient`, `Room`, `Message`, `StepResult`, `Rooms`, `Messages`, `Report`, `Probe`, `Dom`, `Settings`, `sender_stats`, and the typed errors). Subpackages are implementation details and may change without notice.

## Development

```powershell
uv sync --extra dev
uv run ruff check src tests
uv run mypy
uv run pytest
uv build
```

## Troubleshooting

If the room list shows names that are people or groups rather than conversations, or comes back empty, the LINE tab is not on the chats view. `status()` logs which view it reached and the URL it saw (`chats view: navigated, url=...`); a `ChatsViewMissing` error means neither the chats URL nor the nav button produced a chat list. The friends view is never read as a room list, so that mix-up fails instead of returning wrong data.

If the login log repeats `login state: unknown` after the PIN step, the QR scan succeeded but the page landed on a view the library does not read. The login flow retries the chats route twice on its own and raises `AppNotReady` pointing at `--dump` if that does not help, so a run never sits there waiting.

If rooms cannot be read after a LINE UI update, save the DOM and send it to tune the selectors:

```powershell
line-ext-msg --dump             # chats DOM -> session/dumps/line_dom.html
line-ext-msg --dump-room 0      # room DOM  -> session/dumps/line_room.html
# selectors live in src/line_ext_msg/config/selectors.py
```

Add `--debug-qr` when the QR capture fails; it logs redacted login-page diagnostics.
