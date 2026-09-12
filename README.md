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
line-ext-msg --save                # + เขียน rooms.json + messages_{index}.json
line-ext-msg --unread               # แสดงเฉพาะห้องที่ไม่อ่าน
line-ext-msg --limit 10 --date 2026-09-12
line-ext-msg --date-from 2026-09-01 --date-to 2026-09-12 --keyword "ใบแจ้งหนี้"
line-ext-msg --search "ใบแจ้งหนี้"  # ค้นทุกห้อง สรุปห้องที่เจอ
```

ครั้งแรก: โปรแกรมเปิด Chrome โปรไฟล์แยก `%LOCALAPPDATA%\line-chrome-debug` ให้เอง ติดตั้ง LINE + ล็อกอินครั้งเดียวในหน้าต่างนั้น หลังจากนั้น auto หมด (Chrome 136+ บล็อก `--remote-debugging-port` บนโปรไฟล์หลักโดยตรง จึงต้องใช้โปรไฟล์แยก)

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

- อ่านได้เฉพาะแถวที่ render บนจอ (virtualized list) ประวัติย้อนหลังลึกต้อง scroll เพิ่ม (ยังไม่ทำ)
- ได้เฉพาะที่ UI แสดง ไม่มี API สถานะอ่านรายข้อความ
- `from_me` เป็น heuristic (ไม่มี username = เราส่ง) ยังไม่ยืนยันด้วย dump ที่มีข้อความของตัวเอง

## dev

```powershell
uv sync
uv run pytest
uv build
```

## ถ้าอ่านห้องไม่ได้ (LINE อัปเดต UI)

```powershell
line-ext-msg --dump              # DOM หน้า chats → line_dom.html
line-ext-msg --dump-room 0       # DOM ในห้อง → line_room.html
# ส่งไฟล์มาเพื่อจูน selector ใน src/line_ext_msg/settings.py
```
