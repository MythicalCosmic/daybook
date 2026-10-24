"""Money, days and phone numbers the way the owner dashboard writes them
(`dashboard/src/lib/money.ts`, `lib/dates.ts`, `lib/format.ts`), for the texts the server builds
for it: palette search hits and "Needs you" items.

The bots keep `apps.core.money.format_money` ("12 500 000 UZS" in English). The dashboard puts
the amount first in every language with that language's grouping ("12,500,000 UZS",
"12 500 000 so‘m", "12 500 000 сум"), writes a real minus sign, and writes days as "5 Oct",
"5-okt" or "5 окт.", adding the year outside the current one.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.utils import translation

from apps.core.money import SOM, Currency

NBSP = " "
MINUS = "−"
LANGUAGES = ("uz", "ru", "en")

# Short month names as the dashboard prints them: the browser's (CLDR) for English (en-GB) and
# Russian, the product's own for Uzbek.
MONTHS = {
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sept", "Oct", "Nov", "Dec"),
    "ru": (
        "янв.",
        "февр.",
        "мар.",
        "апр.",
        "мая",
        "июн.",
        "июл.",
        "авг.",
        "сент.",
        "окт.",
        "нояб.",
        "дек.",
    ),
    "uz": ("yan", "fev", "mar", "apr", "may", "iyn", "iyl", "avg", "sen", "okt", "noy", "dek"),
}


def language(code: str | None = None) -> str:
    """The language to write in: `code`, else the active one, else Uzbek."""
    code = (code or translation.get_language() or "uz")[:2]
    return code if code in LANGUAGES else "uz"


def money(amount, currency: str, lang: str | None = None, *, signed: bool = False) -> str:
    """ "1,250,000 UZS" (en), "1 250 000 so‘m" (uz) or the Russian word for som, "$1,250.00" (en)
    or "1 250,00 $": som without tiyin when there are none, dollars always with cents. A negative
    amount takes a real minus sign (U+2212); `signed` adds "+" to a positive one."""
    lang = language(lang)
    value = Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    whole, fraction = divmod(abs(value), 1)
    group, mark = (",", ".") if lang == "en" else (NBSP, ",")
    text = f"{int(whole):,}".replace(",", group)
    if currency == Currency.USD or fraction:
        text += f"{mark}{int(fraction * 100):02d}"
    sign = MINUS if value < 0 else ("+" if signed and value > 0 else "")
    if currency == Currency.USD:
        return f"{sign}${text}" if lang == "en" else f"{sign}{text}{NBSP}$"
    label = SOM[lang] if currency == Currency.UZS else currency
    return f"{sign}{text}{NBSP}{label}"


def day(value: date, today: date, lang: str | None = None) -> str:
    """ "5 Oct" or "5-okt" (Russian: day, short month); in another year than `today`'s
    "5 Oct 2025", "5-okt, 2025" (Russian adds the year and its abbreviation), as the dashboard's
    "short" and "medium" day styles write them."""
    lang = language(lang)
    month = MONTHS[lang][value.month - 1]
    same_year = value.year == today.year
    # No-break spaces: "5 Oct" never splits across lines (research R3 §1.8).
    if lang == "uz":
        text = f"{value.day}-{month}"
        return text if same_year else f"{text},{NBSP}{value.year}"
    text = f"{value.day}{NBSP}{month}"
    if same_year:
        return text
    return f"{text}{NBSP}{value.year}" if lang == "en" else f"{text}{NBSP}{value.year}{NBSP}г."


def phone(value: str | None) -> str:
    """ "+998901234567" → "+998 90 123 45 67"; anything else as it is."""
    digits = "".join(char for char in value or "" if char.isdigit())
    if len(digits) == 12 and digits.startswith("998"):
        return f"+998 {digits[3:5]} {digits[5:8]} {digits[8:10]} {digits[10:]}"
    return value or ""
