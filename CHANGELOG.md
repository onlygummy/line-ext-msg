# Changelog

## 3.1.0

Everything here is additive. No signature changed shape, no return value lost a field, and code written against 3.0.0 runs unchanged.

### Fixes

- `login_timeout_ms` now bounds the QR wait it claims to bound. The value reached only the headed fallback: `_qr_login` took no timeout and looped until the QR was scanned, the dialog was closed, or the page matched no known view, so a host that passed `login_timeout_ms=180000` and got nothing back after three minutes had no way to tell a three minute wait from an infinite one. The budget now covers the whole wait and expiry raises the new `LoginTimeout` instead of a bare `LoginRequired`, because "no session is stored" and "a session is needed but nobody scanned in time" call for different responses in an embedding app. `LoginTimeout` subclasses `LoginRequired`, so existing handlers keep catching it
- The 300 second scroll ceiling is now `scroll_cap_ms` (`LINE_EXT_MSG_SCROLL_CAP_MS`). It was hardcoded in two places, so a room with a long archive stayed pinned to five minutes per query and reported `truncated: true` forever with no knob to raise it. The same number capped both the limit-derived budget and the search budget, so one setting now covers both. `0` or less removes the ceiling and lets `limit` decide
- `qr_zoom` is clamped to the 1-4 range the README documents. Nothing enforced it, and Tk's `PhotoImage.zoom` rejects values outside it inside the viewer process, which runs with its output discarded, so `--qr-zoom 0` produced a blank dialog and no error anywhere
- The scroll budget formula in the README said `limit * 1000s` in one place and `limit * 1000ms` in another; the code has always been milliseconds, so an embedder sizing its own timeouts from the seconds version would have been wrong by a factor of a thousand
- The environment variable table was missing `LINE_EXT_MSG_EXTENSION`, `LINE_EXT_MSG_LOGIN_MS`, `LINE_EXT_MSG_DEBUG_QR`, and `LINE_EXT_MSG_DEBUG_SCROLL`, all of which were still read by `Settings`

### Changes

- The login flow has one named state machine that both renderers share: the Tk dialog and a host's callbacks. It used to be implicit, split across three places, and derived from whether the `pin` field happened to be empty, which is why the dialog showed the same submitted PIN through the whole post-PIN transition. After the code is entered, LINE moves to a view of its own that is neither the login screen nor the chat list, and recovering from that takes seconds, during which the dialog sat on "Enter code" for a code already typed. The new `verifying` state replaces it with a spinner and a "Signing in" pill, and the viewer renders `state` as the primary key instead of inferring it
- A timeout or an unmatched page now closes the dialog as `failed` ("Could not continue") rather than `cancelled`. Nobody closed anything, so reporting the library giving up as a cancel blamed the user for it. The same three terminal names are what a host receives through `on_status`
- The dialog keeps one size in every login state, and centres the QR, the code and the spinner on both axes. The content frame stopped following whichever child was packed, so the window used to jump between the QR, the submitted code, the new spinner and an empty box. The box is now floored by the widest piece of copy in any state and by the QR itself, measured rather than hardcoded so it still holds on a scaled display where the text is a third wider. The QR is loaded before the event loop starts, which is free because Tk does not map the window until then, so the user sees the final size once instead of watching it grow. Children are positioned with `place` rather than `pack`, which centres on both axes without depending on the parcel `pack` carves out, and cannot resize the box in the process. The header and caption are pinned to the top and bottom edges so the box sits between them, and a terminal state leaves the QR or the code on screen instead of blanking it
- The QR and PIN can be rendered by the host instead of the Tk dialog. `LineClient(on_qr=..., on_pin=...)` receives the same values the dialog showed, which is what an MCP server or a web backend needs: until now the only login UI was a Tk window, so a host could not return the QR to its own client, and the AI on the other end of that client could not see it either. Supplying any login callback replaces the dialog rather than adding to it, because on a machine with no desktop a window nobody can reach is not a fallback. Return `False` from `on_qr` or `on_pin` to end the wait
- `LineClient(on_status=...)` carries the phases that have no payload of their own: `verifying` once, then one of `done`, `failed` or `cancelled`. A host keeps showing its last QR or PIN until one arrives, which is why there is no resume event, and it is not told about a cancellation it performed itself. Without this an embedder had the same dead seconds the dialog did, on the machine where there is no dialog to look at
- `LineClient(wait_for_login=...)` sets the login policy for the whole client. Every method that needs a ready page calls `status()` implicitly, and that call used to inherit "always wait" with no way for a caller to change it: 2.0.0 derived it from `settings.quiet`, which was wrong in one direction, and 3.0.0 made it unconditional, which was wrong in the other. Precedence is now the `status()` argument, then the constructor value, then waiting
- `unread_full` and `search_all` accept `on_progress`, called once per room with a `ScanProgress` carrying the room, its position, the match count, and the same `truncated` flag the report carries. Both scans walk rooms one at a time and each can spend up to the scroll budget, so a host that wanted progress had to wrap the call and guess. The truncated flag rides along on every tick, which means a partial room is visible while the scan runs rather than only when it finishes
- `clear_session()` is back as a deprecated alias for `logout()`, and logs a warning. 3.0.0 removed it outright, which broke every 1.x and 2.x embedder at once for a rename; the alias costs nothing and will be removed in a future major version
- `logout()` documents that it stops the debug Chrome. It always did, which matters more than the name suggests: the extension keeps the session token in memory, so wiping storage alone would leave a Chrome that looks logged in and cannot be trusted
- The layer table in `__init__.py` and in the README lists `domain` as holding the callback contracts alongside the models and typed errors, since `service` and the host-facing signatures both need them

## 3.0.0

### Breaking changes

- `status()` waits for a login in every mode. `wait_for_login=None` now resolves to `True` instead of `not settings.quiet`, so `LineClient(quiet=True)` no longer fails fast with `LoginRequired`: it shows the QR dialog and waits. Pass `wait_for_login=False` to get the old behaviour back, and note that a machine with no interactive desktop raises `QrDialogFailed` instead of `LoginRequired`. Both are `LineError` subclasses. `settings.quiet` still only silences the checklist, and `line-ext-msg --wait-login` is now the default for every invocation (`--no-wait-login` is the opt-out)
- `clear_session()` is renamed to `logout()` and the `--clear-session` flag is replaced by a `logout` subcommand (`line-ext-msg logout`). The old names are gone, so an embedding app has to rename the call and a script has to move `--yes` after the subcommand: `line-ext-msg logout --yes`. The probe written before a wipe moves from `session/session_probe_before_clear.json` to `session/session_probe_before_logout.json`. The internal `maintenance.clear_live` and `maintenance.clear_on_disk` keep their names because they describe the storage they clear, not the operation
- The friends list is out of the `room_*` selectors, so a wrong view can no longer be read as rooms. `list_rooms()` raises the new `ChatsViewMissing` instead of returning an empty list, because an empty list reads as "this account has no rooms"
- `search_all()` and `unread_full()` entries now carry `truncated`, and a truncated room is listed even when it matched nothing. An entry with empty `messages` and `truncated: true` means "not reached", not "not there", so code that iterates the report has to read the flag
- `open_room()` locates a room row by `data-mid` only. A row with no `data-mid` still falls back to its list position, because that is the only key left for it. Two consequences: a room whose `data-mid` is not among the rendered rows makes the library scroll the chat list once and look again, and raises `RoomNotFound` when the room is genuinely not there; and a row with no Go-chatroom button reports `RoomNotFound` instead of a click timeout. A caller that previously received another room's messages in either situation now gets an error, which is the intended outcome

### Fixes

- Rooms are read from the chats view only. LINE lands on its own view after the QR login and nothing navigated back, so the chat list never rendered and the room selectors, which also matched the friends list, silently returned friend and group names as rooms. `status()` now checks the view after login: it navigates to the chats URL when the route is wrong and clicks the nav button when the route is right but no chat list rendered, then logs which one worked and the URL it saw
- The headless QR login no longer hangs when LINE lands on a view the library does not read. After the PIN step such a page matches neither the login screen nor the chat list, which `auth.check_login` reports as `unknown`; the old loop ignored that reason and polled until the dialog was closed. It now treats a sustained `unknown` as "logged in on another view", retries the chats route twice, and raises `AppNotReady` pointing at `--dump` if that does not work. The reload is gated on `unknown` on purpose, because the login screen does not match it and a reload there would discard a half-entered PIN
- Adding a filter made a search shallower than the same call without one. A filtered query passed `need=0` to the scroll loop, which is the sentinel for "no target" and fell back to the 8s base budget instead of the limit-scaled one, so `--search` stopped mid-history in long rooms. Filtered queries now pass an explicit budget, still scaled up by `limit` and capped at 300s

### Changes

- A partial scan is now visible instead of looking like a clean miss: `Messages.scroll_stop` carries the scroll stop reason, `--search` prints which rooms were partial and how to dig deeper, and the new `--search-scroll-budget-s` sets the per-room budget from the command line
- `search_all()` and `unread_full()` read the room list once instead of once per room, which with the 8s scroll budget was the dominant cost of both
- New settings: `LINE_EXT_MSG_CHATS_ENSURE_MS` (default 10s) bounds the wait for the chat list after switching to the chats view, and `LINE_EXT_MSG_SEARCH_SCROLL_MS` (default 60s) is the lower bound for the per-room budget of a filtered query. Neither is an off switch: use `scroll=False` or `LINE_EXT_MSG_MSGS_SCROLL_MS=0` for that
- The QR dialog card no longer shows the app name: the header row holds only the status pill on the right. `LINE_EXT_MSG_DIALOG_TITLE` and `--dialog-title` still set the window title bar, which is where the name now lives. The dialog layout, colours and PIN step are unchanged

## 2.0.0

### Breaking changes

- Queries no longer write files. `list_rooms`, `get_messages`, `unread_digest`, `unread_full`, `search_all`, `dump_page`, and `dump_room` return savable result types (`Rooms`, `Messages`, `Report`, `Probe`, `Dom`) and the caller writes with `.save(path)`. `save_rooms`, `save_messages`, and `save_probe` were removed
- Media moved out of the query: `get_messages(with_media=True)` fetches image bubbles in memory as data URIs (no files) and `Messages.download_media(dir, include_data=False)` writes them. The `media_dir` and `include_media_data` arguments were removed from `get_messages`

### Changes

- Faster Chrome lifecycle: the debug PID is recorded at launch and a stop force-kills that whole tree with a single `taskkill /T` instead of enumerating every process through PowerShell; the start poll backs off after 2s and passes `--no-first-run --no-default-browser-check`; the graceful-close wait drops from 8s to 3s (`LINE_EXT_MSG_STOP_GRACEFUL_MS`); the post-switch settle wait drops from 800ms to 200ms (`LINE_EXT_MSG_READY_SETTLE_MS`); and repeated `/json/version` reads within one transition share a 0.3s cache
- Mode switches now close Chrome for real: `mode.stop` sends the CDP `Browser.close` command over the existing connection, because Playwright's `browser.close()` on a browser from `connect_over_cdp` only detaches. Graceful shutdown used to be a fixed wait that always ended in a force kill
- Quieter install check: when the extension files are already on disk `check_installed` reports `found_on_disk=True` without opening a probe tab, and a blocked probe (`net::ERR_BLOCKED_BY_CLIENT`) logs as one line instead of the full Playwright call log. The real load is still exercised by step `[4/5]`
- Fix: `ensure_chrome` reuses a running debug Chrome whatever its mode, so `--dump` and `--dump-room` no longer fail with `ChromeNotReady` when a headed instance (for example after a QR login) is already up
- Docs match the code again: the layer table in `__init__.py` and in the README now lists every real edge (`domain` is the shared vocabulary, `results` sits between `scraper` and `output`), and the Windows-only classifier replaces `OS Independent`
- CDP HTTP calls live in one module (`browser/cdp.py`): one `/json/list` reader, one `/json/close/{id}` caller, and one `/json/version` fetch replace four, three, and one copy in `session.py`, `diagnostics.py`, and `chrome.py`
- The QR status file has one writer (`service/qr_status.py`) shared by the controller and the viewer process, replacing two copies of the temp-file plus replace dance
- Removed the unused `SESSION_KEY_LEN` script from `browser/js.py`
- The debug profile launches with `--disable-notifications` and `--hide-crash-restore-bubble`, so web and push notifications stay off and the "Restore pages?" bubble never appears after a force kill. Toasts an extension raises through `chrome.notifications` are outside the scope of that switch
- The QR dialog title is configurable: `LINE_EXT_MSG_DIALOG_TITLE` sets both the window title bar and the header text inside the card (default `LINE`), and the CLI exposes it as `--dialog-title`. Blank or whitespace falls back to `LINE`
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
- Fix: the dialog no longer flashes the QR again while the PIN is being verified. It keeps showing the PIN and returns to the QR only when a genuinely new QR image appears, until login succeeds or the window is closed
- English-only project with structured logging: every CLI, dialog, and error string is English, and progress goes through the `line_ext_msg` logger instead of prints. The CLI adds `--verbose`, `--quiet-log`, `--log-level`, and `--log-file`; results stay on stdout and logs go to stderr. README and CHANGELOG translated to English
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
- CLI shows `[image: path]` / `[sticker]` instead of blank lines

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
