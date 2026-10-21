"""Daily exchange rates from the Central Bank of Uzbekistan (cbu.uz), for every company.

The Central Bank publishes the official rate of each currency for each day. Its JSON archive
answers `GET https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/2026-10-20/` with

    [{"Ccy": "USD", "Nominal": "1", "Rate": "12150.37", "Date": "20.10.2026", …}]

`fetch_rate(day)` stores that as a global `ExchangeRate` (source "cbu"); `rates.rate_for` picks it
up for every company that hasn't set its own rate for the day. When the bank doesn't answer,
nothing is stored and the last known rate keeps being used, marked stale.
"""

import json
import logging
import urllib.request
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.core.money import Currency
from apps.finance.models import ExchangeRate, RateSource

logger = logging.getLogger(__name__)

URL = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/{currency}/{day}/"
TIMEOUT = 10
CURRENCIES = (Currency.USD,)


class RateUnavailable(Exception):
    """The Central Bank didn't answer with a usable rate."""


def fetch_json(url: str, *, timeout: int = TIMEOUT):
    """GET `url` and decode its JSON (one place for tests to replace)."""
    request = urllib.request.Request(url, headers={"User-Agent": "911-trello/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def parse(payload, currency: str) -> tuple[date, Decimal]:
    """(the day the rate is for, UZS per 1 unit) from the bank's answer."""
    if not isinstance(payload, list):
        raise RateUnavailable("Unexpected answer.")
    for entry in payload:
        if not isinstance(entry, dict) or entry.get("Ccy") != currency:
            continue
        try:
            rate = Decimal(str(entry["Rate"]).replace(",", ".").strip())
            nominal = Decimal(str(entry.get("Nominal") or "1").strip())
            day = datetime.strptime(str(entry["Date"]).strip(), "%d.%m.%Y").date()
        except (KeyError, InvalidOperation, ValueError) as error:
            raise RateUnavailable(f"Unreadable rate: {error}") from error
        if rate <= 0 or nominal <= 0:
            raise RateUnavailable("A rate is more than zero.")
        return day, (rate / nominal).quantize(Decimal("0.000001"))
    raise RateUnavailable(f"No {currency} rate in the answer.")


def fetch_rate(day: date, currency: str = Currency.USD) -> ExchangeRate:
    """Fetch and store the Central Bank's rate in force on `day`. The bank answers with the
    rate set on or before that day, which is the one in force, so it is stored for `day`.
    Raises `RateUnavailable` when the bank can't be reached or answers nonsense."""
    url = URL.format(currency=currency, day=day.isoformat())
    try:
        payload = fetch_json(url)
    except (OSError, ValueError) as error:  # network problems, timeouts, bad JSON
        raise RateUnavailable(str(error)) from error
    set_on, rate = parse(payload, currency)
    if set_on > day:
        raise RateUnavailable(f"The bank answered with the rate of {set_on} for {day}.")
    with transaction.atomic():
        row, _created = ExchangeRate.objects.update_or_create(
            currency=currency,
            date=day,
            source=RateSource.CBU,
            defaults={"rate": rate, "fetched_at": timezone.now()},
        )
    return row


def has_rate(day: date, currency: str = Currency.USD) -> bool:
    return ExchangeRate.objects.filter(currency=currency, date=day, source=RateSource.CBU).exists()


def ensure_rates(day: date) -> dict[str, str]:
    """Fetch every currency's rate for `day` that isn't stored yet. Returns {currency: what
    happened} ("stored", "had it" or the error); never raises, so the hourly job keeps going."""
    outcome = {}
    for currency in CURRENCIES:
        if has_rate(day, currency):
            outcome[currency] = "had it"
            continue
        try:
            row = fetch_rate(day, currency)
        except RateUnavailable as error:
            logger.warning("CBU %s rate for %s not fetched: %s", currency, day, error)
            outcome[currency] = str(error)
        else:
            outcome[currency] = f"stored {row.rate}"
    return outcome
