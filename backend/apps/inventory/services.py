"""Business logic of stock: every write, shared by the API, the bots and Celery.

Each service takes `by: Membership` (`None` means the system), audits its changes with
`apps.audit.services.record` and queues jobs with `transaction.on_commit`.

The stock contract (docs/PLAN-OWNER.md §14.6.3) has its final signatures from W2.a: the sales
lines (J2), the people lifecycle (S) and later J3 and N call them. Until J1 fills them they are
stubs: `deduct` returns one allocation without a batch and moves nothing, `restock` and
`remember_code` do nothing, `record_rx` returns None, `start_count` and `journal_pdf` refuse.
J1 keeps every signature (`tests/test_contract.py` checks them).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import NamedTuple

from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError


class Allocation(NamedTuple):
    """What a deduction took from one batch: `quantity` in parts, `unit_cost` per part at the
    batch's cost. `batch_id` None: no batch held it (the stub, or a shortfall)."""

    batch_id: int | None
    quantity: Decimal
    unit_cost: Decimal | None


def deduct(
    branch,
    product,
    quantity,
    *,
    by,
    document: tuple[str, int],
    kind: str = "sale",
    series: str | None = None,
    reason: str = "",
    at: datetime | None = None,
) -> list[Allocation]:
    """Take `quantity` parts of `product` at `branch`, earliest-expiring sellable batch first
    (FEFO), for `document` ("sales.sale", id). Returns what each batch gave."""
    return [Allocation(None, Decimal(quantity), None)]


def restock(
    branch,
    allocations: list[Allocation],
    *,
    by,
    document: tuple[str, int],
    kind: str = "refund",
    status: str = "quarantine",
) -> None:
    """Put deducted parts back (a refund lands in quarantine: medicines sold aren't resold; a
    voided invoice passes status="sellable", the goods never left)."""


def start_count(branch, *, by, kind: str = "partial", category=None) -> StockCount:  # noqa: F821
    raise DomainError(_("Stock counts arrive with the stock module."))


def remember_code(product, *, by, kind: str, code: str, supplier=None) -> None:
    """An import line matched by hand: the code finds this product from now on."""


def record_rx(
    *, by, branch, product, quantity, document: tuple[str, int] | None = None, **fields
) -> RxRecord | None:  # noqa: F821
    """A prescription log entry for a dispensed prescription medicine."""
    return None


def journal_pdf(kind: str, *, branch, month: date, product=None, language: str) -> bytes:
    """The printed journal: kind rx, rx_invalid or controlled."""
    raise DomainError(_("The journals arrive with the stock module."))
