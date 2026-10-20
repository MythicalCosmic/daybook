from datetime import timedelta
from decimal import Decimal

import pytest

from apps.core.exceptions import DomainError
from apps.finance import conf, services
from apps.finance.rates import RateQuote, convert, quoted_currency, rate_for
from apps.finance.tests.factories import CompanyRateFactory, ExchangeRateFactory

pytestmark = pytest.mark.django_db

D = Decimal


def test_the_base_currency_needs_no_rate(company, day):
    assert rate_for(company, "UZS", day) == RateQuote(D(1), False, "base")


def test_the_central_bank_rate_of_the_day(company, usd, day):
    assert rate_for(company, "USD", day) == RateQuote(D("12800"), False, "cbu")


def test_the_companys_own_rate_wins(company, usd, day):
    CompanyRateFactory(company=company, date=day, rate=D("12950"))
    CompanyRateFactory(date=day, rate=D("1"))  # another company's

    assert rate_for(company, "USD", day) == RateQuote(D("12950"), False, "company")


def test_a_manual_platform_rate_stands_in_for_the_central_bank(company, day):
    ExchangeRateFactory(date=day, rate=D("12700"), source="manual")
    assert rate_for(company, "USD", day) == RateQuote(D("12700"), False, "manual")

    ExchangeRateFactory(date=day, rate=D("12800"), source="cbu")
    assert rate_for(company, "USD", day).source == "cbu"


def test_without_a_rate_for_the_day_the_closest_earlier_one_is_stale(company, day):
    ExchangeRateFactory(date=day - timedelta(days=5), rate=D("12500"))
    ExchangeRateFactory(date=day - timedelta(days=2), rate=D("12600"))
    ExchangeRateFactory(date=day + timedelta(days=1), rate=D("12900"))

    assert rate_for(company, "USD", day) == RateQuote(D("12600"), True, "cbu")


def test_an_earlier_company_rate_beats_an_older_central_bank_rate(company, day):
    ExchangeRateFactory(date=day - timedelta(days=5), rate=D("12500"))
    CompanyRateFactory(company=company, date=day - timedelta(days=1), rate=D("12650"))

    assert rate_for(company, "USD", day) == RateQuote(D("12650"), True, "company")


def test_on_a_tie_the_company_rate_wins(company, day):
    ExchangeRateFactory(date=day - timedelta(days=1), rate=D("12500"))
    CompanyRateFactory(company=company, date=day - timedelta(days=1), rate=D("12650"))

    assert rate_for(company, "USD", day).rate == D("12650")


def test_with_nothing_earlier_the_closest_later_rate_is_used(company, day):
    ExchangeRateFactory(date=day + timedelta(days=3), rate=D("12900"))
    ExchangeRateFactory(date=day + timedelta(days=9), rate=D("13100"))

    assert rate_for(company, "USD", day) == RateQuote(D("12900"), True, "cbu")


def test_no_rate_at_all(company, day):
    with pytest.raises(DomainError, match="no exchange rate for USD"):
        rate_for(company, "USD", day)


def test_a_company_that_sets_its_own_rates_marks_any_other_stale(company, usd, day):
    settings = conf.get_settings(company)
    settings.rate_source = "manual"
    settings.save()

    assert rate_for(company, "USD", day) == RateQuote(D("12800"), True, "cbu")
    CompanyRateFactory(company=company, date=day, rate=D("12990"))
    assert rate_for(company, "USD", day) == RateQuote(D("12990"), False, "company")


def test_a_dollar_company_quotes_the_dollar_for_its_som(company, usd, day):
    company.base_currency = "USD"
    company.save()

    assert rate_for(company, "USD", day) == RateQuote(D(1), False, "base")
    assert rate_for(company, "UZS", day) == RateQuote(D("12800"), False, "cbu")


def test_the_services_export_rate_for():
    assert services.rate_for is rate_for


@pytest.mark.parametrize(
    "amount, source, target, rate, expected",
    [
        ("100", "USD", "UZS", "12800", "1280000.00"),
        ("1280000", "UZS", "USD", "12800", "100.00"),
        ("1", "UZS", "USD", "12800", "0.00"),
        ("0.005", "UZS", "UZS", "1", "0.01"),  # half up
        ("33.333", "USD", "UZS", "12345.678901", "411518.51"),
        ("-100", "USD", "UZS", "12800", "-1280000.00"),
    ],
)
def test_convert(amount, source, target, rate, expected):
    assert convert(D(amount), source, target, D(rate)) == D(expected)


def test_quoted_currency():
    assert quoted_currency("UZS", "UZS") is None
    assert quoted_currency("UZS", "USD") == "USD"
    assert quoted_currency("USD", "UZS") == "USD"
