# Changelog

## Unreleased

- Layered package: `config`, `domain`, `browser`, `scraper`, `output`, `service`. Imports flow one way with no cycles, and only `line_ext_msg/__init__.py` exposes the public API
- Split the two god modules: `messages.py` (731 lines) became `scraper/{messages,scroll,extract,media}.py`, and `client.py` (417 lines) became `service/{client,readiness,diagnostics,maintenance}.py`
- All `page.evaluate` snippets now live in `browser/js.py` and take a single args object; a test scans that module to keep the single-argument rule
- Default output paths centralized in `config/paths.py`; `SESSION_DIR` moved there from storage
- `SELECTORS` split out of `Settings` into `config/selectors.py`
- OS-specific code (locate Chrome, force kill, expand, profile lock) isolated in `browser/process.py`
- Smooth headless/headed switching: new `browser/mode.py` state machine (`current`, `converge`) that closes Chrome gracefully via CDP `Browser.close` before falling back to a force kill, and verifies the mode after start with one retry
- Headless QR login: when a QR is needed the login canvas is captured from the headless page and shown in a small Tk dialog (`LINE QR`, 2x zoom, `--qr-zoom`/`LINE_EXT_MSG_QR_ZOOM` to change) that refreshes the QR itself. No Chrome window is popped, so the run stays headless throughout
- The QR dialog has no buttons and no timeout: it waits until the QR is scanned or the window is closed with the X, which records a cancel and stops the wait
- QR capture is more robust: it polls for a non-empty canvas data URI, then reloads the page once and retries before falling back to a headed window. Canvas lookup now tries the QR container, then the login page, then the largest square canvas on the page
- `--debug-qr` (env `LINE_EXT_MSG_DEBUG_QR`) prints redacted login-page diagnostics (containers, canvas sizes, data length) when capture fails; `LINE_EXT_MSG_QR_READY_MS` tunes the wait (default 20s)
- Missing extension: instead of opening the Web Store in a hidden headless tab and exiting, the CLI now pops a headed window, opens the Web Store, waits until the extension folder appears on disk, then returns to headless and continues the same run. Waiting stops when the extension is installed or the user closes Chrome. The install switch does not open the blocked LINE page and closes leftover blocked extension tabs, so only the Web Store tab is visible
- The dialog runs as a separate process (`service.qr_view`) driven by `session/qr.png` and `session/qr_status.json`, so Tkinter never shares a thread with the sync Playwright API. When the QR canvas cannot be captured the flow falls back to a headed window
- The dialog also shows the verification PIN: after the QR is scanned the extension opens a PIN modal (`pinCodeModal`), and the dialog displays that code so it can be typed into the phone. It switches back to the QR image when the flow returns to it
- Dialog redesign: a light card with the LINE header, a colored status pill, and a large spaced PIN. It re-centers on the primary screen whenever its content changes size, DPI awareness keeps text crisp, and the copy was trimmed to the essentials
- Session reality: the token stays in Local Storage (`lcs_secure_<mid>`, about 3.2 KB) across restarts, but the key that decrypts it lives in the extension's sandboxed `ltsmSandbox.html`, which has no persistent storage, so a fresh Chrome always asks for the QR again. Startup therefore never restarts a live Chrome to match the preferred mode; a running instance is reused and stays logged in, so the QR is scanned once per Chrome lifetime
- Accurate headless detection reads the full CDP version payload (User-Agent), not the Browser string only
- Tooling: `py.typed`, ruff, mypy, and a windows-latest CI workflow. Shared test helpers live in `tests/helpers.py` with `tests/conftest.py`, and tests mirror the package layout

## 1.2.0

- Headless by default: Chrome runs with `--headless=new` (`LINE_EXT_MSG_HEADLESS=1`); `--headed` forces a visible window, `--headless` forces quiet mode
- Headed fallback for QR: when the login screen shows and waiting is allowed, the client pops a headed window for the scan only and stays headed for that run (no kill-before-flush); the next run returns to headless quietly
- Session probe: `probe_session`/`save_probe` report redacted storage (key names with type and length only, never secrets) plus CDP targets; CLI `--probe-session` writes `session/session_probe.json`, `--status` checks keepalive without picking a room
- Session findings: the login token persists on disk (`lcs_secure` in Local Storage survives full kills), so closing debug Chrome no longer always means re-login; `--clear-session` (with confirm, `--yes` to skip) wipes only extension storage and keeps the install, backing up a probe first
- Startup tabs: Chrome opens straight at `#/chats` and startup noise (`chrome://newtab`, welcome, blank) is closed via CDP, so LINE stays tab 1
- Outputs under `session/`: probes, `rooms.json`, `messages_*.json`, `media/`, and `dumps/` all live under `session/` (auto-created, git-ignored); `storage.save_json` creates parent dirs
- Port conflicts: CDP squatter hint (`netstat -ano | findstr <port>`, `LINE_EXT_MSG_PORT`) attached to `ChromeNotReady`; mode mismatches restart in the expected mode instead of failing
- Windows console fix: checklist uses ASCII `-` prefix (cp874 has no box-drawing glyph)

## 1.1.0

- Message backfill: `get_messages` scrolls the chat up until `limit` rows render (bounded by `LINE_EXT_MSG_MSGS_SCROLL_MS`, default 8s), stops early past `date_from`; `scroll=False` or `--no-scroll-msgs` restores on-screen-only reads
- Backfill honesty fix: top-reached is read before scrolling (not after setting it), scroll moves one viewport per round with 1000ms settle, stops only after 5 steady rounds at the real top, prints progress and stop reason when not quiet
- Correctness fix: room DOM is newest-first (verified in two room dumps), so `limit` now slices from the head (`out[:limit]`); previously it returned the oldest rendered rows
- Accumulation fix: messages merge into a SeenMap every scroll round, so newest rows unloaded mid-scroll (e.g. Sep 12 messages lost while backfilling) stay in the result; full extraction runs only when the rendered id signature changes, and images download once per id
- System rows: strip glued clock prefix (`3:43 PMw.siri...` to `w.siri...`), omit the empty `sender: ` prefix in CLI output, and exclude system rows from `sender_stats`
- Backfill wake-up: nudge down-and-up when parked at the top (a no-op set fires no scroll event, starving the loader), track `scrollHeight` alongside count, scale time budget with `need` (150ms each, 30s cap), report round count in the stop line; `--scroll-budget-s` overrides the base budget
- Hotfix: `_scroll_up_one` JS took two params but Playwright passes one arg, so every scroll threw into a bogus `detached` stop with zero rounds; scripts now take a single object, guarded by a test scanning all top-level evaluate arrows
- Scroll the right box: accept `overflow: overlay` (what LINE reports) and prefer `chatroomContent-module__content_area` directly; log the chosen box each run; when sets stop moving anything, fall back to a real `mouse.wheel` over the list (up to 3 pokes)
- Excursion instead of nudges: parked at the top, dive two viewports deep and return to the edge so edge-triggered loaders wake up; track the `data-scroll-date` anchor as loader-activity signal; log every wheel attempt
- Spike tooling: shared scroll-box picker prefers a box that is really scrollable (height-checked) instead of assuming the selector; box log now shows clientHeight; `--debug-scroll` (or `LINE_EXT_MSG_DEBUG_SCROLL=1`) prints per-round top/height/count/have/date telemetry
- Park instead of yank: parked at the top, hold scrollTop at 0 and give the loader quiet time; transient probe failures burn one step and retry instead of aborting as `detached`; wheel fallback dips down first then back up to re-enter the top edge
- Direction probe: measure whether scrollTop goes negative (column-reverse world) before looping, scroll and stop at the correct older edge per direction, accept negative tops instead of reporting `detached`; box state now carries clientHeight too
- Stride scrolling: each round covers half the remaining distance (1-4 viewports) instead of one fixed viewport, so a 13kpx box reaches its edge in ~5 rounds; the time budget is now a last-resort guard (need * 1000ms, 300s cap) and the loop runs until need/top/date stops it
- Faster text reads: message `_text` timeout 3000ms down to 500ms
- Login session note: the extension keeps its token in restart-scoped secure storage (verified: profile, storage.local, and IndexedDB all persist on disk, yet a relaunch still shows QR), so closing the debug window always means logging in again; README corrected (was: login once) and the CLI prints a keep-the-window-open tip after each fetch

## 1.0.0

First stable release: OOP facade, extended schema, filters, search, media.

- `Message.media_data`: opt-in data URI (`include_media_data=True`) for MCP/AI image analysis
- Download image bubbles to `media/` via in-page blob fetch; `Message.media` holds the path
- CLI shows `[รูปภาพ: path]` / `[สติกเกอร์]` instead of blank lines

- Filters: `date_from/date_to`, `time_from/time_to` (`HH:MM`), `sender`, `keyword` in `get_messages`/`save_messages`/CLI
- `search_all()` keyword search grouped per room, `unread_full()` unread rooms + today's messages
- `sender_stats()` pure per-sender counts; `apply_filters()` unit-tested without browser

- Explicit save: `get_*`/`list_*` never write files; only `save_rooms`/`save_messages` do
- CLI `--save` flag (default prints to screen only)
- Removed `export_room` (use `save_messages`)

- OOP rewrite: `LineClient` facade owns lifecycle (context manager)
- Models: `Room{index,id,name,unread,last_preview,last_time}`,
  `Message{id,date,ts,sender,from_me,type,text,read_count}`, `StepResult`
- Typed errors: `LoginRequired`, `ExtensionMissing`, `RoomNotFound`, ...
- `Settings` dataclass (env `LINE_EXT_MSG_*`) replaces config constants
- `open_room` accepts index, data-mid, name substring, or Room
- `get_messages(room?, limit, date?)`, `unread_digest()`, `export_room()`
- CLI flags: `--date`, `--unread`; `Steps` supports `quiet`
- Removed: `browser.py`, `chrome_launcher.py`, `config.py` (now `session.py`, `chrome.py`, `settings.py`)

## 0.1.0

- Restructured to `src/line_ext_msg` package with `line-ext-msg` CLI entry point
- Checklist startup: Chrome debug, CDP attach, extension, render, login
- Room listing, latest-N message export to JSON (timestamp + sender + text)
- Library API for MCP reuse: `list_rooms`, `get_latest_messages`
