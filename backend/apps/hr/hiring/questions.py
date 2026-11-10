"""What a vacancy may ask, and how the bot checks an answer.

A vacancy's `questions` is a list of at most `MAX_QUESTIONS`:

    {"id": "q1a2b3", "text": "Farmatsevtik ma’lumotingiz bormi?", "kind": "yes_no",
     "required": True, "options": []}

`kind` is text, choice (2 to `MAX_OPTIONS` options, shown as buttons), yes_no (two buttons) or
number. An applicant's answers keep the question as they read it, so a later edit of the vacancy
never changes what someone answered:

    {"id": "q1a2b3", "text": "…", "kind": "yes_no", "answer": "yes"}     ("" when skipped)
"""

import re
import secrets
from decimal import Decimal, InvalidOperation

from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.hr.models import QuestionKind

MAX_QUESTIONS = 8
MAX_OPTIONS = 6
TEXT_MAX = 200
OPTION_MAX = 40
ANSWER_MAX = 500
YES, NO = "yes", "no"
ID = re.compile(r"^q[a-z0-9]{1,15}$")
# "3", "2,5", "3 yil", "5 лет": a number, then perhaps a word for its unit.
NUMBER = re.compile(r"^(\d{1,12}(?:[.,]\d{1,2})?)\s*[^\d]{0,20}$")
# "5 000 000" or "5.000.000": digits in groups of three.
THOUSANDS = re.compile(r"^(\d{1,3}(?:[  .,]\d{3})+)(?!\d)")


def new_id() -> str:
    return f"q{secrets.token_hex(3)}"


def clean(raw) -> list[dict]:
    """The questions as stored, from what the dashboard sent; DomainError says what's wrong."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise DomainError(_("Send the questions as a list."))
    if len(raw) > MAX_QUESTIONS:
        raise DomainError(
            _("A vacancy can ask at most %(count)d questions.") % {"count": MAX_QUESTIONS}
        )
    cleaned: list[dict] = []
    seen: set[str] = set()
    for number, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise DomainError(_("Question %(number)d is not filled in.") % {"number": number})
        text = " ".join(str(item.get("text") or "").split())
        if not text:
            raise DomainError(_("Question %(number)d has no text.") % {"number": number})
        if len(text) > TEXT_MAX:
            raise DomainError(
                _("Question %(number)d is longer than %(count)d characters.")
                % {"number": number, "count": TEXT_MAX}
            )
        kind = item.get("kind") or QuestionKind.TEXT
        if kind not in QuestionKind.values:
            raise DomainError(_("Question %(number)d has an unknown kind.") % {"number": number})
        options = _options(item.get("options"), number) if kind == QuestionKind.CHOICE else []
        qid = str(item.get("id") or "")
        if not ID.match(qid) or qid in seen:
            qid = new_id()
            while qid in seen:
                qid = new_id()
        seen.add(qid)
        cleaned.append(
            {
                "id": qid,
                "text": text,
                "kind": str(kind),
                "required": bool(item.get("required", True)),
                "options": options,
            }
        )
    return cleaned


def _options(raw, number: int) -> list[str]:
    options = [" ".join(str(option or "").split()) for option in (raw or [])]
    options = [option for option in options if option]
    if len(options) < 2:
        raise DomainError(_("Question %(number)d needs at least two options.") % {"number": number})
    if len(options) > MAX_OPTIONS:
        raise DomainError(
            _("Question %(number)d can have at most %(count)d options.")
            % {"number": number, "count": MAX_OPTIONS}
        )
    if any(len(option) > OPTION_MAX for option in options):
        raise DomainError(
            _("An option of question %(number)d is longer than %(count)d characters.")
            % {"number": number, "count": OPTION_MAX}
        )
    if len({option.casefold() for option in options}) != len(options):
        raise DomainError(_("Question %(number)d has the same option twice.") % {"number": number})
    return options


# Answers -----------------------------------------------------------------------------------


def text_answer(value: str | None) -> str | None:
    """A typed answer, or None when it's empty or too long."""
    text = (value or "").strip()
    if not text or len(text) > ANSWER_MAX:
        return None
    return text


def number_answer(value: str | None) -> str | None:
    """ "3", "2,5", "3 yil" or "5 000 000 so‘m" as a plain number ("3", "2.5", "5000000");
    None for anything else."""
    text = (value or "").strip()
    grouped = THOUSANDS.match(text)
    if grouped is not None:
        text = re.sub(r"\D", "", grouped.group(1)) + text[grouped.end() :]
    found = NUMBER.match(text)
    if found is None:
        return None
    try:
        number = Decimal(found.group(1).replace(",", "."))
    except InvalidOperation:
        return None
    return format(number.normalize(), "f")


def choice_answer(question: dict, index: int) -> str | None:
    options = question.get("options") or []
    if not 0 <= index < len(options):
        return None
    return options[index]


def answer_row(question: dict, answer: str) -> dict:
    return {
        "id": question["id"],
        "text": question["text"],
        "kind": question["kind"],
        "answer": answer,
    }


def shown(row: dict) -> str:
    """An answer as the reader reads it (yes and no in their language); "—" when skipped."""
    answer = row.get("answer") or ""
    if not answer:
        return "—"
    if row.get("kind") == QuestionKind.YES_NO:
        return _("Yes") if answer == YES else _("No")
    return answer
