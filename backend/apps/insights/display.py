"""How insights write numbers in words, in the active language: compact money ("48,1 mln
so‘m"), percentages ("8,7"), days ("23.11"). The dashboard formats the same way
(`dashboard/src/lib/money.ts`), so a number reads alike in the bot and on the page."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.utils import translation

from apps.core.money import NBSP, SOM, Currency, format_money

# Thousand, million, billion, as `formatCompact` names them.
UNITS = {
    "uz": ("ming", "mln", "mlrd"),
    "ru": ("тыс.", "млн", "млрд"),
    "en": ("K", "M", "B"),
}
MINUS = "−"


def language() -> str:
    return (translation.get_language() or "uz")[:2]


def _decimal_mark(lang: str) -> str:
    return "." if lang == "en" else ","


def money(amount, currency: str = Currency.UZS, lang: str | None = None) -> str:
    """Compact from a million up ("48,1 mln so‘m"), the full amount below it."""
    lang = lang or language()
    value = Decimal(amount)
    size = abs(value)
    if size < Decimal(1_000_000):
        return format_money(value, currency, lang)
    scale, unit = (
        (Decimal(1_000_000_000), UNITS.get(lang, UNITS["en"])[2])
        if size >= Decimal(999_950_000)
        else (Decimal(1_000_000), UNITS.get(lang, UNITS["en"])[1])
    )
    tenths = (size / scale).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    number = f"{tenths:f}".rstrip("0").rstrip(".") if tenths % 1 == 0 else f"{tenths:f}"
    number = number.replace(".", _decimal_mark(lang))
    sign = MINUS if value < 0 else ""
    if currency == Currency.USD:
        return f"{sign}${number}{unit}"
    suffix = SOM.get(lang, SOM["en"]) if currency == Currency.UZS else currency
    if lang == "en":
        return f"{sign}{number}{unit}{NBSP}{suffix}"
    return f"{sign}{number}{NBSP}{unit}{NBSP}{suffix}"


def percent(value, digits: int = 1, lang: str | None = None) -> str:
    """ "8,7" (uz, ru) or "8.7" (en), without the sign of percent."""
    lang = lang or language()
    number = Decimal(value).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    text = f"{abs(number):f}".replace(".", _decimal_mark(lang))
    return f"{MINUS}{text}" if number < 0 else text


def ratio(value, lang: str | None = None) -> str:
    """ "6,8" times."""
    return percent(value, 1, lang)


def day(value: date | str | None) -> str:
    """ "23.11": the day and month, as the bots write dates ("" when there is none)."""
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value)
        except ValueError:
            return ""
    return value.strftime("%d.%m")
