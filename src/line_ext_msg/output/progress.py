"""Single checklist logger: [n/total] label ... OK/FAIL/skip."""

import logging

logger = logging.getLogger(__name__)


class Steps:
    """Counted checklist; details go on indented sub-lines.

    quiet=True logs nothing (for library/MCP use over stdio).
    """

    def __init__(self, total: int, quiet: bool = False):
        self.total = total
        self.done = 0
        self.quiet = quiet

    def detail(self, text: str) -> None:
        """Debug line under the current step."""
        if not self.quiet:
            logger.info("   - %s", text)

    def check(self, label: str, passed: bool, hint: str = "") -> bool:
        """Record one step; log a hint line when failed."""
        self.done += 1
        if not self.quiet:
            status = "OK" if passed else "FAIL"
            logger.info("[%d/%d] %s ... %s", self.done, self.total, label, status)
            if not passed and hint:
                logger.info("   - %s", hint)
        return passed

    def skip_rest(self, reason: str = "") -> None:
        """Mark remaining steps as skipped after an early stop."""
        while self.done < self.total:
            self.done += 1
            if not self.quiet:
                suffix = f" ({reason})" if reason else ""
                logger.info("[%d/%d] skip%s", self.done, self.total, suffix)
