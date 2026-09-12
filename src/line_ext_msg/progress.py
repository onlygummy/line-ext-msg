"""Single checklist printer: [n/total] label ... ผ่าน/ไม่ผ่าน."""


class Steps:
    """Counted checklist; details go on indented sub-lines.

    quiet=True prints nothing (for library/MCP use over stdio).
    """

    def __init__(self, total: int, quiet: bool = False):
        self.total = total
        self.done = 0
        self.quiet = quiet

    def detail(self, text: str) -> None:
        """Debug line under the current step."""
        if not self.quiet:
            print(f"   └ {text}", flush=True)

    def check(self, label: str, passed: bool, hint: str = "") -> bool:
        """Record one step; print hint line when failed."""
        self.done += 1
        if not self.quiet:
            status = "ผ่าน" if passed else "ไม่ผ่าน"
            print(f"[{self.done}/{self.total}] {label} ... {status}", flush=True)
            if not passed and hint:
                print(f"   └ {hint}", flush=True)
        return passed

    def skip_rest(self, reason: str = "") -> None:
        """Mark remaining steps as skipped after an early stop."""
        while self.done < self.total:
            self.done += 1
            if not self.quiet:
                suffix = f" ({reason})" if reason else ""
                print(f"[{self.done}/{self.total}] ข้าม{suffix}", flush=True)
