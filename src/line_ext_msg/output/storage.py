"""Text and JSON storage helpers: always UTF-8, keep non-ASCII readable."""

import json
import os


def _ensure_parent(path: str) -> None:
    """Create the parent directory of a path when it has one."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def save_json(path: str, data) -> None:
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_text(path: str, text: str) -> None:
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
