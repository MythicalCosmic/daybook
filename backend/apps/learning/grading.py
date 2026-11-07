"""The seven kinds of question: what `Question.data` holds, what a person is shown, what they
answer and how it is graded (docs/PLAN-LEARNING.md §4.3). Pure functions over plain data: the
attempts, the question of the day and the checks all grade through here, on the server only.

    data = clean_data("single", raw)                 # on save; InvalidQuestion with the problems
    order = shown_order("single", data, shuffle=True)
    play_shape = play(question, order)               # what the app shows: never the right answer
    answer = clean_answer("single", data, order, {"option": "b"})
    result = grade("single", data, order, answer, partial=True)    # Grade(share, answered)

**What the person is shown, by kind.** Options of `single` and `multi` keep their own ids (the
bot's buttons carry them). The items of `order` are always shuffled and the right side of
`match` too (never in the right order), and both get ids by where they stand on the screen
(`o1`…, `l1`…, `r1`…): the ids an author typed run in the right order and the two sides of a
pair share one, so showing them would give the answer away. `order` (stored on the attempt or
the daily question) is the real ids in the order shown; answers use the ids shown.
"""

from __future__ import annotations

import math
import random
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.learning.models import Question

Kind = Question.Kind

TEXT_MAX = 300
QUESTION_MAX = 1000
UNIT_MAX = 20
ANSWERS_MAX = 10
ID = re.compile(r"^[A-Za-z0-9_-]{1,12}$")
OPTIONS = (2, 6)
ITEMS = (3, 8)
PAIRS = (2, 6)
# Free ids for options an author left without one, in this order.
FREE_IDS = "abcdefghijklmnopqrstuvwxyz"
# What the bot and the app show next to options: A to F.
LETTERS = "ABCDEFGH"

ORDER_ID, LEFT_ID, RIGHT_ID = "o", "l", "r"


class InvalidQuestion(DomainError):
    """A question that doesn't fit its kind. `errors` maps where (``"data.options.1.text"``,
    ``"data.options"``, ``"kind"``) to what is wrong; the message is the first problem."""

    def __init__(self, errors: dict[str, list[str]]):
        self.errors = errors
        first = next(iter(errors.values()), [""])
        super().__init__(first[0] if first else "")


class InvalidAnswer(DomainError):
    pass


class _Errors:
    def __init__(self):
        self.found: dict[str, list[str]] = {}

    def add(self, where: str, message: str) -> None:
        self.found.setdefault(where, []).append(message)

    def raise_if_any(self) -> None:
        if self.found:
            raise InvalidQuestion(self.found)


# Validation of `data` ----------------------------------------------------------------------


def clean_data(kind: str, data) -> dict:
    """`data` as stored for `kind`: only the known keys, texts trimmed, missing ids filled in.
    Raises InvalidQuestion with every problem found (§4.3: the shapes, unique ids, the counts,
    non-empty texts of at most 300 characters, a tolerance of 0 or more)."""
    if kind not in Kind.values:
        raise InvalidQuestion({"kind": [_("Pick a kind of question.")]})
    errors = _Errors()
    raw = data if isinstance(data, dict) else {}
    if not isinstance(data, dict):
        errors.add("data", _("The question has no answer part."))
    cleaned = CLEANERS[kind](raw, errors)
    errors.raise_if_any()
    return cleaned


def clean_text(value, *, where: str = "text", limit: int = QUESTION_MAX) -> str:
    """The question's own text: trimmed, not empty, at most `limit` characters."""
    errors = _Errors()
    text = _text(value, errors, where, limit=limit)
    errors.raise_if_any()
    return text


def _text(value, errors: _Errors, where: str, *, limit: int = TEXT_MAX) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        errors.add(where, _("Write something here."))
    elif len(text) > limit:
        errors.add(where, _("Keep it under %(max)s characters.") % {"max": limit})
    return text


def _list(raw: dict, key: str, errors: _Errors, bounds: tuple[int, int], message: str) -> list:
    found = raw.get(key)
    if not isinstance(found, list):
        errors.add(f"data.{key}", message)
        return []
    low, high = bounds
    if not low <= len(found) <= high:
        errors.add(f"data.{key}", _("How many: %(min)s–%(max)s.") % {"min": low, "max": high})
    return [item if isinstance(item, dict) else {} for item in found[: high + 2]]


def _ids(rows: list[dict], errors: _Errors, key: str) -> list[str]:
    """Each row's id: the one given (unique, short, letters and digits), or a free one."""
    given = [row.get("id") for row in rows]
    taken = {value for value in given if isinstance(value, str) and ID.match(value)}
    free = (letter for letter in FREE_IDS if letter not in taken)
    ids: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(given):
        if value in (None, ""):
            value = next(free, f"x{index}")
        elif not isinstance(value, str) or not ID.match(value):
            errors.add(f"data.{key}.{index}.id", _("Use letters and digits for the id."))
            value = f"x{index}"
        if value in seen:
            errors.add(f"data.{key}.{index}.id", _("Two of them have the same id."))
        seen.add(value)
        ids.append(value)
    return ids


def _same_texts(texts: list[str], errors: _Errors, where: str) -> None:
    folded = [normalize_text(text, case=False) for text in texts if text]
    if len(set(folded)) != len(folded):
        errors.add(where, _("Two of them say the same thing."))


def _choice(raw: dict, errors: _Errors, *, exactly_one: bool) -> dict:
    rows = _list(raw, "options", errors, OPTIONS, _("Add the answer options."))
    ids = _ids(rows, errors, "options")
    options = [
        {
            "id": ids[index],
            "text": _text(row.get("text"), errors, f"data.options.{index}.text"),
            "correct": row.get("correct") is True,
        }
        for index, row in enumerate(rows)
    ]
    _same_texts([option["text"] for option in options], errors, "data.options")
    right = sum(option["correct"] for option in options)
    if options and exactly_one and right != 1:
        errors.add("data.options", _("Mark exactly one option as right."))
    if options and not exactly_one and right < 1:
        errors.add("data.options", _("Mark at least one option as right."))
    return {"options": options}


def _single(raw: dict, errors: _Errors) -> dict:
    return _choice(raw, errors, exactly_one=True)


def _multi(raw: dict, errors: _Errors) -> dict:
    return _choice(raw, errors, exactly_one=False)


def _true_false(raw: dict, errors: _Errors) -> dict:
    answer = raw.get("answer")
    if not isinstance(answer, bool):
        errors.add("data.answer", _("Say whether the statement is true or false."))
        answer = False
    return {"answer": answer}


def _order(raw: dict, errors: _Errors) -> dict:
    rows = _list(raw, "items", errors, ITEMS, _("Add the steps in their right order."))
    ids = _ids(rows, errors, "items")
    items = [
        {"id": ids[index], "text": _text(row.get("text"), errors, f"data.items.{index}.text")}
        for index, row in enumerate(rows)
    ]
    _same_texts([item["text"] for item in items], errors, "data.items")
    return {"items": items}


def _match(raw: dict, errors: _Errors) -> dict:
    rows = _list(raw, "pairs", errors, PAIRS, _("Add the pairs to match."))
    ids = _ids(rows, errors, "pairs")
    pairs = [
        {
            "id": ids[index],
            "left": _text(row.get("left"), errors, f"data.pairs.{index}.left"),
            "right": _text(row.get("right"), errors, f"data.pairs.{index}.right"),
        }
        for index, row in enumerate(rows)
    ]
    _same_texts([pair["left"] for pair in pairs], errors, "data.pairs")
    _same_texts([pair["right"] for pair in pairs], errors, "data.pairs")
    return {"pairs": pairs}


def _typed(raw: dict, errors: _Errors) -> dict:
    found = raw.get("answers")
    if not isinstance(found, list) or not found:
        errors.add("data.answers", _("Add at least one accepted answer."))
        found = []
    if len(found) > ANSWERS_MAX:
        errors.add("data.answers", _("At most %(max)s accepted answers.") % {"max": ANSWERS_MAX})
    answers: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(found[:ANSWERS_MAX]):
        text = _text(value, errors, f"data.answers.{index}")
        key = normalize_text(text, case=raw.get("case") is True)
        if text and not key:
            errors.add(f"data.answers.{index}", _("An accepted answer needs letters or digits."))
        elif text and key not in seen:
            seen.add(key)
            answers.append(text)
    return {"answers": answers, "case": raw.get("case") is True}


def _number(raw: dict, errors: _Errors) -> dict:
    value = to_decimal(raw.get("value"))
    if value is None:
        errors.add("data.value", _("Enter the right number."))
    given = raw.get("tolerance")
    tolerance = Decimal(0) if given in (None, "") else to_decimal(given)
    if tolerance is None or tolerance < 0:
        errors.add("data.tolerance", _("The tolerance is 0 or more."))
    unit = raw.get("unit") if isinstance(raw.get("unit"), str) else ""
    unit = unit.strip()
    if len(unit) > UNIT_MAX:
        errors.add("data.unit", _("Keep it under %(max)s characters.") % {"max": UNIT_MAX})
    return {
        "value": _json_number(value),
        "tolerance": _json_number(
            tolerance if tolerance is not None and tolerance >= 0 else Decimal(0)
        ),
        "unit": unit[:UNIT_MAX],
    }


CLEANERS = {
    Kind.SINGLE: _single,
    Kind.MULTI: _multi,
    Kind.TRUE_FALSE: _true_false,
    Kind.ORDER: _order,
    Kind.MATCH: _match,
    Kind.TEXT: _typed,
    Kind.NUMBER: _number,
}


def to_decimal(value) -> Decimal | None:
    """A finite number from a JSON number or a typed one ("4,5", " 4.5 "); None otherwise."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return Decimal(str(value))
    if isinstance(value, str):
        typed = value.strip().replace(" ", "").replace(" ", "").replace(",", ".")
        typed = typed.replace("−", "-")
        if not re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)", typed):
            return None
        try:
            return Decimal(typed)
        except InvalidOperation:
            return None
    return None


def _json_number(value: Decimal | None) -> int | float:
    if value is None:
        return 0
    return int(value) if value == value.to_integral_value() else float(value)


# What the person is shown ------------------------------------------------------------------


def option_ids(kind: str, data: dict) -> list[str]:
    """The real ids that get an order: options, steps or pairs ([] for the other kinds)."""
    key = {
        Kind.SINGLE: "options",
        Kind.MULTI: "options",
        Kind.ORDER: "items",
        Kind.MATCH: "pairs",
    }.get(kind)
    return [row["id"] for row in data.get(key, [])] if key else []


def shown_order(
    kind: str, data: dict, *, shuffle: bool = True, rng: random.Random | None = None
) -> list[str]:
    """The real ids in the order the person sees them. Options of `single` and `multi` are
    shuffled when `shuffle`; the steps of `order` and the right side of `match` always, and
    never left in the right order."""
    rng = rng or random.SystemRandom()
    ids = option_ids(kind, data)
    if kind in (Kind.SINGLE, Kind.MULTI):
        if shuffle:
            rng.shuffle(ids)
        return ids
    if kind in (Kind.ORDER, Kind.MATCH) and len(ids) > 1:
        right = list(ids)
        while ids == right:
            rng.shuffle(ids)
    return ids


def reconcile(kind: str, data: dict, order: list) -> list[str]:
    """`order` (stored when the question was drawn) against the question as it is now: ids
    that went are dropped, new ones come last."""
    current = option_ids(kind, data)
    kept = [value for value in order or [] if value in current]
    return kept + [value for value in current if value not in kept]


def play(question, order: list, *, image_url: str | None = None) -> dict:
    """What the person sees (QuestionPlay): never a right answer."""
    kind, data = question.kind, question.data or {}
    order = reconcile(kind, data, order)
    shape = {
        "id": question.pk,
        "kind": kind,
        "text": question.text,
        "image_url": image_url,
        "points": question.points,
        "options": [],
        "left": [],
        "right": [],
        "unit": None,
    }
    if kind in (Kind.SINGLE, Kind.MULTI):
        texts = {option["id"]: option["text"] for option in data.get("options", [])}
        shape["options"] = [{"id": value, "text": texts[value]} for value in order]
    elif kind == Kind.ORDER:
        texts = {item["id"]: item["text"] for item in data.get("items", [])}
        shape["options"] = [
            {"id": f"{ORDER_ID}{index + 1}", "text": texts[value]}
            for index, value in enumerate(order)
        ]
    elif kind == Kind.MATCH:
        pairs = data.get("pairs", [])
        rights = {pair["id"]: pair["right"] for pair in pairs}
        shape["left"] = [
            {"id": f"{LEFT_ID}{index + 1}", "text": pair["left"]}
            for index, pair in enumerate(pairs)
        ]
        shape["right"] = [
            {"id": f"{RIGHT_ID}{index + 1}", "text": rights[value]}
            for index, value in enumerate(order)
        ]
    elif kind == Kind.NUMBER:
        shape["unit"] = data.get("unit") or None
    return shape


# Answers -----------------------------------------------------------------------------------


def clean_answer(kind: str, data: dict, order: list, answer) -> dict | None:
    """The answer as stored, in the ids shown; None for "no answer" (cleared). Raises
    InvalidAnswer when it doesn't fit the question."""
    if answer is None:
        return None
    if not isinstance(answer, dict):
        raise InvalidAnswer(_("This answer doesn't fit the question."))
    order = reconcile(kind, data, order)
    bad = InvalidAnswer(_("This answer doesn't fit the question."))
    if kind == Kind.SINGLE:
        value = answer.get("option")
        if value in (None, ""):
            return None
        if value not in order:
            raise bad
        return {"option": value}
    if kind == Kind.MULTI:
        values = answer.get("options")
        if not isinstance(values, list) or any(value not in order for value in values):
            raise bad
        picked = [value for value in order if value in set(values)]
        return {"options": picked} if picked else None
    if kind == Kind.TRUE_FALSE:
        value = answer.get("value")
        if not isinstance(value, bool):
            raise bad
        return {"value": value}
    if kind == Kind.ORDER:
        values = answer.get("order")
        shown = [f"{ORDER_ID}{index + 1}" for index in range(len(order))]
        if not isinstance(values, list) or sorted(values) != sorted(shown):
            raise bad
        return {"order": list(values)}
    if kind == Kind.MATCH:
        values = answer.get("pairs")
        lefts = {f"{LEFT_ID}{index + 1}" for index in range(len(data.get("pairs", [])))}
        rights = {f"{RIGHT_ID}{index + 1}" for index in range(len(order))}
        if not isinstance(values, dict) or any(
            left not in lefts or right not in rights for left, right in values.items()
        ):
            raise bad
        return {"pairs": dict(values)} if values else None
    if kind == Kind.TEXT:
        value = answer.get("text")
        if not isinstance(value, str) or len(value) > TEXT_MAX:
            raise bad
        value = value.strip()
        return {"text": value} if value else None
    if kind == Kind.NUMBER:
        raw = answer.get("value")
        if raw in (None, ""):
            return None
        value = to_decimal(raw)
        if value is None:
            raise bad
        return {"value": _json_number(value)}
    raise bad


@dataclass(frozen=True)
class Grade:
    """How one answer scored: `share` of the question's points (0 to 1), and whether there
    was an answer at all."""

    share: Fraction
    answered: bool

    @property
    def correct(self) -> bool:
        return self.share == 1


NOTHING = Grade(Fraction(0), False)


def grade(kind: str, data: dict, order: list, answer, *, partial: bool) -> Grade:
    """Grade `answer` (as `clean_answer` keeps it) on the server (§4.3). An unanswered or
    unfitting answer scores 0; partial credit only for `multi`, `order` and `match`, and only
    when `partial`."""
    try:
        answer = clean_answer(kind, data, order, answer)
    except InvalidAnswer:
        return NOTHING
    if answer is None:
        return NOTHING
    order = reconcile(kind, data, order)
    share = _share(kind, data, order, answer, partial)
    return Grade(max(Fraction(0), min(Fraction(1), share)), True)


def _share(kind: str, data: dict, order: list[str], answer: dict, partial: bool) -> Fraction:
    if kind == Kind.SINGLE:
        right = {option["id"] for option in data["options"] if option["correct"]}
        return Fraction(int(answer["option"] in right))
    if kind == Kind.MULTI:
        right = {option["id"] for option in data["options"] if option["correct"]}
        picked = set(answer["options"])
        if picked == right:
            return Fraction(1)
        if not partial or not right:
            return Fraction(0)
        hits, misses = len(picked & right), len(picked - right)
        return max(Fraction(0), Fraction(hits - misses, len(right)))
    if kind == Kind.TRUE_FALSE:
        return Fraction(int(answer["value"] == data["answer"]))
    if kind == Kind.ORDER:
        given = [_real_order_id(order, value) for value in answer["order"]]
        right = [item["id"] for item in data["items"]]
        if given == right:
            return Fraction(1)
        if not partial or not right:
            return Fraction(0)
        placed = sum(1 for mine, theirs in zip(given, right, strict=False) if mine == theirs)
        return Fraction(placed, len(right))
    if kind == Kind.MATCH:
        pairs = data["pairs"]
        if not pairs:
            return Fraction(0)
        hits = 0
        for index, pair in enumerate(pairs):
            chosen = answer["pairs"].get(f"{LEFT_ID}{index + 1}")
            if chosen is not None and _real_right_id(order, chosen) == pair["id"]:
                hits += 1
        if hits == len(pairs):
            return Fraction(1)
        return Fraction(hits, len(pairs)) if partial else Fraction(0)
    if kind == Kind.TEXT:
        typed = normalize_text(answer["text"], case=data.get("case", False))
        accepted = {normalize_text(text, case=data.get("case", False)) for text in data["answers"]}
        return Fraction(int(bool(typed) and typed in accepted))
    if kind == Kind.NUMBER:
        value, right = to_decimal(answer["value"]), to_decimal(data["value"])
        tolerance = to_decimal(data.get("tolerance", 0)) or Decimal(0)
        if value is None or right is None:
            return Fraction(0)
        return Fraction(int(abs(value - right) <= tolerance))
    return Fraction(0)


def _real_order_id(order: list[str], shown: str) -> str | None:
    index = _position(shown, ORDER_ID)
    return order[index] if index is not None and index < len(order) else None


def _real_right_id(order: list[str], shown: str) -> str | None:
    index = _position(shown, RIGHT_ID)
    return order[index] if index is not None and index < len(order) else None


def _position(shown: str, prefix: str) -> int | None:
    if not isinstance(shown, str) or not shown.startswith(prefix) or not shown[1:].isdigit():
        return None
    index = int(shown[1:]) - 1
    return index if index >= 0 else None


def right_answer(kind: str, data: dict, order: list) -> dict:
    """The right answer in the ids shown, in the answer's own shape (for the review once the
    person has answered)."""
    order = reconcile(kind, data, order)
    if kind == Kind.SINGLE:
        return {"option": next((o["id"] for o in data["options"] if o["correct"]), None)}
    if kind == Kind.MULTI:
        right = {option["id"] for option in data["options"] if option["correct"]}
        return {"options": [value for value in order if value in right]}
    if kind == Kind.TRUE_FALSE:
        return {"value": data["answer"]}
    if kind == Kind.ORDER:
        position = {value: index for index, value in enumerate(order)}
        return {"order": [f"{ORDER_ID}{position[item['id']] + 1}" for item in data["items"]]}
    if kind == Kind.MATCH:
        position = {value: index for index, value in enumerate(order)}
        return {
            "pairs": {
                f"{LEFT_ID}{index + 1}": f"{RIGHT_ID}{position[pair['id']] + 1}"
                for index, pair in enumerate(data["pairs"])
            }
        }
    if kind == Kind.TEXT:
        return {"text": data["answers"][0] if data.get("answers") else ""}
    if kind == Kind.NUMBER:
        return {"value": data["value"]}
    return {}


# Text answers --------------------------------------------------------------------------------

QUOTES = str.maketrans({mark: "'" for mark in "‘’`´ʻʼʹ′‛"})
DASHES = re.compile(r"\s*[‐-―−﹘﹣－-]\s*")
DEGREES = re.compile(r"\s*°\s*[cCсС]?(?![^\W\d_])")
CELSIUS = re.compile(r"(?<=\d)\s*[cCсС](?![^\W\d_])")
EDGES = '.,;:!?"«»“”'


def normalize_text(value: str, *, case: bool) -> str:
    """A typed answer as it is compared (§4.3): trimmed, spaces collapsed, lower case unless
    `case`, the apostrophes of o‘ and ’ unified, dashes unified (and the spaces around them
    dropped), "°C" and a "C" after a number ignored, and stray punctuation at the ends gone."""
    text = unicodedata.normalize("NFKC", value or "")
    text = text.translate(QUOTES)
    text = DEGREES.sub("", text)
    text = CELSIUS.sub("", text)
    text = DASHES.sub("-", text)
    text = " ".join(text.split()).strip(EDGES + " ")
    return text if case else text.lower()


# Scores --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Score:
    score: Decimal
    max_score: Decimal
    percent: int


def total(grades: list[tuple[int, Grade]]) -> Score:
    """The sum of points * share over `(points, grade)` pairs; percent = floor(score / max *
    100)."""
    earned = sum((Fraction(points) * found.share for points, found in grades), Fraction(0))
    possible = sum((Fraction(points) for points, _found in grades), Fraction(0))
    percent = math.floor(earned / possible * 100) if possible else 0
    return Score(_cents(earned), _cents(possible), percent)


def _cents(value: Fraction) -> Decimal:
    return (Decimal(value.numerator) / Decimal(value.denominator)).quantize(Decimal("0.01"))


def share_decimal(share: Fraction) -> Decimal:
    """A share as the answer log keeps it (three decimals)."""
    return (Decimal(share.numerator) / Decimal(share.denominator)).quantize(Decimal("0.001"))
