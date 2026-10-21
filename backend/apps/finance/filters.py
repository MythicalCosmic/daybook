"""Query parameters of the finance list endpoints and exporters, parsed and checked.

The dashboard keeps filters in the URL with the API's own names (`?from=2026-10-01&category=4&
category=9&kind=expense`), and the same object travels to `exports/` as `params`, so one parser
serves both. Bad values raise DRF's `ValidationError` naming the parameter.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from django.utils.translation import gettext as _
from rest_framework.exceptions import ValidationError

from apps.finance.models import Category, Debt, Transaction

MULTI_INTS = ("account", "category", "counterparty", "member", "branch", "debt", "project")


def _values(params, key: str) -> list[str]:
    """Every value of `key`: repeated keys, comma lists and JSON arrays all work."""
    if hasattr(params, "getlist"):
        raw = params.getlist(key)
    else:
        value = params.get(key)
        raw = value if isinstance(value, list | tuple) else ([] if value in (None, "") else [value])
    out: list[str] = []
    for item in raw:
        out += [part.strip() for part in str(item).split(",") if part.strip()]
    return out


def _first(params, key: str) -> str | None:
    values = _values(params, key)
    return values[0] if values else None


def day(params, key: str) -> date | None:
    text = _first(params, key)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValidationError({key: [_("A day like 2026-10-20.")]}) from None


def ints(params, key: str) -> list[int]:
    try:
        return [int(value) for value in _values(params, key)]
    except ValueError:
        raise ValidationError({key: [_("Must be a whole number.")]}) from None


def one_int(params, key: str) -> int | None:
    values = ints(params, key)
    return values[0] if values else None


def amount(params, key: str) -> Decimal | None:
    text = _first(params, key)
    if not text:
        return None
    try:
        value = Decimal(text.replace(" ", "").replace(",", "."))
    except InvalidOperation:
        raise ValidationError({key: [_("Enter an amount of money.")]}) from None
    if not value.is_finite() or value < 0:
        raise ValidationError({key: [_("Enter an amount of money.")]})
    return value


def boolean(params, key: str) -> bool | None:
    text = _first(params, key)
    if text is None:
        return None
    if text.lower() in ("1", "true", "yes"):
        return True
    if text.lower() in ("0", "false", "no"):
        return False
    raise ValidationError({key: [_("Must be true or false.")]})


def choices(params, key: str, allowed) -> list[str]:
    values = _values(params, key)
    wrong = [value for value in values if value not in allowed]
    if wrong:
        raise ValidationError({key: [_("Unknown value: %(value)s") % {"value": wrong[0]}]})
    return values


def transaction_filters(params) -> dict:
    """The filters of `transactions/` (§4.7) for `queries.filter_transactions`."""
    filters: dict = {
        "from": day(params, "from"),
        "to": day(params, "to"),
        "kind": choices(params, "kind", Transaction.Kind.values),
        "status": choices(params, "status", Transaction.Status.values),
        "q": (_first(params, "q") or "")[:100],
        "min": amount(params, "min"),
        "max": amount(params, "max"),
        "has_receipt": boolean(params, "has_receipt"),
        "source_type": _first(params, "source_type") or None,
        # A P&L line: what the overview's "Income/Expenses this month" add up.
        "pnl": (choices(params, "pnl", Category.Kind.values) or [None])[0],
    }
    for key in MULTI_INTS:
        filters[key] = ints(params, key)
    return filters


def debt_filters(params) -> dict:
    status = choices(params, "status", (*Debt.Status.values, "all"))
    return {
        "direction": (choices(params, "direction", Debt.Direction.values) or [None])[0],
        "status": status or [Debt.Status.OPEN],
        "kind": choices(params, "kind", Debt.Kind.values),
        "overdue": boolean(params, "overdue"),
        "party": _first(params, "party"),
        "counterparty": ints(params, "counterparty"),
        "member": ints(params, "member"),
        "branch": ints(params, "branch"),
        "q": (_first(params, "q") or "")[:100],
    }
