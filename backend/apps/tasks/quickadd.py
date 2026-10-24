"""Quick add: the deadline, repeat and urgency in what people type, in Uzbek, Russian, English.

    parse("Narx yorliqlarini yangilash ertaga 10:00", now=now)
    # QuickAdd(title="Narx yorliqlarini yangilash", due_at=<tomorrow 10:00>, ...)

Only the two ends of the text are read ("ertaga 10:00 ..." or "... ertaga 10:00"), so a date
word inside a title stays part of it. `now` is timezone-aware, in the company's timezone
(Asia/Tashkent is UTC+5 all year, no daylight saving). Uzbek is read in Latin and Cyrillic, and
in the 2027 alphabet too (ö ğ ş ç next to o‘ g‘ sh ch), with any apostrophe. Standard library
only; the rules and their tests come from research R2 §6 (docs: the scratchpad's r2-tasks.md).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

# A part of the day as a deadline, and when it is over ("bugun kechqurun" at 19:00 still fits).
PARTS = {
    "morning": (time(9, 0), time(12, 0)),
    "noon": (time(12, 0), time(13, 0)),
    "lunch": (time(13, 0), time(14, 0)),
    "afternoon": (time(15, 0), time(18, 0)),
    "evening": (time(18, 0), time(22, 0)),
    "night": (time(21, 0), time(23, 59)),
    "midnight": (time(23, 59), time(23, 59)),
}
PM_PARTS = frozenset({"noon", "lunch", "afternoon", "evening"})
DEFAULT_TIME = time(18, 0)  # a day without a time: by the end of the working day
END_OF_DAY = time(18, 0)  # "kun oxirigacha": pass the branch's closing time where it's known
ROLLOVER_HOUR = 5  # before 05:00 "ertaga" still means the coming morning (night shifts)


@dataclass(frozen=True)
class QuickAdd:
    """What a typed text says. Positions in `spans` are the original text's."""

    title: str
    due_at: datetime | None = None
    day: date | None = None  # a day was given but its time has to be asked
    repeat: str | None = None  # daily / weekdays / weekly (apps.tasks.models.Repeat), or None
    repeat_weekdays: tuple[int, ...] | None = None  # 0 = Monday; for weekly, the due's weekday
    priority: str | None = None  # "urgent" when the text says so
    spans: tuple[tuple[int, int], ...] = ()  # what was read as a date, in the original text
    guessed_time: bool = False  # no time was given: `due_at` carries the default time
    rolled: bool = False  # a time that had passed today: moved to tomorrow
    past: bool = False  # an explicit moment that has already passed: nothing set
    passed: datetime | None = None  # that moment, so the same time tomorrow can be offered

    @property
    def found(self) -> bool:
        return bool(self.spans)


@dataclass
class _Spec:
    date_parts: tuple[int, int, int | None] | None = None
    offset: int | None = None  # 0 today, 1 tomorrow, 2 the day after
    weekday: int | None = None  # 0 = Monday
    week_mod: str | None = None  # "next" (next week's) or "this"
    special: str | None = None  # next_week, weekend, next_weekend, eom
    days_later: int | None = None
    hour: int | None = None
    minute: int = 0
    ampm: str | None = None
    exact: bool = False  # "03:00", "15:00": the hour is meant as written
    part: str | None = None
    delta: timedelta | None = None
    repeat: str = "none"
    priority: str | None = None

    def has_day(self) -> bool:
        days = (self.date_parts, self.offset, self.weekday, self.special, self.days_later)
        return any(value is not None for value in days)

    def has_time(self) -> bool:
        return self.hour is not None or self.part is not None


# — reading the text —

_APOSTROPHES = str.maketrans(dict.fromkeys("‘’ʻʼ`´′‛", "'"))
_EDGE = ' \t\n,.;:!?()[]«»"—–-'
_LEFT = r"(?<![^\s,(«\"])"  # the start, or after a space, comma, bracket or quote
_TAIL = r"[\s,.;:!?)»\"]*$"
_RIGHT = r"(?=$|[\s,.;:!?)»\"])"


# The 2027 Uzbek letters, read as today's spelling: duşanba = dushanba, keçqurun = kechqurun.
_FOLD = {"ö": "o'", "ğ": "g'", "ş": "sh", "ç": "ch", "ё": "е", "\u00a0": " "}


def _normalize(text: str) -> tuple[str, list[int]]:
    """Lower case, one apostrophe, today's Uzbek letters, the Russian yo read as ye, plain spaces;
    and for each character of the result, the position of the original character it came from
    (one more entry at the end: the original's length). ş becomes two characters, so positions
    must be mapped back rather than shared."""
    chars: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(text.translate(_APOSTROPHES)):
        low = char.lower()
        for piece in _FOLD.get(low, low if len(low) == 1 else char):
            chars.append(piece)
            origin.append(index)
    origin.append(len(text))
    return "".join(chars), origin


def _start_of(origin: list[int], index: int) -> int:
    """The original position where the normalized character `index` starts."""
    return origin[index]


def _end_of(origin: list[int], index: int) -> int:
    """The original position just after the normalized characters before `index`."""
    return origin[index - 1] + 1 if index > 0 else 0


def _alt(words) -> str:
    return "|".join(sorted((re.escape(word) for word in words), key=len, reverse=True))


_UZ_UNITS = {
    "bir": 1,
    "ikki": 2,
    "uch": 3,
    "to'rt": 4,
    "besh": 5,
    "olti": 6,
    "yetti": 7,
    "sakkiz": 8,
    "to'qqiz": 9,
}
_UZ_TENS = {"o'n": 10, "yigirma": 20, "o'ttiz": 30, "qirq": 40, "ellik": 50}
_RU_NUMBERS = {
    "один": 1,
    "одну": 1,
    "пару": 2,
    "два": 2,
    "две": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "десять": 10,
    "пятнадцать": 15,
    "двадцать": 20,
    "тридцать": 30,
    "сорок": 40,
}
_EN_NUMBERS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "ten": 10,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
}
_UZ_NUM = (
    "(?:(?:" + _alt(_UZ_TENS) + r")(?:\s+(?:" + _alt(_UZ_UNITS) + "))?|" + _alt(_UZ_UNITS) + ")"
    r"(?:\s+yarim)?|yarim"
)
_UZ_HOUR = r"o'n\s+(?:bir|ikki)|o'n|" + _alt(_UZ_UNITS)

_WD_UZ = {
    "dushanba": 0,
    "seshanba": 1,
    "chorshanba": 2,
    "payshanba": 3,
    "juma": 4,
    "shanba": 5,
    "yakshanba": 6,
    "душанба": 0,
    "сешанба": 1,
    "чоршанба": 2,
    "пайшанба": 3,
    "жума": 4,
    "шанба": 5,
    "якшанба": 6,
}
_WD_RU = {
    "понедельник": 0,
    "вторник": 1,
    "сред": 2,
    "четверг": 3,
    "пятниц": 4,
    "суббот": 5,
    "воскресен": 6,
    "пн": 0,
    "вт": 1,
    "ср": 2,
    "чт": 3,
    "пт": 4,
    "сб": 5,
    "вс": 6,
}
_WD_EN = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_WD_UZ_RE = _alt(_WD_UZ)
_WD_RU_RE = (
    r"понедельник[ауе]?|вторник[ауе]?|сред[аеуы]|четверг[ауе]?|пятниц[аеуы]"
    r"|суббот[аеуы]|воскресень[еяю]|пн|вт|ср|чт|пт|сб|вс"
)
_WD_EN_RE = (
    r"monday|mon|tuesday|tues|tue|wednesday|wed|thursday|thurs|thur|thu|friday|fri"
    r"|saturday|sat|sunday|sun"
)

_MONTHS = {
    "yanvar": 1,
    "fevral": 2,
    "mart": 3,
    "aprel": 4,
    "may": 5,
    "iyun": 6,
    "iyul": 7,
    "avgust": 8,
    "sentabr": 9,
    "sentyabr": 9,
    "oktabr": 10,
    "oktyabr": 10,
    "noyabr": 11,
    "dekabr": 12,
    "январ": 1,
    "феврал": 2,
    "март": 3,
    "апрел": 4,
    "ма": 5,
    "июн": 6,
    "июл": 7,
    "август": 8,
    "сентябр": 9,
    "октябр": 10,
    "ноябр": 11,
    "декабр": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_MONTH_UZ_RU_RE = (
    r"yanvar|fevral|mart|aprel|may|iyun|iyul|avgust|senty?abr|okty?abr"
    r"|noyabr|dekabr|январ[ья]?|феврал[ья]?|марта?|апрел[ья]?|ма[йя]|июн[ья]?"
    r"|июл[ья]?|августа?|сентябр[ья]?|октябр[ья]?|ноябр[ья]?|декабр[ья]?"
)
_MONTH_EN_RE = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)


def _weekday_of(word: str) -> int:
    for table in (_WD_UZ, _WD_RU, _WD_EN):
        for stem in sorted(table, key=len, reverse=True):
            if word.startswith(stem):
                return table[stem]
    raise ValueError(word)


def _month_of(word: str) -> int:
    return _MONTHS[max((stem for stem in _MONTHS if word.startswith(stem)), key=len)]


def _number(text: str) -> float:
    text = re.sub(r"\s+", " ", text)
    if text[0].isdigit():
        return float(text.replace(",", "."))
    if text in _RU_NUMBERS:
        return _RU_NUMBERS[text]
    if text in _EN_NUMBERS:
        return _EN_NUMBERS[text]
    return sum(
        0.5 if w == "yarim" else _UZ_TENS.get(w) or _UZ_UNITS.get(w, 0) for w in text.split()
    )


_UNITS = [
    ("daq", "minutes"),
    ("дақ", "minutes"),
    ("дак", "minutes"),
    ("min", "minutes"),
    ("мин", "minutes"),
    ("m", "minutes"),
    ("soat", "hours"),
    ("соат", "hours"),
    ("час", "hours"),
    ("ч", "hours"),
    ("h", "hours"),
    ("kun", "days"),
    ("кун", "days"),
    ("дн", "days"),
    ("d", "days"),
    ("hafta", "weeks"),
    ("ҳафта", "weeks"),
    ("хафта", "weeks"),
    ("недел", "weeks"),
    ("w", "weeks"),
]


# — the rules, tried in this order at each end of the text —

Apply = Callable[[dict, _Spec], bool]
_RULES: list[tuple[re.Pattern, re.Pattern, Apply]] = []


def _rule(body: str) -> Callable[[Apply], Apply]:
    def register(apply: Apply) -> Apply:
        _RULES.append(
            (
                re.compile(_LEFT + "(?:" + body + ")" + _TAIL),
                re.compile("(?:" + body + ")" + _RIGHT),
                apply,
            )
        )
        return apply

    return register


@_rule(
    r"(?P<daily>har\s+kuni?|[ҳх]ар\s+куни?|кажд(?:ый|ое)\s+день|ежедневно|every\s*day|daily)"
    r"|(?P<workdays>(?:har\s+)?ish\s+kunlari(?:da)?|har\s+ish\s+kuni|(?:[ҳх]ар\s+)?иш\s+кунлари(?:да)?"
    r"|по\s+будням|в\s+будни|every\s+weekday|(?:on\s+)?weekdays)"
    r"|(?P<weekly>(?:har|[ҳх]ар)\s+(?:hafta|[ҳх]афта)(?:da|да)?|haftada\s+bir(?:\s+marta)?"
    r"|кажд(?:ую|ая)\s+неделю|еженедельно|every\s+week|weekly)"
    r"|(?:har|[ҳх]ар)\s+(?P<wd_uz>" + _WD_UZ_RE + r")(?:\s+(?:kuni|куни))?"
    r"|кажд(?:ый|ую|ое)\s+(?P<wd_ru>" + _WD_RU_RE + ")"
    r"|по\s+(?P<wd_ru_pl>понедельникам|вторникам|средам|четвергам|пятницам|субботам|воскресеньям)"
    r"|every\s+(?P<wd_en>" + _WD_EN_RE + ")"
    r"|on\s+(?P<wd_en_pl>monday|tuesday|wednesday|thursday|friday|saturday|sunday)s"
)
def _repeat(g: dict, spec: _Spec) -> bool:
    if spec.repeat != "none":
        return False
    word = g["wd_uz"] or g["wd_ru"] or g["wd_ru_pl"] or g["wd_en"] or g["wd_en_pl"]
    if word:
        if spec.has_day() or spec.delta:
            return False
        spec.weekday, spec.repeat = _weekday_of(word), "weekly"
    else:
        spec.repeat = "daily" if g["daily"] else "weekdays" if g["workdays"] else "weekly"
    return True


@_rule(
    r"(?P<n_uz>\d+(?:[.,]\d+)?|" + _UZ_NUM + r")\s*"
    r"(?P<u_uz>soat|daqiqa|minut|min|kun|hafta|соат|дақиқа|дакика|минут|кун|[ҳх]афта)"
    r"(?:dan|дан)?\s+(?:keyin|so'ng|кейин|сўнг)"
    r"|(?P<n_uz_in>\d+(?:[.,]\d+)?|"
    + _UZ_NUM
    + r")\s*(?P<u_uz_in>soat|daqiqa|minut|соат|дақиқа|минут)"
    r"\s+(?:ichida|ичида)"
    r"|через\s+(?:(?P<n_ru>\d+(?:[.,]\d+)?|" + _alt(_RU_NUMBERS) + r")\s*)?"
    r"(?P<u_ru>минут[уы]?|мин\.?|час(?:а|ов)?|ч\.?|дн(?:я|ей)|недел[юиь]|полчаса|полтора\s+часа)"
    r"|в\s+течени[ея]\s+(?:(?P<n_ru_in>\d+|"
    + _alt(_RU_NUMBERS)
    + r")\s*)?(?P<u_ru_in>минут|час(?:а|ов)?)"
    r"|in\s+(?P<n_en>\d+(?:\.\d+)?|" + _alt(_EN_NUMBERS) + r")\s*"
    r"(?P<u_en>minutes?|mins?|m|hours?|hrs?|hr|h|days?|d|weeks?|wks?|w)"
    r"|in\s+(?P<half_en>half\s+an?\s+hour)"
)
def _relative(g: dict, spec: _Spec) -> bool:
    if g["half_en"]:
        amount, kind = 0.5, "hours"
    else:
        number = g["n_uz"] or g["n_uz_in"] or g["n_ru"] or g["n_ru_in"] or g["n_en"]
        unit = g["u_uz"] or g["u_uz_in"] or g["u_ru"] or g["u_ru_in"] or g["u_en"]
        amount = _number(number) if number else 1.0
        if unit == "полчаса":
            amount, unit = 0.5, "час"
        elif unit.startswith("полтора"):
            amount, unit = 1.5, "час"
        kind = next(kind for prefix, kind in _UNITS if unit.startswith(prefix))
    if amount <= 0 or spec.delta or spec.has_day():
        return False
    if kind in ("days", "weeks"):
        days = amount * (7 if kind == "weeks" else 1)
        if days != int(days):
            return False
        spec.days_later = int(days)
        return True
    minutes = amount * (60 if kind == "hours" else 1)
    if spec.has_time() or minutes < 1:  # "yarim daqiqadan keyin" is no deadline
        return False
    spec.delta = timedelta(minutes=minutes)
    return True


@_rule(
    r"(?P<next_weekend>(?:keyingi|kelasi|кейинги|келаси)\s+(?:hafta|[ҳх]афта)\s+(?:oxiri|охири)"
    r"(?:da|да)?|next\s+weekend|на\s+следующих\s+выходных)"
    r"|(?P<next_week>(?:keyingi|kelasi|kelgusi|кейинги|келаси)\s+(?:hafta|[ҳх]афта)(?:da|ga|да|га)?"
    r"|на\s+следующей\s+неделе|next\s+week)"
    r"|(?P<weekend>(?:hafta|[ҳх]афта)\s+(?:oxiri|охири)(?:da|gacha|да|гача)?|на\s+выходных"
    r"|в\s+выходные|к\s+выходным|(?:в|до|к)\s+конц[еау]\s+недели"
    r"|(?:(?:this|the|at\s+the|on\s+the|by\s+the)\s+)?weekend|(?:by\s+)?(?:the\s+)?end\s+of\s+(?:the\s+)?week|eow)"
    r"|(?P<eom>(?:oy|ой)\s+(?:oxiri|охири)(?:da|gacha|да|гача)?|(?:в|до|к)\s+конц[еау]\s+месяца"
    r"|(?:by\s+)?(?:the\s+)?end\s+of\s+(?:the\s+)?month|eom)"
)
def _special(g: dict, spec: _Spec) -> bool:
    if spec.has_day() or spec.delta:
        return False
    spec.special = next(name for name in ("next_weekend", "next_week", "weekend", "eom") if g[name])
    return True


_PART_WORDS = {
    "morning": r"ertalab(?:dan)?|(?:erta\s+)?tongda|эрталаб|утром|с\s+утра|utrom"
    r"|(?:in\s+the\s+|this\s+)?morning",
    "noon": r"tushda|tushgacha|тушда|тушгача|в\s+полдень|к\s+полудню|до\s+обеда"
    r"|(?:at\s+)?(?:noon|midday)",
    "lunch": r"tushlikda|тушликда|в\s+обед|(?:at\s+)?lunch(?:time)?",
    "afternoon": r"tushdan\s+(?:keyin|so'ng)|tushlikdan\s+keyin|kunduzi|тушдан\s+кейин|кундузи|днем"
    r"|после\s+обеда|(?:in\s+the\s+|this\s+)?afternoon",
    "evening": r"kechqurun|kechga|kechgacha|кечқурун|кечкурун|кечга|вечером|к\s+вечеру|до\s+вечера"
    r"|vecherom|(?:in\s+the\s+|this\s+)?evening",
    "night": r"kechasi|tunda|кечаси|тунда|ночью|tonight|(?:at\s+)?night",
    "midnight": r"yarim\s+tunda|yarim\s+kechada|в\s+полночь|к\s+полуночи|до\s+полуночи"
    r"|(?:at\s+|by\s+)?midnight",
    "eod": r"kun\s+oxiri(?:da|gacha)?|кун\s+охири(?:да|гача)?"
    r"|(?:до|к|в)\s+конц[еау]\s+(?:рабочего\s+)?дня"
    r"|(?:by\s+)?(?:the\s+)?end\s+of\s+(?:the\s+)?day|eod|cob",
}


@_rule("|".join(f"(?P<{name}>{words})" for name, words in _PART_WORDS.items()))
def _part(g: dict, spec: _Spec) -> bool:
    if spec.part or spec.delta:
        return False
    spec.part = next(name for name in _PART_WORDS if g[name])
    return True


_SUFFIX = r"(?:\s*-?\s*(?:da|ga|gacha|ga\s+qadar|dan\s+oldin|да|га|гача|га\s+қадар|дан\s+олдин))"
_RU_PARTS = {"утра": "morning", "дня": "afternoon", "вечера": "evening", "ночи": "night"}
_HOURS = ("a_h", "c_h", "d_h", "e_h", "f_h", "g_h", "p_h")
_MINUTES = ("a_m", "c_m", "d_m", "e_m", "f_m", "g_m", "p_m")


def _time(g: dict, spec: _Spec) -> bool:
    if spec.hour is not None or spec.delta:
        return False
    raw = next((g[key] for key in _HOURS if g.get(key)), None)
    if raw is not None:
        hour = int(raw)
    elif g.get("b_w"):
        hour = int(_number(g["b_w"]))
    else:
        return False
    minutes = next((g[key] for key in _MINUTES if g.get(key)), None)
    half = any(g.get(key) for key in ("a_half", "b_half", "c_half"))
    minute = int(minutes) if minutes else 30 if half else 0
    ampm = ("pm" if "p" in g["f_ap"] else "am") if g.get("f_ap") else None
    part = _RU_PARTS.get(g.get("d_part") or g.get("e_part") or "")
    if hour > 23 or minute > 59 or (ampm and not 1 <= hour <= 12):
        return False
    if part and spec.part and part != spec.part:
        return False
    spec.hour, spec.minute, spec.ampm = hour, minute, ampm
    spec.exact = raw is not None and (
        (raw.startswith("0") and len(raw) == 2) or hour >= 13 or hour == 0
    )
    spec.part = part or spec.part
    return True


_rule(
    r"(?:soat|соат)\s*(?P<a_h>\d{1,2})(?:[:.](?P<a_m>\d{2}))?(?:\s+(?P<a_half>yarim|ярим))?"
    + _SUFFIX
    + "?"
    r"|(?:soat|соат)\s+(?P<b_w>" + _UZ_HOUR + r")(?:\s+(?P<b_half>yarim))?" + _SUFFIX + "?"
    r"|(?P<c_h>\d{1,2})(?:[:.](?P<c_m>\d{2}))?(?:\s+(?P<c_half>yarim|ярим))?"
    + _SUFFIX
    + r"|(?:в|во|к|ко|до)\s+(?P<d_h>\d{1,2})(?:[:.](?P<d_m>\d{2}))?(?:\s*(?:ч\.?|час(?:а|ов)?))?"
    r"(?:\s+(?P<d_part>утра|дня|вечера|ночи))?"
    r"|(?P<e_h>\d{1,2})(?:[:.](?P<e_m>\d{2}))?\s*(?:ч\.?|час(?:а|ов)?)?\s+(?P<e_part>утра|дня|вечера|ночи)"
    r"|(?:(?:at|by|until|till|@)\s*)?(?P<f_h>\d{1,2})(?::(?P<f_m>\d{2}))?(?P<f_ap>\s*[ap]\.?m\.?|[ap])"
    r"|(?:at|by|until|till|@)\s*(?P<g_h>\d{1,2})(?::(?P<g_m>\d{2}))?"
)(_time)


@_rule(
    r"(?:(?:on|by|until|до|к)\s+)?(?P<n_d>\d{1,2})[./](?P<n_mo>\d{1,2})(?:[./](?P<n_y>\d{4}|\d{2}))?"
    r"(?:\s*-?\s*(?:da|ga|gacha|да|га|гача))?"
    r"|(?:(?:до|к)\s+)?(?P<m_d>\d{1,2})(?:-?го)?(?:\s*-\s*|\s+)?(?P<m_mon>" + _MONTH_UZ_RU_RE + ")"
    r"(?:ning|da|ga|gacha|dan|нинг|да|га|гача)?"
    r"|(?:(?:on|by|until)\s+)?(?P<e_d>\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<e_mon>"
    + _MONTH_EN_RE
    + ")"
    r"|(?:(?:on|by|until)\s+)?(?P<r_mon>"
    + _MONTH_EN_RE
    + r")\.?\s+(?P<r_d>\d{1,2})(?:st|nd|rd|th)?"
)
def _date(g: dict, spec: _Spec) -> bool:
    if spec.has_day() or spec.delta:
        return False
    if g["n_d"]:
        day, month, year = int(g["n_d"]), int(g["n_mo"]), g["n_y"]
    elif g["m_d"]:
        day, month, year = int(g["m_d"]), _month_of(g["m_mon"]), None
    elif g["e_d"]:
        day, month, year = int(g["e_d"]), _month_of(g["e_mon"]), None
    else:
        day, month, year = int(g["r_d"]), _month_of(g["r_mon"]), None
    year = (int(year) + (2000 if len(year) == 2 else 0)) if year else None
    try:
        date(year or 2024, month, day)  # 2024 has a 29 February
    except ValueError:
        return False
    spec.date_parts = (day, month, year)
    return True


@_rule(
    r"(?:(?P<wu_mod>keyingi|kelasi|kelgusi|shu|bu|кейинги|келаси|шу|бу)\s+)?(?P<wu>"
    + _WD_UZ_RE
    + ")"
    r"(?:\s+(?:kuni|куни)|gacha|ga|da|гача|га|да)?"
    r"|(?:(?:в|во|к|ко|до|на)\s+)?(?:(?P<wr_mod>следующ(?:ий|ую|ее|ей|его)|эт(?:от|у|о)"
    r"|ближайш(?:ий|ую|ее|ей|его))\s+)?(?P<wr>" + _WD_RU_RE + ")"
    r"|(?:(?:on|by|until|till)\s+)?(?:(?P<we_mod>next|this|coming)\s+)?(?P<we>" + _WD_EN_RE + ")"
)
def _weekday(g: dict, spec: _Spec) -> bool:
    if spec.has_day() or spec.delta:
        return False
    mod = g["wu_mod"] or g["wr_mod"] or g["we_mod"] or ""
    spec.weekday = _weekday_of(g["wu"] or g["wr"] or g["we"])
    if mod.startswith(("keyingi", "kelasi", "kelgusi", "кейинги", "келаси", "следующ", "next")):
        spec.week_mod = "next"
    elif mod.startswith(("shu", "bu", "шу", "бу", "эт", "this")):
        spec.week_mod = "this"
    return True


@_rule(
    r"(?P<du>bugunoq|bugun|ertagacha|ertaga|indinga|indin|бугун|эртагача|эртага|индинга|индин)"
    r"|(?:(?:на|к|до)\s+)?(?P<dr>сегодня|завтра|послезавтра|segodnya|zavtra|poslezavtra)"
    r"|(?P<de>today|tdy|tomorrow|tmrw|tmr|day\s+after\s+tomorrow)"
)
def _day(g: dict, spec: _Spec) -> bool:
    if spec.has_day() or spec.delta:
        return False
    word = g["du"] or g["dr"] or g["de"]
    if word.startswith(("bugun", "бугун", "сегодня", "segodnya", "today", "tdy")):
        spec.offset = 0
    elif word.startswith(("indin", "индин", "послезавтра", "poslezavtra", "day")):
        spec.offset = 2
    else:
        spec.offset = 1
    return True


_rule(r"(?P<p_h>\d{1,2})[:.](?P<p_m>\d{2})")(_time)  # a bare clock, after dates: "25.10" is a date


@_rule(r"(?P<urgent>srochno|срочно|shoshilinch|zudlik\s+bilan|urgent|asap)")
def _priority(g: dict, spec: _Spec) -> bool:
    if spec.priority:
        return False
    spec.priority = "urgent"
    return True


def _peel(s: str, spec: _Spec, end: int) -> tuple[int, int, list[tuple[int, int]]]:
    """Take date phrases off both ends of `s` until neither end reads as one."""
    start, spans = 0, []
    while True:
        while end > start and s[end - 1] in _EDGE:
            end -= 1
        while start < end and s[start] in _EDGE:
            start += 1
        if start >= end:
            break
        for at_end, _, apply in _RULES:
            match = at_end.search(s, start, end)
            if match and apply(match.groupdict(), spec):
                spans.append((match.start(), end))
                end = match.start()
                break
        else:
            for _, at_start, apply in _RULES:
                match = at_start.match(s, start, end)
                if match and apply(match.groupdict(), spec):
                    spans.append((start, match.end()))
                    start = match.end()
                    break
            else:
                break
    return start, end, spans


# — turning what was read into a moment —


def _date_of(spec: _Spec, today: date, base: date) -> date | None:
    if spec.date_parts:
        day, month, year = spec.date_parts
        if year:
            return date(year, month, day)
        for add in range(5):  # a date without a year: this year's, else the next one that exists
            try:
                candidate = date(today.year + add, month, day)
            except ValueError:
                continue
            if candidate >= today:
                return candidate
    if spec.offset is not None:
        return max(today, base + timedelta(days=spec.offset))
    if spec.weekday is not None:
        if spec.week_mod == "next":  # next week's (weeks start on Monday)
            return base - timedelta(days=base.weekday()) + timedelta(days=7 + spec.weekday)
        ahead = (spec.weekday - base.weekday()) % 7
        if ahead == 0 and spec.week_mod != "this" and spec.repeat != "weekly":
            ahead = 7  # "dushanba" said on a Monday is next Monday; today is "bugun"
        return base + timedelta(days=ahead)
    if spec.special == "next_week":
        return base - timedelta(days=base.weekday()) + timedelta(days=7)
    if spec.special in ("weekend", "next_weekend"):
        saturday = base + timedelta(days=(5 - base.weekday()) % 7)
        return saturday + timedelta(days=7 if spec.special == "next_weekend" else 0)
    if spec.special == "eom":
        return (base.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    if spec.days_later is not None:
        return today + timedelta(days=spec.days_later)
    return None


def _clock_of(spec: _Spec, parts: dict) -> tuple[time | None, bool]:
    """The time of day, and whether it only came from a part of the day ("kechqurun")."""
    if spec.hour is not None:
        hour = spec.hour
        if spec.ampm == "pm" and hour != 12:
            hour += 12
        elif spec.ampm == "am" and hour == 12:
            hour = 0
        elif spec.ampm is None and not spec.exact and 1 <= hour <= 11:
            if spec.part in PM_PARTS or (spec.part == "night" and hour >= 6):
                hour += 12  # "kechqurun 7 da", "в 7 вечера", "kechasi 11 da"
            elif spec.part is None and hour <= 6:
                hour += 12  # a bare "soat 3 da" / "в 3" is 15:00: nobody works to a 03:00 deadline
        return time(hour, spec.minute), False
    if spec.part:
        return parts[spec.part][0], True
    return None, False


def _soon(now: datetime) -> datetime:
    """An hour from now, on the next :00 or :30."""
    later = (now + timedelta(hours=1)).replace(second=0, microsecond=0)
    return later + timedelta(minutes=(-later.minute) % 30)


def _resolve(spec: _Spec, now: datetime, default_time: time, end_of_day: time) -> dict:
    parts = {**PARTS, "eod": (end_of_day, time(23, 59))}
    if spec.delta is not None:  # counted in UTC, so a daylight-saving change can't bend it
        due = (now.astimezone(UTC) + spec.delta).astimezone(now.tzinfo)
        return {"due": due.replace(second=0, microsecond=0)}
    today = now.date()
    base = today - timedelta(days=1) if now.hour < ROLLOVER_HOUR else today
    day = _date_of(spec, today, base)
    clock, from_part = _clock_of(spec, parts)
    guessed = clock is None
    if clock is None:
        if day is None and spec.repeat == "none":
            return {}
        clock = default_time
    in_part = from_part and now.time() < parts[spec.part][1]
    if day is None:  # a time alone: today, or tomorrow once it has passed
        due = datetime.combine(today, clock, tzinfo=now.tzinfo)
        if due <= now and in_part:
            return {"due": _soon(now)}
        result = {"due": due, "guessed_time": guessed}
        if due <= now:
            result.update(due=due + timedelta(days=1), rolled=True)
    else:
        due = datetime.combine(day, clock, tzinfo=now.tzinfo)
        if spec.part == "night" and spec.hour is not None and clock < time(6):
            due += timedelta(days=1)  # "ertaga kechasi 2 da": the night after that day
        if due <= now and spec.repeat == "weekly" and spec.weekday is not None:
            due += timedelta(days=7)
        if due <= now:
            if in_part and day == today:
                return {"due": _soon(now)}
            if guessed and day == today:
                return {"day": day, "guessed_time": True}  # "bugun" after 18:00: ask the time
            return {"past": True, "passed": due}
        result = {"due": due, "guessed_time": guessed}
    while spec.repeat == "weekdays" and result["due"].weekday() >= 5:
        result["due"] += timedelta(days=1)
    return result


_DANGLING = {
    "в",
    "во",
    "к",
    "ко",
    "до",
    "на",
    "at",
    "on",
    "by",
    "in",
    "until",
    "till",
    "soat",
    "соат",
}


def _title(text: str, start: int, end: int) -> str:
    words = text[start:end].strip(_EDGE).split()
    while words and words[-1].lower() in _DANGLING:
        words.pop()
    while words and words[0].lower() in _DANGLING:
        words.pop(0)
    title = " ".join(words).strip(_EDGE)
    if start > 0 and title:  # the date came first: "ertaga 9 da nakladnoy" -> "Nakladnoy"
        title = title[0].upper() + title[1:]
    return title


def _merge(s: str, spans: list[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    """The phrases to highlight: trailing punctuation off, neighbours joined into one."""
    merged: list[tuple[int, int]] = []
    for first, last in sorted(spans):
        while last > first and s[last - 1] in _EDGE:
            last -= 1
        if merged and not s[merged[-1][1] : first].strip(" ,"):
            merged[-1] = (merged[-1][0], last)
        else:
            merged.append((first, last))
    return tuple(merged)


def parse(
    text: str,
    *,
    now: datetime,
    lang: str | None = None,
    default_time: time = DEFAULT_TIME,
    end_of_day: time = END_OF_DAY,
) -> QuickAdd:
    """What `text` says about when (and how often, and how urgently) the task is due.

    `lang` is the writer's language (uz, ru, en). Every language is read whatever it is, so
    nobody has to pick one first; it is there for callers that word the result."""
    if now.tzinfo is None:
        raise ValueError("`now` must be timezone-aware, in the company's timezone.")
    # "!!" anywhere makes it urgent ("Kassa!!", "Dori !! ertaga"); the marks leave the title.
    bangs = [match.span() for match in _BANGS.finditer(text)]
    plain = _blank(text, bangs)
    s, origin = _normalize(plain)
    spec = _Spec(priority="urgent" if bangs else None)
    start, end, spans = _peel(s, spec, len(s))
    found = _merge(s, spans)
    if not found and not bangs:
        return QuickAdd(title=text.strip())
    moment = _resolve(spec, now, default_time, end_of_day)
    due_at = moment.pop("due", None)
    repeat = None if spec.repeat == "none" else spec.repeat
    return QuickAdd(
        title=_title(plain, _start_of(origin, start), _end_of(origin, end)) if start < end else "",
        due_at=due_at,
        repeat=repeat,
        repeat_weekdays=_repeat_weekdays(repeat, due_at, spec.weekday),
        priority=spec.priority,
        spans=tuple(sorted([(_start_of(origin, a), _end_of(origin, b)) for a, b in found] + bangs)),
        **moment,
    )


_BANGS = re.compile(r"!{2,}")


def _blank(text: str, spans: list[tuple[int, int]]) -> str:
    """`text` with spaces over `spans`: the same length, so positions still match."""
    for first, last in spans:
        text = text[:first] + " " * (last - first) + text[last:]
    return text


def _repeat_weekdays(
    repeat: str | None, due_at: datetime | None, weekday: int | None
) -> tuple[int, ...] | None:
    """The days a repeat runs on (0 = Monday), as `apps.tasks.services` sets a repeat up."""
    if repeat == "daily":
        return tuple(range(7))
    if repeat == "weekdays":
        return (0, 1, 2, 3, 4)
    if repeat == "weekly":
        day = due_at.weekday() if due_at is not None else weekday
        return (day,) if day is not None else None
    return None
