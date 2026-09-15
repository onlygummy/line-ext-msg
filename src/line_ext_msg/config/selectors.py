"""Tuned selectors for the LINE extension DOM.

Single place to adjust when LINE ships a new build. CSS-module hashes
change per build, so match the stable module prefix with *= and never the
hash itself.
"""

SELECTORS = {
    # Left nav button that routes to the chats view.
    "nav_chat": "button[aria-label='Chat']",
    # Room rows (chats view first, friends as fallback).
    "room_list": "[class*='chatlist-module__chatlist'], [class*='friendlist-module__list']",
    "room_item": "[class*='chatlistItem-module__chatlist_item'], [class*='friendlistItem-module__item']",
    "room_name": "[class*='chatlistItem-module__text'], [class*='friendlistItem-module__text']",
    "room_open": "button[aria-label='Go chatroom']",
    "room_unread": "[class*='chatlistItem-module__message_count'], [class*='friendlistItem-module__badge']",
    "room_preview": "[class*='chatlistItem-module__description'], [class*='friendlistItem-module__description']",
    "room_time": "[class*='chatlistItem-module__date']",
    # Message list: stable hash-free container (role=log).
    "message_list": "div.message_list",
    "message_item": "[class*='message-module__message']",
    "sender": "[class*='username-module__username']",
    "text": "[class*='textMessageContent-module__text']",
    "time": "[class*='metaInfo-module__send_time']",
    "read_count": "[class*='metaInfo-module__read_count']",
    "sticker": "[class*='stickerMessageContent-module__']",
    "image": "[class*='imageMessageContent-module__']",
    "system_row": "[class*='systemMessage-module__message']",
    "system_text": "[class*='systemMessage-module__text']",
    "date_sep": "[class*='messageDate-module__date']",
    # Login page: the page container and the QR sub-area (extension v3.7.2).
    "login_page": "[class*='loginPage']",
    "login_qr": "[class*='login_qr']",
}
