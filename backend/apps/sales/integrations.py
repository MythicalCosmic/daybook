"""Other packages' contracts that sales reads where they may not have landed yet (§14.7).

Each answers a safe default until the package that owns the data provides it, so sales never
waits for them and never breaks when one is missing.
"""

from decimal import Decimal


def vat_percent(company) -> Decimal:
    """The company's VAT rate from its tax regime (package I's `finance.queries.vat_percent`),
    for invoice lines whose medicine has no rate of its own; 0 until that contract exists."""
    try:
        from apps.finance import queries
    except ImportError:
        return Decimal(0)
    rate = getattr(queries, "vat_percent", None)
    if rate is None:
        return Decimal(0)
    try:
        return Decimal(rate(company) or 0)
    except Exception:  # a regime not set up yet reads as no VAT on the invoice
        return Decimal(0)
