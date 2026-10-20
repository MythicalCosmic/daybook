"""Exchange rates: which rate a company uses on a day, and converting amounts with it.

Every rate is UZS per 1 USD, the only foreign currency (`apps.core.money.Currency`). A company
keeping its books in USD uses the same quotes: its UZS rows divide by the rate instead of
multiplying. That keeps six decimals of precision either way, where a "USD per 1 UZS" rate
would not.
"""

from datetime import date
from decimal import Decimal
from typing import NamedTuple

from django.db.models import Q
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.core.money import Currency, quantize
from apps.finance import conf
from apps.finance.models import CompanyRate, ExchangeRate, RateSource

ONE = Decimal(1)


class RateQuote(NamedTuple):
    rate: Decimal  # UZS per 1 USD; 1 when the currency is the company's base currency
    stale: bool  # no rate for the day itself: an older (or, failing that, a later) one
    source: str  # "base", "company", "cbu", "manual"


def quoted_currency(base: str, currency: str) -> str | None:
    """The foreign currency whose rate converts `currency` into `base` (None: no conversion)."""
    if currency == base:
        return None
    return currency if currency != Currency.UZS else base


def convert(amount: Decimal, from_currency: str, to_currency: str, rate: Decimal) -> Decimal:
    """`amount` in `to_currency`, rounded half up to 0.01. `rate` is UZS per 1 USD."""
    amount = Decimal(amount)
    if from_currency == to_currency:
        return quantize(amount)
    if to_currency == Currency.UZS:
        return quantize(amount * Decimal(rate))
    if from_currency == Currency.UZS:
        return quantize(amount / Decimal(rate))
    raise ValueError(f"No cross rate between {from_currency} and {to_currency}.")


def rate_for(company, currency: str, day: date) -> RateQuote:
    """The rate the company uses for `currency` on `day`.

    The company's own rate for the day beats the Central Bank's rate for the day (or a platform
    admin's manual one). Without either, the closest earlier rate of any kind is used and marked
    stale; with no earlier rate at all, the closest later one (also stale). A company that sets
    its own rates (`rate_source="manual"`) treats every rate but its own for the day as stale.
    Raises `DomainError` when there is no rate at all.
    """
    quoted = quoted_currency(company.base_currency, currency)
    if quoted is None:
        return RateQuote(ONE, False, "base")
    own = CompanyRate.objects.filter(company=company, currency=quoted)
    official = ExchangeRate.objects.filter(currency=quoted)

    today = own.filter(date=day).first()
    if today is not None:
        return RateQuote(today.rate, False, "company")
    if conf.get_settings(company).rate_source == RateSource.CBU:
        same_day = {row.source: row for row in official.filter(date=day)}
        for source in (RateSource.CBU, RateSource.MANUAL):
            if source in same_day:
                return RateQuote(same_day[source].rate, False, source)

    # Stale: the closest day before (or else after), company rates first on a tie.
    for days, order in ((Q(date__lte=day), "-date"), (Q(date__gt=day), "date")):
        candidates = [
            (row.date, 0, row.rate, "company") for row in own.filter(days).order_by(order)[:1]
        ] + [
            (row.date, 1 if row.source == RateSource.CBU else 2, row.rate, row.source)
            for row in official.filter(days).order_by(order, "source")[:2]
        ]
        if candidates:
            closest = sorted(candidates, key=lambda c: (abs((c[0] - day).days), c[1]))[0]
            return RateQuote(closest[2], True, closest[3])
    raise DomainError(
        _("There is no exchange rate for %(currency)s yet. Enter today's rate first.")
        % {"currency": quoted}
    )
