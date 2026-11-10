"""Checking that a text says only numbers of the facts (docs/PLAN-OWNER.md §8.1 rule 2).

    known = known_numbers(facts)
    numbers_ok("Tushum 48,1 mln so‘m, 4,2% ko‘p", known)    # True when 48.1 and 4.2 are facts

A number in a text is read the way people write them in Uzbek, Russian and English: digit groups
with spaces or no-break spaces ("48 120 000"), English thousands commas ("48,120,000"), a
decimal comma or point ("4,2", "4.2"), a sign or a percent around it. It is known when it is a
number of the facts as it is or rounded the way a sentence rounds it: to whole numbers or one
or two decimals, and money shortened to thousands, millions or billions ("48,1 mln"). Dates
count with their parts ("2026-11-23" gives 2026, 11 and 23, and "23.11"). Signs never matter:
"fell 4.2%" and "-4.2" are the same number.
"""

import re
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation

# Numbers that are not data, never shown: they don't make a text's numbers right.
IGNORED_KEYS = frozenset({"id", "weight", "version", "url"})

_SPACES = "    "
_NUMBER = re.compile(
    rf"(?<![\w.,])(?:\d{{1,3}}(?:[{_SPACES}]\d{{3}})+(?:[.,]\d+)?"  # 48 120 000(,5)
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?"  # 48,120,000(.5)
    r"|\d+(?:[.,]\d+)?)"  # 4,2 · 4.2 · 2026
)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STEPS = (Decimal(1), Decimal("0.1"), Decimal("0.01"))
_SCALES = (Decimal(1_000), Decimal(1_000_000), Decimal(1_000_000_000))


def parse(token: str) -> Decimal | None:
    """One number as written ("48 120 000", "48,1", "1,250,000.50") as a Decimal."""
    text = token
    for space in _SPACES:
        text = text.replace(space, "")
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", text):
        text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def numbers_in(text: str) -> list[Decimal]:
    found = []
    for match in _NUMBER.finditer(text or ""):
        value = parse(match.group(0))
        if value is not None:
            found.append(abs(value))
    return found


def _forms(value: Decimal) -> set[Decimal]:
    """`value` and the ways a sentence may round or shorten it."""
    value = abs(value)
    forms = {value}
    for step in _STEPS:
        forms.add(value.quantize(step, rounding=ROUND_HALF_UP))
    forms.add(value.to_integral_value(rounding=ROUND_FLOOR))
    forms.add(value.to_integral_value(rounding=ROUND_CEILING))
    for scale in _SCALES:
        if value >= scale:
            short = value / scale
            for step in _STEPS:
                forms.add(short.quantize(step, rounding=ROUND_HALF_UP))
            forms.add(short.to_integral_value(rounding=ROUND_FLOOR))
    return forms


def _date_forms(text: str) -> set[Decimal]:
    try:
        day = date.fromisoformat(text)
    except ValueError:
        return set()
    return {
        Decimal(day.year),
        Decimal(day.month),
        Decimal(day.day),
        Decimal(f"{day.day}.{day.month:02d}"),
    }


def known_numbers(facts) -> set[Decimal]:
    """Every number of `facts`, in every form a sentence may give it."""
    found: set[Decimal] = set()

    def walk(value, key: str = "") -> None:
        if key in IGNORED_KEYS:
            return
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, int | float | Decimal):
            found.update(_forms(Decimal(str(value))))
        elif isinstance(value, str):
            if _DATE.match(value):
                found.update(_date_forms(value))
                return
            for number in numbers_in(value):
                found.update(_forms(number))
        elif isinstance(value, dict):
            for name, item in value.items():
                walk(item, str(name))
        elif isinstance(value, list | tuple):
            for item in value:
                walk(item, key)

    walk(facts)
    return found


def numbers_ok(text: str, known: set[Decimal]) -> bool:
    """Every number written in `text` is one of `known`."""
    return all(number in known for number in numbers_in(text))


def unknown(text: str, known: set[Decimal]) -> list[Decimal]:
    return [number for number in numbers_in(text) if number not in known]
