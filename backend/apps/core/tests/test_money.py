from decimal import Decimal

import pytest
from django.db import models
from rest_framework import serializers

from apps.core.money import (
    Currency,
    CurrencyField,
    MoneyField,
    MoneySerializerField,
    RateField,
    format_money,
    to_base,
)


def test_money_and_rate_fields_have_fixed_precision():
    money, rate, currency = MoneyField(null=True), RateField(), CurrencyField()

    assert (money.max_digits, money.decimal_places) == (18, 2)
    assert (rate.max_digits, rate.decimal_places) == (18, 6)
    assert currency.max_length == 3
    assert currency.default == Currency.UZS
    assert dict(currency.choices) == dict(Currency.choices)
    assert isinstance(money, models.DecimalField)


def test_fields_deconstruct_without_their_defaults():
    # Keeps migrations short and stable.
    assert MoneyField(null=True).deconstruct()[3] == {"null": True}
    assert RateField().deconstruct()[3] == {}
    assert CurrencyField().deconstruct()[3] == {}
    assert CurrencyField(default=Currency.USD).deconstruct()[3] == {"default": Currency.USD}
    assert MoneyField(max_digits=20).deconstruct()[3] == {"max_digits": 20}


@pytest.mark.parametrize(
    ("amount", "rate", "expected"),
    [
        ("100", "12850.5", "1285050.00"),
        ("0.01", "12850.123456", "128.50"),  # 128.50123456
        ("0.005", "1", "0.01"),  # half up, not to even
        ("0.015", "1", "0.02"),
        ("-0.005", "1", "-0.01"),
        ("1250000", "1", "1250000.00"),
    ],
)
def test_to_base_rounds_half_up_to_cents(amount, rate, expected):
    result = to_base(Decimal(amount), Decimal(rate))

    assert result == Decimal(expected)
    assert result.as_tuple().exponent == -2


@pytest.mark.parametrize(
    ("amount", "currency", "language", "expected"),
    [
        ("12500000", "UZS", "uz", "12\u00a0500\u00a0000\u00a0so‘m"),
        ("12500000", "UZS", "ru", "12\u00a0500\u00a0000\u00a0сум"),
        ("12500000", "UZS", "en", "12\u00a0500\u00a0000\u00a0UZS"),
        ("12500000.50", "UZS", "uz", "12\u00a0500\u00a0000,50\u00a0so‘m"),
        ("12500000.5", "UZS", "en", "12\u00a0500\u00a0000.50\u00a0UZS"),
        ("999", "UZS", "uz", "999\u00a0so‘m"),
        ("0", "UZS", "ru", "0\u00a0сум"),
        ("-45000", "UZS", "uz", "-45\u00a0000\u00a0so‘m"),
        ("1250", "USD", "uz", "$1,250.00"),
        ("1250", "USD", "ru", "$1,250.00"),
        ("1250.456", "USD", "en", "$1,250.46"),
        ("-3.5", "USD", "en", "-$3.50"),
    ],
)
def test_format_money(amount, currency, language, expected):
    # No-break spaces between the digit groups and before the currency (R3 §1.8).
    assert format_money(Decimal(amount), currency, language) == expected


class Payment(serializers.Serializer):
    amount = MoneySerializerField()
    correction = MoneySerializerField(positive=False, required=False)


def test_money_goes_out_as_a_string():
    assert Payment({"amount": Decimal("1250000")}).data == {"amount": "1250000.00"}


def test_money_must_be_positive_by_default():
    assert not Payment(data={"amount": "0"}).is_valid()
    assert not Payment(data={"amount": "-5"}).is_valid()
    assert not Payment(data={"amount": "1.234"}).is_valid()  # no fractions of a tiyin
    payment = Payment(data={"amount": "0.01", "correction": "-150.50"})
    assert payment.is_valid(), payment.errors
    assert payment.validated_data == {"amount": Decimal("0.01"), "correction": Decimal("-150.50")}


def test_money_fits_the_column():
    assert not Payment(data={"amount": "1" * 17 + ".00"}).is_valid()
    assert Payment(data={"amount": "9" * 16 + ".99"}).is_valid()
