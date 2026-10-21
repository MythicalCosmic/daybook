"""Money, days and phone numbers in the server's texts for the dashboard read exactly as the
dashboard writes them (`dashboard/src/lib/money.ts`, `lib/dates.ts`, `lib/format.ts`)."""

from datetime import date
from decimal import Decimal

import pytest
from django.utils import translation

from apps.finance import display

NB = " "
MINUS = "−"


@pytest.mark.parametrize(
    ("amount", "currency", "lang", "signed", "text"),
    [
        ("4100000", "UZS", "en", False, f"4,100,000{NB}UZS"),
        ("4100000", "UZS", "uz", False, f"4{NB}100{NB}000{NB}so‘m"),
        ("4100000", "UZS", "ru", False, f"4{NB}100{NB}000{NB}сум"),
        ("-4600000", "UZS", "en", False, f"{MINUS}4,600,000{NB}UZS"),
        ("-4600000", "UZS", "ru", True, f"{MINUS}4{NB}600{NB}000{NB}сум"),
        ("75000", "UZS", "en", True, f"+75,000{NB}UZS"),
        ("0", "UZS", "en", True, f"0{NB}UZS"),
        ("1250.5", "UZS", "uz", False, f"1{NB}250,50{NB}so‘m"),
        ("1250.5", "UZS", "en", False, f"1,250.50{NB}UZS"),
        ("1500", "USD", "en", False, "$1,500.00"),
        ("-1500", "USD", "en", False, f"{MINUS}$1,500.00"),
        ("1500", "USD", "ru", True, f"+1{NB}500,00{NB}$"),
    ],
)
def test_money_is_written_like_the_dashboard(amount, currency, lang, signed, text):
    assert display.money(Decimal(amount), currency, lang, signed=signed) == text


def test_money_follows_the_active_language():
    with translation.override("ru"):
        assert display.money(Decimal("1000"), "UZS") == f"1{NB}000{NB}сум"
    with translation.override("en"):
        assert display.money(Decimal("1000"), "UZS") == f"1,000{NB}UZS"


@pytest.mark.parametrize(
    ("value", "lang", "text"),
    [
        (date(2026, 10, 5), "en", "5 Oct"),
        (date(2026, 9, 5), "en", "5 Sept"),
        (date(2026, 10, 5), "uz", "5-okt"),
        (date(2026, 10, 5), "ru", "5 окт."),
        (date(2026, 5, 9), "ru", "9 мая"),
        (date(2025, 10, 5), "en", "5 Oct 2025"),
        (date(2025, 10, 5), "uz", "5-okt, 2025"),
        (date(2025, 10, 5), "ru", "5 окт. 2025 г."),
    ],
)
def test_days_drop_the_year_only_within_the_current_one(value, lang, text):
    assert display.day(value, date(2026, 10, 21), lang) == text


def test_phones_are_grouped_and_anything_else_is_kept():
    assert display.phone("+998901234567") == "+998 90 123 45 67"
    assert display.phone("998 71 200-44-11") == "+998 71 200 44 11"
    assert display.phone("1234") == "1234"
    assert display.phone(None) == ""
