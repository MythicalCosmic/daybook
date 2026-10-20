"""Money: fixed-point amounts, currencies, conversion to the base currency and display.

Amounts are `Decimal(18, 2)` with a currency next to them; a rate is UZS per 1 unit of the
currency, frozen when the row is posted. The API sends amounts as strings and the client never
adds money up itself.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

CENT = Decimal("0.01")


class Currency(models.TextChoices):
    UZS = "UZS", _("Uzbek som")
    USD = "USD", _("US dollar")


class MoneyField(models.DecimalField):
    """An amount of money: `DecimalField(max_digits=18, decimal_places=2)`."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_digits", 18)
        kwargs.setdefault("decimal_places", 2)
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if kwargs.get("max_digits") == 18:
            del kwargs["max_digits"]
        if kwargs.get("decimal_places") == 2:
            del kwargs["decimal_places"]
        return name, path, args, kwargs


class RateField(models.DecimalField):
    """An exchange rate, UZS per 1 unit: `DecimalField(max_digits=18, decimal_places=6)`."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_digits", 18)
        kwargs.setdefault("decimal_places", 6)
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if kwargs.get("max_digits") == 18:
            del kwargs["max_digits"]
        if kwargs.get("decimal_places") == 6:
            del kwargs["decimal_places"]
        return name, path, args, kwargs


class CurrencyField(models.CharField):
    """`CharField(3, choices=Currency, default="UZS")`."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", 3)
        kwargs.setdefault("choices", Currency.choices)
        kwargs.setdefault("default", Currency.UZS)
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if kwargs.get("max_length") == 3:
            del kwargs["max_length"]
        if kwargs.get("choices") == Currency.choices:
            del kwargs["choices"]
        if kwargs.get("default") == Currency.UZS:
            del kwargs["default"]
        return name, path, args, kwargs


def quantize(amount: Decimal) -> Decimal:
    """Round to whole tiyin/cents, half up (bankers' rounding is not what people expect)."""
    return Decimal(amount).quantize(CENT, rounding=ROUND_HALF_UP)


def to_base(amount: Decimal, rate: Decimal) -> Decimal:
    """The amount in the base currency at `rate` (base units per 1 unit), rounded half up."""
    return quantize(Decimal(amount) * Decimal(rate))


# How each language names the som. USD reads the same in every language.
SOM = {"uz": "so'm", "ru": "сум", "en": "UZS"}


def format_money(amount: Decimal, currency: str, language: str) -> str:
    """The amount as people read it in `language`.

    `12 500 000 so'm` (uz), `12 500 000 сум` (ru), `12 500 000 UZS` (en), `$1,250.00` (USD in
    every language). Som amounts drop the tiyin when there are none; dollars always show cents.
    """
    value = quantize(amount)
    sign = "-" if value < 0 else ""
    value = abs(value)
    if currency == Currency.USD:
        return f"{sign}${value:,.2f}"
    whole, cents = divmod(value, 1)
    text = f"{int(whole):,}".replace(",", " ")
    if cents:
        decimal_mark = "." if language == "en" else ","
        text += f"{decimal_mark}{int(cents * 100):02d}"
    suffix = SOM.get(language, SOM["en"]) if currency == Currency.UZS else currency
    return f"{sign}{text} {suffix}"


class MoneySerializerField(serializers.DecimalField):
    """Money in the API: a string out, a positive amount in (pass `positive=False` to allow
    zero and negative amounts, e.g. corrections)."""

    def __init__(self, *, positive: bool = True, **kwargs):
        kwargs.setdefault("max_digits", 18)
        kwargs.setdefault("decimal_places", 2)
        kwargs["coerce_to_string"] = True
        if positive:
            kwargs.setdefault("min_value", CENT)
        super().__init__(**kwargs)
