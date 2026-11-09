"""What the bots say about learning (package Q2: the question of the day, checks, the tutor).

Plain, short, no emoji (apps/notifications/tests/test_emoji.py reads every literal here). Call
these under the reader's language.

The question of the day (docs/PLAN-LEARNING.md §9.2): "Question of the day", the question and
its options lettered A to F; a short option is written on its button, long ones in the message
with only their letters on the buttons. One tap answers a one-answer or a true-or-false
question; with several right answers the taps choose (the chosen letters show in the message)
and "Answer" sends them. The other kinds are answered in the app. Once answered, the message
becomes the result: the answer, right or not, the right answer, the explanation, points and the
streak, with "Open in the app".
"""

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from django.conf import settings
from django.utils.translation import gettext as _
from django.utils.translation import ngettext, pgettext

from apps.learning import grading
from apps.learning.callbacks import FALSE, TRUE, DailyAction, DailyCallback
from apps.learning.models import DailyQuestion, Question
from apps.members.bot_messages import BotMessage, miniapp_url

# Kinds answered with buttons in the bot; the others only in the app.
BOT_KINDS = (Question.Kind.SINGLE, Question.Kind.MULTI, Question.Kind.TRUE_FALSE)
# The mini app's screen of the question of the day.
DAILY_SCREEN = "daily"
# An option this short is written on its button.
BUTTON_TEXT = 28
# Telegram takes 4096 characters; the explanation gives way first.
MESSAGE_MAX = 4000


def _title() -> str:
    return f"<b>{html.quote(_('Question of the day'))}</b>"


def _letters(order: list[str]) -> dict[str, str]:
    return {value: grading.LETTERS[index] for index, value in enumerate(order)}


def _true() -> str:
    return pgettext("true or false answer", "True")


def _false() -> str:
    return pgettext("true or false answer", "False")


def _app_button(label: str) -> InlineKeyboardButton | None:
    """Opens the app's question of the day (Telegram only takes https Mini App links)."""
    if not settings.EMPLOYEE_MINIAPP_URL.startswith("https://"):
        return None
    return InlineKeyboardButton(text=label, web_app=WebAppInfo(url=miniapp_url(DAILY_SCREEN)))


def _options(question: Question, order: list[str]) -> list[tuple[str, str, str]]:
    """(id, letter, text) of a one-answer or several-answers question, as shown."""
    texts = {option["id"]: option["text"] for option in question.data.get("options", [])}
    return [(value, grading.LETTERS[index], texts[value]) for index, value in enumerate(order)]


def daily_message(daily: DailyQuestion) -> BotMessage:
    """The question as sent: its buttons, or the way to the app for the other kinds."""
    question = daily.question
    order = grading.reconcile(question.kind, question.data, daily.order)
    lines = [_title(), "", html.quote(question.text)]
    rows: list[list[InlineKeyboardButton]] = []
    if question.kind == Question.Kind.TRUE_FALSE:
        lines += ["", html.quote(_("True or false?"))]
        rows.append(
            [
                _button(_true(), DailyAction.PICK, daily, TRUE),
                _button(_false(), DailyAction.PICK, daily, FALSE),
            ]
        )
    elif question.kind in (Question.Kind.SINGLE, Question.Kind.MULTI):
        options = _options(question, order)
        long = any(len(text) > BUTTON_TEXT for _value, _letter, text in options)
        if long:
            lines.append("")
            lines += [f"{letter}. {html.quote(text)}" for _value, letter, text in options]
        if question.kind == Question.Kind.SINGLE:
            lines += ["", html.quote(_("Choose one answer."))]
        else:
            lines += ["", html.quote(_("Choose every right answer, then press «Answer»."))]
            chosen = (daily.answer or {}).get("options") or []
            if chosen:
                letters = _letters(order)
                picked = ", ".join(letters[value] for value in order if value in chosen)
                lines.append(html.quote(_("Chosen: %(letters)s") % {"letters": picked}))
        buttons = [
            _button(letter if long else f"{letter}. {text}", DailyAction.PICK, daily, value)
            for value, letter, text in options
        ]
        rows += [buttons] if long else [[button] for button in buttons]
        if question.kind == Question.Kind.MULTI:
            label = pgettext("question of the day button", "Answer")
            rows.append([_button(label, DailyAction.SEND, daily)])
    else:
        lines += ["", html.quote(_("This one is answered in the app."))]
        if button := _app_button(_("Answer in the app")):
            rows.append([button])
    markup = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
    return "\n".join(lines), markup


def _button(text: str, action: DailyAction, daily: DailyQuestion, option: str = ""):
    data = DailyCallback(action=action, daily_id=daily.pk, option=option).pack()
    return InlineKeyboardButton(text=text[:60], callback_data=data)


def describe(question: Question, order: list[str], answer: dict | None) -> str:
    """An answer of any kind in plain words (the bot's result line)."""
    if not answer:
        return "—"
    order = grading.reconcile(question.kind, question.data, order)
    kind, data = question.kind, question.data
    if kind == Question.Kind.TRUE_FALSE:
        return _true() if answer.get("value") else _false()
    if kind in (Question.Kind.SINGLE, Question.Kind.MULTI):
        picked = [answer["option"]] if "option" in answer else answer.get("options", [])
        options = _options(question, order)
        return "; ".join(
            f"{letter}. {text}" for value, letter, text in options if value in set(picked)
        )
    if kind == Question.Kind.ORDER:
        texts = {item["id"]: item["text"] for item in data.get("items", [])}
        real = [grading.real_order_id(order, shown) for shown in answer.get("order", [])]
        return "; ".join(
            f"{index}. {texts[value]}" for index, value in enumerate(real, 1) if value in texts
        )
    if kind == Question.Kind.MATCH:
        pairs = data.get("pairs", [])
        rights = {pair["id"]: pair["right"] for pair in pairs}
        lines = []
        for index, pair in enumerate(pairs):
            shown = answer.get("pairs", {}).get(f"{grading.LEFT_ID}{index + 1}")
            real = grading.real_right_id(order, shown) if shown else None
            lines.append(f"{pair['left']} — {rights.get(real, '—')}")
        return "; ".join(lines)
    if kind == Question.Kind.TEXT:
        return str(answer.get("text", ""))
    if kind == Question.Kind.NUMBER:
        unit = data.get("unit") or ""
        return f"{answer.get('value')} {unit}".strip()
    return "—"


def daily_result(
    daily: DailyQuestion, *, points: int | None = None, streak: int | None = None
) -> BotMessage:
    """What the message says once answered (in the bot or the app)."""
    question = daily.question
    order = daily.order
    right = grading.right_answer(question.kind, question.data, order)
    lines = [_title(), "", html.quote(question.text), ""]
    mine = describe(question, order, daily.answer)
    lines.append(html.quote(_("Your answer: %(answer)s") % {"answer": mine}))
    if daily.correct:
        lines.append(f"<b>{html.quote(_('Right!'))}</b>")
    else:
        lines.append(f"<b>{html.quote(_('Not quite.'))}</b>")
        shown = describe(question, order, right)
        lines.append(html.quote(_("The right answer: %(answer)s") % {"answer": shown}))
    tail = []
    if points:
        tail.append(html.quote(_("Points: +%(points)s") % {"points": points}))
    if streak:
        tail.append(
            html.quote(
                ngettext(
                    "Learning streak: %(count)s day",
                    "Learning streak: %(count)s days",
                    streak,
                )
                % {"count": streak}
            )
        )
    text = "\n".join(lines)
    explanation = (question.explanation or "").strip()
    if explanation:
        room = MESSAGE_MAX - len(text) - sum(len(line) + 1 for line in tail) - 4
        if room > 40:
            clipped = explanation if len(explanation) <= room else explanation[: room - 1] + "…"
            text += "\n\n" + html.quote(clipped)
    if tail:
        text += "\n\n" + "\n".join(tail)
    button = _app_button(_("Open in the app"))
    markup = InlineKeyboardMarkup(inline_keyboard=[[button]]) if button else None
    return text, markup
