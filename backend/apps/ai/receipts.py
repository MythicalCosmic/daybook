"""Reading receipts with AI (docs/PLAN-OWNER.md §8.5), for expenses and claims.

    scan = receipts.start_scan(image, by=member, source="bot")
    if scan is None:
        ...  # no AI: the person fills in the form themselves

`start_scan` queues the reading and returns the `ReceiptScan` row at once (status queued);
the result arrives on that row, and the bot edits its message when it is ready. It returns
None whenever AI isn't available for the company (apps.ai.availability), receipts are switched
off, or the person reached today's limit. Until package K builds it, it always returns None.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.ai.models import ReceiptScan  # added by package K

# Where a receipt photo came from (ReceiptScan.source).
SOURCES = ("dashboard", "bot", "miniapp")


def start_scan(file, *, by, source: str) -> ReceiptScan | None:
    """Start reading the receipt in `file` (a picture already through
    `apps.core.uploads.sanitize_image`) for `by` (a Membership). `source` is one of SOURCES."""
    if source not in SOURCES:
        raise ValueError(f"Unknown receipt source {source!r}.")
    return None
