"""Pure message filters and sender stats. No browser, fully unit-testable."""

from __future__ import annotations

from .models import Message


def time_of(msg: Message) -> str:
    """HH:MM from full ISO ts; '' when ts is display text only."""
    ts = msg.ts or ""
    return ts[11:16] if len(ts) >= 16 and ts[10:11] == "T" else ""


def apply_filters(
    msgs: list[Message],
    date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    time_from: str | None = None,
    time_to: str | None = None,
    sender: str | None = None,
    keyword: str | None = None,
) -> list[Message]:
    """Post-filter a message list. `date` is shorthand for from == to."""
    if date is not None:
        date_from = date_to = date
    out = msgs
    if date_from is not None:
        out = [m for m in out if m.date >= date_from]
    if date_to is not None:
        out = [m for m in out if m.date and m.date <= date_to]
    if time_from is not None or time_to is not None:
        keep = []
        for m in out:
            t = time_of(m)
            if not t:
                continue
            if time_from is not None and t < time_from:
                continue
            if time_to is not None and t > time_to:
                continue
            keep.append(m)
        out = keep
    if sender is not None:
        out = [m for m in out if sender in m.sender]
    if keyword is not None:
        out = [m for m in out if keyword in m.text]
    return out


def sender_stats(msgs: list[Message]) -> list[dict]:
    """Count messages per sender, most first. System rows are skipped."""
    counts: dict[str, int] = {}
    for m in msgs:
        if m.type == "system":
            continue
        name = m.sender or "(me)"
        counts[name] = counts.get(name, 0) + 1
    return [{"sender": s, "count": c} for s, c in sorted(counts.items(), key=lambda kv: -kv[1])]
