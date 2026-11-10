"""Numbers and days the way a review writes them, per language.

    money(48120000, "UZS", "uz")     "48,1 mln so‘m"       (en "48.1 mln UZS", ru "48,1 млн сум")
    percent("4.2", "ru")             "4,2%"
    day("2026-11-23", "uz")          "23-noyabr"           (ru "23 ноября", en "23 November")
    period(period_dict, "ru")        "октябрь 2026"; a week: its two days joined by an en dash

Money under a million keeps every digit ("850 000 so‘m", no-break spaces as everywhere in the
bots); a million or more is shortened to one decimal of millions, a billion or more to two of
billions, which the number check (apps.briefings.numbers) reads back as the same number.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from apps.core.money import SOM, Currency
from apps.finance import display as finance_display

NBSP = " "
MINUS = "−"
MILLION = Decimal(1_000_000)
BILLION = Decimal(1_000_000_000)
LANGUAGES = ("uz", "ru", "en")
SHORT = {
    "uz": ("mln", "mlrd"),
    "ru": ("млн", "млрд"),
    "en": ("mln", "bln"),
}
MONTHS = {
    "uz": (
        "yanvar",
        "fevral",
        "mart",
        "aprel",
        "may",
        "iyun",
        "iyul",
        "avgust",
        "sentabr",
        "oktabr",
        "noyabr",
        "dekabr",
    ),
    # Russian: the day takes the genitive ("23 ноября"), a month alone the nominative.
    "ru": (
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ),
    "en": (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
}
RU_MONTHS_ALONE = (
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)


def lang_of(language: str | None) -> str:
    code = (language or "uz")[:2]
    return code if code in LANGUAGES else "uz"


def _decimal_text(value: Decimal, places: int, lang: str) -> str:
    step = Decimal(1).scaleb(-places)
    text = f"{value.quantize(step, rounding=ROUND_HALF_UP):f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text if lang == "en" else text.replace(".", ",")


def money(amount, currency: str, language: str | None) -> str:
    lang = lang_of(language)
    value = Decimal(str(amount or 0))
    if currency != Currency.UZS or abs(value) < MILLION:
        return finance_display.money(value, currency, lang)
    sign = MINUS if value < 0 else ""
    value = abs(value)
    words = SHORT[lang]
    if value >= BILLION:
        number, word = _decimal_text(value / BILLION, 2, lang), words[1]
    else:
        number, word = _decimal_text(value / MILLION, 1, lang), words[0]
    return f"{sign}{number}{NBSP}{word}{NBSP}{SOM[lang]}"


def percent(value, language: str | None) -> str:
    """ "4,2%", "588%" (the sign left to the words: "fell 4,2%"); from 100 on, whole."""
    if value is None:
        return ""
    amount = abs(Decimal(str(value)))
    return f"{_decimal_text(amount, 0 if amount >= 100 else 1, lang_of(language))}%"


def number(value, language: str | None) -> str:
    """A count or an average count ("4,5", "12", "10 546")."""
    lang = lang_of(language)
    amount = Decimal(str(value or 0))
    if amount == amount.to_integral_value() and abs(amount) >= 1000:
        return f"{int(amount):,}".replace(",", NBSP)
    return _decimal_text(amount, 1, lang)


def day(value, language: str | None) -> str:
    lang = lang_of(language)
    when = date.fromisoformat(value) if isinstance(value, str) else value
    month = MONTHS[lang][when.month - 1]
    if lang == "uz":
        return f"{when.day}-{month}"
    return f"{when.day}{NBSP}{month}"


def period(shape: dict, language: str | None) -> str:
    """The period a review covers: a week as its days ("2", an en dash, "8-noyabr"; across two
    months both days in full), a month as "2026-yil oktabr", "октябрь 2026", "October 2026"."""
    lang = lang_of(language)
    start = date.fromisoformat(shape["start"])
    end = date.fromisoformat(shape["end"])
    if shape.get("kind") == "monthly":
        if lang == "ru":
            return f"{RU_MONTHS_ALONE[start.month - 1]} {start.year}"
        if lang == "uz":
            return f"{start.year}-yil {MONTHS['uz'][start.month - 1]}"
        return f"{MONTHS['en'][start.month - 1]} {start.year}"
    if start.month == end.month:
        month = MONTHS[lang][end.month - 1]
        if lang == "uz":
            return f"{start.day}–{end.day}-{month}"
        return f"{start.day}–{end.day}{NBSP}{month}"
    return f"{day(start, lang)} – {day(end, lang)}"
