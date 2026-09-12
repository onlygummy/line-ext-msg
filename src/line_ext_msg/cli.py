"""Thin CLI over LineClient: parse args, print results."""
import argparse

from .client import LineClient
from .errors import LineError
from .models import Room
from .settings import Settings


def _display(m) -> str:
    """Readable line: text, or media label when the bubble has no text."""
    if m.text:
        return m.text[:80]
    if m.type == "image":
        return f"[รูปภาพ: {m.media or 'โหลดไม่สำเร็จ'}]"
    if m.type == "sticker":
        return "[สติกเกอร์]"
    if m.type == "system":
        return m.text
    return f"[{m.type}]"


def pick_room(rooms: list[Room]) -> Room:
    """Show rooms in terminal and return user choice."""
    print("\nห้องแชททั้งหมด:")
    for r in rooms:
        unread = f" ({r.unread} ไม่อ่าน)" if r.unread else ""
        print(f"  [{r.index}] {r.name}{unread}")
    while True:
        raw = input("พิมพ์เลขห้อง > ").strip()
        if raw.isdigit() and any(r.index == int(raw) for r in rooms):
            return next(r for r in rooms if r.index == int(raw))
        print("เลขไม่ถูกต้อง ลองใหม่")


def main():
    parser = argparse.ArgumentParser(description="ดึงข้อความล่าสุดจาก LINE Extension")
    parser.add_argument("--limit", type=int, default=5, help="จำนวนข้อความล่าสุด")
    parser.add_argument("--date", default=None, help="กรองเฉพาะวันที่ YYYY-MM-DD")
    parser.add_argument("--date-from", default=None, help="ตั้งแต่วันที่ YYYY-MM-DD")
    parser.add_argument("--date-to", default=None, help="ถึงวันที่ YYYY-MM-DD")
    parser.add_argument("--time-from", default=None, help="ตั้งแต่เวลา HH:MM")
    parser.add_argument("--time-to", default=None, help="ถึงเวลา HH:MM")
    parser.add_argument("--sender", default=None, help="กรองชื่อคนส่ง (บางส่วน)")
    parser.add_argument("--keyword", default=None, help="ค้นคำในข้อความ")
    parser.add_argument("--search", default=None, metavar="KEYWORD",
                        help="ค้นทุกห้อง แล้วสรุปห้องที่เจอ")
    parser.add_argument("--unread", action="store_true", help="แสดงเฉพาะห้องที่ไม่อ่าน")
    parser.add_argument("--save", action="store_true", help="เขียน rooms.json + messages ลงไฟล์ (default พิมพ์จออย่างเดียว)")
    parser.add_argument("--dump", action="store_true", help="บันทึก DOM ดิบเพื่อจูน selector")
    parser.add_argument("--dump-room", type=int, default=None, metavar="INDEX",
                        help="เปิดห้องลำดับ INDEX แล้วบันทึก DOM เพื่อจูน selector ข้อความ")
    parser.add_argument("--wait-login", dest="wait_login", action="store_true", default=None,
                        help="รอหน้าล็อกอินจนกว่าจะล็อกอินเสร็จ (default ในโหมดคนใช้)")
    parser.add_argument("--no-wait-login", dest="no_wait_login", action="store_true",
                        help="เจอหน้าล็อกอินแล้วจบเลย ไม่รอ")
    parser.add_argument("--login-timeout-s", type=float, default=None, metavar="SEC",
                        help="เวลารอสูงสุดเป็นวินาที (default 300)")
    args = parser.parse_args()

    wait_flag = None
    if args.no_wait_login:
        wait_flag = False
    elif args.wait_login:
        wait_flag = True
    wait_ms = int(args.login_timeout_s * 1000) if args.login_timeout_s is not None else None
    settings = Settings(login_wait_ms=wait_ms) if wait_ms is not None else None

    try:
        with LineClient(settings) as line:
            if args.dump:
                state = line.dump_page()
                print(f"บันทึก line_dom.html แล้ว (state={state}) ส่งไฟล์นี้มาเพื่อจูน selector")
                return
            line.status(wait_for_login=wait_flag, login_timeout_ms=wait_ms)
            if args.dump_room is not None:
                room = line.dump_room(args.dump_room)
                print(f"บันทึก line_room.html แล้ว (ห้อง {room.name}) ส่งไฟล์นี้มาเพื่อจูน selector ข้อความ")
                return
            rooms = line.list_rooms(unread_only=args.unread)
            if not rooms:
                print("อ่านรายชื่อห้องไม่ได้ รัน --dump แล้วส่ง line_dom.html มา")
                return
            if args.save:
                path = line.save_rooms(unread_only=args.unread)
                print(f"บันทึก {path} ({len(rooms)} ห้อง)")
            if args.search:
                for hit in line.search_all(args.search, date_from=args.date_from,
                                           date_to=args.date_to or args.date):
                    print(f"\n== {hit['room']['name']} ({len(hit['messages'])} ข้อความ) ==")
                    for m in hit["messages"]:
                        print(f"[{m['date']} {m['ts']}] {m['sender']}: {m['text'][:80]}")
                return
            chosen = pick_room(rooms)
            filt = dict(limit=args.limit, date=args.date, date_from=args.date_from,
                        date_to=args.date_to, time_from=args.time_from, time_to=args.time_to,
                        sender=args.sender, keyword=args.keyword, media_dir="media")
            if args.save:
                out = line.save_messages(chosen, **filt)
                print(f"บันทึก {out}")
            print(f"กำลังเปิดห้อง {chosen.name} ...", flush=True)
            msgs = line.get_messages(chosen, **filt)
            if not msgs:
                print("เปิดห้องได้แต่อ่านข้อความไม่ได้")
                print(f"รัน uv run line-ext-msg --dump-room {chosen.index} แล้วส่ง line_room.html มา")
                return
            for m in msgs:
                print(f"[{m.date} {m.ts}] {m.sender}: {_display(m)}")
    except KeyboardInterrupt:
        print("\nยกเลิกการรอแล้ว")
    except LineError as e:
        print(e)


if __name__ == "__main__":
    main()
