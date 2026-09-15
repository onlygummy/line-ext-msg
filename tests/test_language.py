"""The project ships in English only: no Thai characters in the package."""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "line_ext_msg"
THAI = re.compile(r"[\u0E00-\u0E7F]")


def test_no_thai_characters_in_source():
    offenders = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if THAI.search(line):
                offenders.append(f"{path.relative_to(SRC)}:{lineno}: {line.strip()}")
    assert offenders == [], "Thai text found in source:\n" + "\n".join(offenders)
