"""Central Bank rates: a recorded answer is parsed and stored; a failure keeps the last rate
(entries then use it, marked stale)."""

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from apps.finance import cbu, rates, tasks
from apps.finance.models import ExchangeRate
from apps.finance.tests.factories import ExchangeRateFactory

pytestmark = pytest.mark.django_db

FIXTURE = Path(__file__).parent / "fixtures" / "cbu_usd_2026-10-20.json"
DAY = date(2026, 10, 20)


@pytest.fixture
def recorded(monkeypatch):
    calls = []

    def answer(url, **kwargs):
        calls.append(url)
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    monkeypatch.setattr(cbu, "fetch_json", answer)
    return calls


def test_a_recorded_answer_is_stored_for_the_day(recorded):
    row = cbu.fetch_rate(DAY)
    assert recorded == ["https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/2026-10-20/"]
    assert (row.currency, row.date, row.source, row.rate) == (
        "USD",
        DAY,
        "cbu",
        Decimal("12134.370000"),
    )
    # Fetching again updates the same row.
    cbu.fetch_rate(DAY)
    assert ExchangeRate.objects.count() == 1


def test_the_rate_in_force_on_a_weekend_is_stored_for_that_day(recorded):
    row = cbu.fetch_rate(DAY + timedelta(days=1))
    assert row.date == DAY + timedelta(days=1)


def test_an_answer_for_a_later_day_is_refused(recorded):
    with pytest.raises(cbu.RateUnavailable):
        cbu.fetch_rate(DAY - timedelta(days=1))


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        [{"Ccy": "EUR", "Rate": "1", "Date": "20.10.2026"}],
        [{"Ccy": "USD", "Rate": "abc", "Date": "20.10.2026"}],
        [{"Ccy": "USD", "Rate": "0", "Date": "20.10.2026"}],
    ],
)
def test_nonsense_is_refused(monkeypatch, payload):
    monkeypatch.setattr(cbu, "fetch_json", lambda url, **kw: payload)
    with pytest.raises(cbu.RateUnavailable):
        cbu.fetch_rate(DAY)


def test_a_failure_keeps_the_last_rate_marked_stale(monkeypatch, company):
    ExchangeRateFactory(date=DAY - timedelta(days=2), rate=Decimal("12100"))

    def down(url, **kwargs):
        raise OSError("connection timed out")

    monkeypatch.setattr(cbu, "fetch_json", down)
    outcome = cbu.ensure_rates(DAY)
    assert "timed out" in outcome["USD"]
    quote = rates.rate_for(company, "USD", DAY)
    assert quote.rate == Decimal("12100")
    assert quote.stale is True


def test_the_hourly_job_stops_once_todays_rate_is_stored(recorded, monkeypatch):
    monkeypatch.setattr("django.utils.timezone.localdate", lambda *a, **k: DAY)
    tasks.fetch_exchange_rates()
    tasks.fetch_exchange_rates()
    # Today's rate once, and yesterday's (missing) on each run until the bank has it.
    assert recorded.count("https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/2026-10-20/") == 1
    assert cbu.has_rate(DAY)
