# Changelog

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
