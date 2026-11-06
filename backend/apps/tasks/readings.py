"""Storage readings (PLAN-OWNER §14.10): the numbers a readings routine asks for, the values
people type for them, and how a value reads against its allowed range.

A routine's spec (`TaskTemplate.readings`, copied into each task it makes):

    {"key": "t", "label": "Fridge 1 temperature", "unit": "°C", "min": "2.0", "max": "8.0",
     "critical": true}

`min` or `max` may be null (humidity: a maximum only). Keys are one letter, a to z, unique per
routine. Values are Decimals: "5,2", "5.2", "+5.2" and "5,2 °C" read the same, and anything
outside -50 … +100 is refused as a typo. A plain module: services, the APIs, the bot and the
journal use it.
"""

import re
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.utils import translation
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError

MAX_SPECS = 3
KEYS = "abcdefghijklmnopqrstuvwxyz"
LOWEST, HIGHEST = Decimal("-50"), Decimal("100")
LABEL_MAX = 80
UNIT_MAX = 8
NOTE_MAX = 300
# A second measurement (after moving the vaccines) counts within this long of the first.
RECHECK_WINDOW = timedelta(hours=2)
CENT = Decimal("0.01")

_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
# What people type after the number: "5,2 °C", "5.2C", "58 %".
_UNIT_TAIL = re.compile(r"(°\s*[cс]?|[cс]|%)$", re.IGNORECASE)


# Values ------------------------------------------------------------------------------------


def parse(raw) -> Decimal | None:
    """The number in what someone typed ("5,2", "5.2", " +5,2 °C", "-3" with a minus sign),
    or None."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int | Decimal):
        text = str(raw)
    elif isinstance(raw, float):
        text = repr(raw)
    else:
        text = str(raw)
    text = text.strip().replace("−", "-").replace(" ", "").replace(" ", "")
    text = _UNIT_TAIL.sub("", text).replace(",", ".")
    if not _NUMBER.match(text):
        return None
    try:
        return Decimal(text).quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def is_plausible(value: Decimal) -> bool:
    return LOWEST <= value <= HIGHEST


def bound(raw) -> Decimal | None:
    """A spec's `min` or `max` as a Decimal (None when there is none)."""
    if raw is None or raw == "":
        return None
    value = parse(raw)
    if value is None or not is_plausible(value):
        raise DomainError(_("Allowed values go from −50 to 100."))
    return value


def in_range(value: Decimal, low: Decimal | None, high: Decimal | None) -> bool:
    return (low is None or value >= low) and (high is None or value <= high)


def plain(value: Decimal | None) -> str | None:
    """A Decimal as the API and the specs carry it: "2.0", "5.25", "-3.5"."""
    if value is None:
        return None
    text = format(value.normalize(), "f")
    return text if "." in text else f"{text}.0"


# Words -------------------------------------------------------------------------------------


def number(value: Decimal | str | None, language: str | None = None) -> str:
    """A value as people read it: "5.2" in English, "5,2" in Uzbek and Russian; no trailing
    zeros ("8", not "8.00")."""
    if value is None:
        return ""
    value = Decimal(str(value))
    text = format(value.normalize(), "f")
    if text in ("-0", "+0"):
        text = "0"
    language = (language or translation.get_language() or "uz")[:2]
    return text.replace(".", ",") if language != "en" else text


def range_text(low, high, unit: str = "", language: str | None = None) -> str:
    """A range as people read it ("2 to 8 °C" with an en dash, "≤ 60 %", "≥ 15 °C"), or ""."""
    low_text, high_text = number(low, language), number(high, language)
    if low is not None and high is not None:
        text = f"{low_text}–{high_text}"
    elif high is not None:
        text = f"≤ {high_text}"
    elif low is not None:
        text = f"≥ {low_text}"
    else:
        return ""
    return f"{text} {unit}".strip()


def value_text(value, unit: str = "", language: str | None = None) -> str:
    return f"{number(value, language)} {unit}".strip()


# Specs -------------------------------------------------------------------------------------


def clean_specs(raw) -> list[dict]:
    """A routine's readings, checked and in their stored shape: 0 to `MAX_SPECS` specs, each
    with a label, a unit, an optional range and whether going out of it is critical. A spec
    without a key gets the next free letter."""
    if raw is None:
        return []
    if not isinstance(raw, list | tuple):
        raise DomainError(_("Readings must be a list."))
    if len(raw) > MAX_SPECS:
        raise DomainError(_("A routine asks for at most %(max)d readings.") % {"max": MAX_SPECS})
    if not all(isinstance(spec, dict) for spec in raw):
        raise DomainError(_("Each reading needs a name, a unit and its allowed values."))
    used = {str(spec.get("key") or "").strip().lower() for spec in raw}
    free = (key for key in KEYS if key not in used)
    cleaned, seen = [], set()
    for spec in raw:
        key = str(spec.get("key") or "").strip().lower() or next(free)
        if len(key) != 1 or key not in KEYS:
            raise DomainError(_("A reading's key is one letter, a to z."))
        if key in seen:
            raise DomainError(_("Each reading of a routine needs its own key."))
        seen.add(key)
        label = " ".join(str(spec.get("label") or "").split())
        if not label:
            raise DomainError(_("Name each reading: what is measured."))
        if len(label) > LABEL_MAX:
            raise DomainError(
                _("Keep the name of a reading under %(max)d characters.") % {"max": LABEL_MAX}
            )
        unit = str(spec.get("unit") or "").strip()
        if len(unit) > UNIT_MAX:
            raise DomainError(_("Keep a unit under %(max)d characters.") % {"max": UNIT_MAX})
        low, high = bound(spec.get("min")), bound(spec.get("max"))
        if low is not None and high is not None and low > high:
            raise DomainError(_("The lowest allowed value can't be above the highest."))
        cleaned.append(
            {
                "key": key,
                "label": label,
                "unit": unit,
                "min": plain(low),
                "max": plain(high),
                "critical": bool(spec.get("critical", False)),
            }
        )
    return cleaned


def spec_range(spec: dict) -> tuple[Decimal | None, Decimal | None]:
    low, high = spec.get("min"), spec.get("max")
    return (
        Decimal(str(low)) if low not in (None, "") else None,
        Decimal(str(high)) if high not in (None, "") else None,
    )


def spec_range_text(spec: dict, language: str | None = None) -> str:
    low, high = spec_range(spec)
    return range_text(low, high, spec.get("unit", ""), language)


# Taking them -------------------------------------------------------------------------------


def take(specs: list[dict], values, note: str = "", *, recheck: bool = False) -> list[dict]:
    """Check what someone typed for a task's specs: `values` maps a key to a value ("5,2").
    Every spec needs a value (a recheck: one or more of them), each a plausible number, and a
    value out of range needs `note` (what was done about it). Returns
    `[{"spec", "value", "in_range"}]` in the specs' order; raises DomainError otherwise."""
    values = dict(values or {})
    note = (note or "").strip()
    known = {spec["key"]: spec for spec in specs}
    if unknown := sorted(set(values) - set(known)):
        raise DomainError(_("This task doesn't ask for %(keys)s.") % {"keys": ", ".join(unknown)})
    if not any(str(values.get(key, "")).strip() for key in known):
        if recheck:
            raise DomainError(_("Type the new reading."))
        raise DomainError(_("Enter the readings to complete this task."))
    taken = []
    for spec in specs:
        raw = values.get(spec["key"])
        if raw is None or str(raw).strip() == "":
            if recheck:
                continue
            raise DomainError(_("A reading is missing: %(label)s.") % {"label": spec["label"]})
        value = parse(raw)
        if value is None:
            raise DomainError(_("%(label)s: type a number, like 5.2.") % {"label": spec["label"]})
        if not is_plausible(value):
            raise DomainError(
                _("%(label)s: that can't be right. Type a value from −50 to 100.")
                % {"label": spec["label"]}
            )
        low, high = spec_range(spec)
        taken.append({"spec": spec, "value": value, "in_range": in_range(value, low, high)})
    out = [row for row in taken if not row["in_range"]]
    if out and not note:
        first = out[0]
        raise DomainError(
            _("%(label)s is out of range (%(range)s). Write what you did about it.")
            % {"label": first["spec"]["label"], "range": spec_range_text(first["spec"])}
        )
    if len(note) > NOTE_MAX:
        raise DomainError(_("Keep the note under %(max)d characters.") % {"max": NOTE_MAX})
    return taken


def taken_row(reading) -> dict:
    """A `TaskReading` as both APIs return it."""
    return {
        "id": reading.pk,
        "key": reading.key,
        "label": reading.label,
        "unit": reading.unit,
        "value": plain(reading.value),
        "min": plain(reading.min),
        "max": plain(reading.max),
        "in_range": reading.in_range,
        "note": reading.note,
        "is_recheck": reading.is_recheck,
        "recorded_at": reading.recorded_at,
        "recorded_by": (
            {"id": reading.recorded_by_id, "name": str(reading.recorded_by)}
            if reading.recorded_by_id
            else None
        ),
    }


def latest(readings) -> dict[str, object]:
    """The latest value of each key (a recheck wins over the first measurement)."""
    found: dict[str, object] = {}
    for reading in sorted(readings, key=lambda row: (row.recorded_at, row.pk)):
        found[reading.key] = reading
    return found


def excursion_open(readings) -> bool:
    """Whether a value is still out of range: the latest of some key is."""
    return any(not reading.in_range for reading in latest(readings).values())
