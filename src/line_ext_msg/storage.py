"""JSON storage helper: always UTF-8, keep Thai readable."""

import json
import os

# Single root for all CLI outputs (probes, rooms, messages, dumps, media).
SESSION_DIR = "session"


def save_json(path: str, data) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
