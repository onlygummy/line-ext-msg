# line-ext-msg

ดึงข้อความ (เวลา + คนส่ง + ข้อความ + วันที่ + สถานะ) จาก LINE Chrome Extension ผ่าน Playwright แบบเกาะ Chrome ตัวจริง บัญชีของตัวเอง อ่านอย่างเดียว

## ติดตั้ง

```powershell
pip install line-ext-msg
```

ต้องมี Google Chrome ในเครื่อง ไม่ต้องรัน `playwright install` เพราะโปรแกรมเกาะ Chrome ที่มีอยู่ผ่าน CDP ไม่ได้ใช้ bundled chromium

## ใช้งาน CLI

```powershell
line-ext-msg                       # เลือกห้องใน Terminal → พิมพ์จออย่างเดียว ไม่สร้างไฟล์
line-ext-msg --save                # + เขียน session/rooms.json + session/messages_{index}.json
line-ext-msg --unread               # แสดงเฉพาะห้องที่ไม่อ่าน
line-ext-msg --limit 10 --date 2026-09-12
line-ext-msg --date-from 2026-09-01 --date-to 2026-09-12 --keyword "ใบแจ้งหนี้"
line-ext-msg --search "ใบแจ้งหนี้"  # ค้นทุกห้อง สรุปห้องที่เจอ
line-ext-msg --status              # ตรวจ Chrome + login แล้วจบ (เช็ก keepalive)
line-ext-msg --probe-session       # เขียน session/session_probe.json แบบ redact
line-ext-msg --qr-zoom 3            # ขยาย QR ใน dialog 3 เท่า (default 2, ช่วง 1-4)
line-ext-msg --debug-qr             # พิมพ์สภาพหน้า login ตอนแคป QR ไม่ได้
line-ext-msg --clear-session       # ล้าง session LINE (ถามยืนยันก่อน)
```

ครั้งแรก: โปรแกรมเปิด Chrome โปรไฟล์แยก `%LOCALAPPDATA%\line-chrome-debug` ให้เอง ติดตั้ง LINE แล้วล็อกอิน (Chrome 136+ บล็อก `--remote-debugging-port` บนโปรไฟล์หลักโดยตรง จึงต้องใช้โปรไฟล์แยก) ปกติรันแบบ headless ไม่เปิดหน้าต่าง Chrome เลย พอถึงตอนต้องสแกน QR โปรแกรมจะแคป QR จากหน้า login แล้วเปิดหน้าต่าง dialog `LINE QR` ให้สแกน (ขยาย 2 เท่า ปรับได้ด้วย `--qr-zoom` หรือ `LINE_EXT_MSG_QR_ZOOM`) โดยไม่เด้งหน้าต่าง Chrome dialog รอจนกว่าจะสแกนสำเร็จหรือปิดหน้าต่าง (ไม่มีปุ่มยกเลิก ปิดด้วยปุ่ม X)

ก่อนจะถอยไปเปิดหน้าต่าง Chrome แบบ headed (`--headed` บังคับเปิดหน้าต่าง, `--headless` บังคับเงียบ) โปรแกรมจะวนรอ canvas ของ QR ก่อน แล้วถ้ายังไม่ได้จะโหลดหน้าใหม่หนึ่งครั้งและลองอีกครั้ง เพราะหน้า SPA ที่ถูกใช้ซ้ำอาจค้างอยู่ ถ้าต้องการดูว่าทำไมแคปไม่ได้ให้เพิ่ม `--debug-qr` และปรับเวลารอได้ด้วย `LINE_EXT_MSG_QR_READY_MS` (default 20000) session เก็บในโปรไฟล์แยกและรอดข้ามการปิดเปิด (พิสูจน์แล้วด้วยการฆ่าโปรเซสทิ้ง) ถ้าหลุดจริงค่อยสแกน QR ใหม่ ไฟล์ output ทั้งหมดอยู่ใน `session/` (git-ignored)

การสลับโหมด headless กับ headed ปิด Chrome อย่างสุภาพผ่าน CDP ก่อน แล้วค่อยใช้ force kill เป็นทางสำรอง

session ของ LINE ผูกกับโปรเซส Chrome ไม่ได้ผูกกับดิสก์ token ค้างอยู่ใน Local Storage (`lcs_secure_<mid>` ยาวราว 3.2 KB) จริง แต่กุญแจที่ใช้ถอดรหัสอยู่ในหน้าต่าง sandbox `ltsmSandbox.html` ของ extension ซึ่งไม่มี storage ถาวร พอรีสตาร์ต Chrome แล้วถอดรหัสไม่ได้ก็ต้องสแกน QR ใหม่ โปรแกรมจึงไม่รีสตาร์ต Chrome ที่รันอยู่เพื่อเปลี่ยนโหมด ถ้ามีอินสแตนซ์ที่ล็อกอินค้างอยู่จะเกาะตัวเดิมทันที ทำให้สแกน QR ครั้งเดียวต่ออายุการเปิด Chrome หนึ่งรอบ (ปิด Chrome หรือรีบูตเมื่อไรต้องสแกนใหม่) ส่วน `--headless`/`--headed` มีผลเฉพาะตอนเริ่ม Chrome ใหม่

## หน้าตาไฟล์ JSON ที่ได้

```json
{
  "room": { "index": 0, "id": "CXX...", "name": "ครอบครัว", "unread": 3,
            "last_preview": "กินข้าวยัง", "last_time": "8:13 AM" },
  "fetched_at": "2026-09-12T01:00:00+00:00",
  "messages": [
    { "id": "0178...", "date": "2026-09-12", "ts": "2026-09-12T08:13:00",
      "sender": "แม่", "from_me": false, "type": "text",
      "text": "กินข้าวยัง", "read_count": null }
  ]
}
```

## ข้อจำกัดที่ควรรู้

- รายชื่อห้องกับข้อความในห้องเป็น virtualized list โปรแกรมเลื่อนโหลดเพิ่มให้เองแบบมีเพดานเวลา (`LINE_EXT_MSG_ROOMS_SCROLL_MS`, `LINE_EXT_MSG_MSGS_SCROLL_MS`) ปิดได้ด้วย `--no-scroll-msgs` หรือตั้งค่าเป็น 0
- ได้เฉพาะที่ UI แสดง ไม่มี API สถานะอ่านรายข้อความ
- session ผูกกับโปรเซส Chrome ที่รันอยู่ ต้องการล็อกอินใหม่เมื่อไหร่โปรแกรมจะแคป QR มาแสดงใน dialog `LINE QR` ให้สแกนเอง ล้าง session เองได้ด้วย `--clear-session` (เก็บ extension ไว้)
- `from_me` เป็น heuristic (ไม่มี username = เราส่ง) ยังไม่ยืนยันด้วย dump ที่มีข้อความของตัวเอง

## โครงสร้างโปรเจค

แพ็กเกจแบ่งเป็นชั้น โดย import ไหลทางเดียวและไม่มี dependency วน

```
src/line_ext_msg/
  config/    ค่าตั้ง ค่าคงที่ และ path เอาต์พุต (ไม่แตะ I/O)
  domain/    โมเดล typed errors และ filter บริสุทธิ์ (ไม่แตะเบราว์เซอร์)
  browser/   ทุกอย่างที่แตะ Chrome/Playwright: เปิดโปรเซส, CDP, login, mode, JS
  scraper/   แปลง DOM เป็นโมเดล: scroll, extract, media, rooms, messages
  output/    เขียน JSON และพิมพ์ checklist
  service/   LineClient facade, readiness และ diagnostics
  cli.py     entry point
```

public API อยู่ที่ `line_ext_msg/__init__.py` เท่านั้น (`LineClient`, `Room`, `Message`, `StepResult`, `Settings`, `sender_stats` และ error) ส่วนซับแพ็กเกจเป็น implementation detail

## dev

```powershell
uv sync --extra dev
uv run ruff check src tests
uv run mypy
uv run pytest
uv build
```

## ถ้าอ่านห้องไม่ได้ (LINE อัปเดต UI)

```powershell
line-ext-msg --dump              # DOM หน้า chats → session/dumps/line_dom.html
line-ext-msg --dump-room 0       # DOM ในห้อง → session/dumps/line_room.html
# ส่งไฟล์มาเพื่อจูน selector ใน src/line_ext_msg/settings.py
```
