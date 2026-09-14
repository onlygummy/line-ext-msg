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
line-ext-msg --clear-session       # ล้าง session LINE (ถามยืนยันก่อน)
```

ครั้งแรก: โปรแกรมเปิด Chrome โปรไฟล์แยก `%LOCALAPPDATA%\line-chrome-debug` ให้เอง ติดตั้ง LINE + ล็อกอินในหน้าต่างนั้น (Chrome 136+ บล็อก `--remote-debugging-port` บนโปรไฟล์หลักโดยตรง จึงต้องใช้โปรไฟล์แยก) ปกติรันแบบ headless ไม่เปิดหน้าต่าง จะเด้ง headed ขึ้นมาเฉพาะตอนต้องสแกน QR เท่านั้น (`--headed` บังคับเปิดหน้าต่าง, `--headless` บังคับเงียบ) session เก็บในโปรไฟล์แยกและรอดข้ามการปิดเปิด (พิสูจน์แล้วด้วยการฆ่าโปรเซสทิ้ง) ถ้าหลุดจริงค่อยสแกน QR ใหม่ ไฟล์ output ทั้งหมดอยู่ใน `session/` (git-ignored)

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
- session เก็บในโปรไฟล์ debug และรอดข้ามการปิดเปิดทั่วไป ถ้าหมดอายุโปรแกรมจะเปิด headed ให้สแกน QR เอง ล้างเองได้ด้วย `--clear-session`
- `from_me` เป็น heuristic (ไม่มี username = เราส่ง) ยังไม่ยืนยันด้วย dump ที่มีข้อความของตัวเอง

## dev

```powershell
uv sync
uv run pytest
uv build
```

## ถ้าอ่านห้องไม่ได้ (LINE อัปเดต UI)

```powershell
line-ext-msg --dump              # DOM หน้า chats → session/dumps/line_dom.html
line-ext-msg --dump-room 0       # DOM ในห้อง → session/dumps/line_room.html
# ส่งไฟล์มาเพื่อจูน selector ใน src/line_ext_msg/settings.py
```
