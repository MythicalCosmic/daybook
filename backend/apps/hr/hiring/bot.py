"""What the employee bot says to applicants, and what the hiring team reads about them.

The bot (call under the reader's language): the vacancy with "Apply", the name, each question
with its buttons, the phone number, a diploma photo when the vacancy asks for one, the summary
before sending, and what an applicant hears later (an interview, an offer, a decision, the hire,
a message from the company). Plain and short, no emoji; a name, a date or a number stands after
a colon or on its own, so no case ending ever follows one in Uzbek.

The team: the inbox notice about a new applicant (plain text, the inbox escapes it).
"""

from datetime import date
from zoneinfo import ZoneInfo

from aiogram import html
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.core.money import format_money
from apps.hr.hiring import questions
from apps.hr.hiring.callbacks import ApplyButton, ApplyStep
from apps.hr.models import Applicant, QuestionKind, Vacancy
from apps.members.bot_messages import BotMessage

LANGUAGES = ("uz", "ru", "en")
LANGUAGE_NAMES = {"uz": "O‘zbekcha", "ru": "Русский", "en": "English"}
# The vacancy's description in the bot: long texts are cut (the dashboard has the whole one).
DESCRIPTION_SHOWN = 1200
CANCEL_WORDS = frozenset({"/cancel", "cancel", "bekor", "bekor qilish", "отмена", "отменить"})


def day(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _button(text: str, step: ApplyStep, vacancy_id: int, q: int = 0, pick: int = 0):
    data = ApplyButton(step=step, v=vacancy_id, q=q, pick=pick).pack()
    return InlineKeyboardButton(text=text, callback_data=data)


def cancel_button(vacancy_id: int) -> InlineKeyboardButton:
    return _button(_("Cancel"), ApplyStep.CANCEL, vacancy_id)


def is_cancel(text: str | None) -> bool:
    return (text or "").strip().lower() in CANCEL_WORDS


# The vacancy -------------------------------------------------------------------------------


def salary(vacancy: Vacancy, language: str) -> str:
    """A range of two amounts, "at least 3 000 000 so‘m", "up to …", or "" without one."""
    currency = vacancy.company.base_currency
    low, high = vacancy.salary_from, vacancy.salary_to
    if low is not None and high is not None:
        if low == high:
            return format_money(low, currency, language)
        return f"{format_money(low, currency, language)} – {format_money(high, currency, language)}"
    if low is not None:
        return _("at least %(amount)s") % {"amount": format_money(low, currency, language)}
    if high is not None:
        return _("up to %(amount)s") % {"amount": format_money(high, currency, language)}
    return ""


def vacancy_card(vacancy: Vacancy, language: str) -> BotMessage:
    """The vacancy as the link opens it, with "Apply" and the three languages."""
    lines = [f"<b>{html.quote(vacancy.title)}</b>", html.quote(vacancy.company.name)]
    if vacancy.branch_id:
        lines.append(_("Branch: %(branch)s") % {"branch": html.quote(vacancy.branch.name)})
    if pay := salary(vacancy, language):
        lines.append(_("Salary: %(salary)s") % {"salary": pay})
    if description := vacancy.description.strip():
        if len(description) > DESCRIPTION_SHOWN:
            description = description[:DESCRIPTION_SHOWN].rsplit(" ", 1)[0] + "…"
        lines += ["", html.quote(description)]
    count = len(vacancy.questions or [])
    lines.append("")
    if count:
        lines.append(
            ngettext(
                "To apply, answer %(count)d question and share your phone number.",
                "To apply, answer %(count)d questions and share your phone number.",
                count,
            )
            % {"count": count}
        )
    else:
        lines.append(_("To apply, give your name and share your phone number."))
    if vacancy.asks_document:
        lines.append(_("Have a photo of your diploma or specialist certificate at hand."))
    rows = [
        [_button(_("Apply"), ApplyStep.APPLY, vacancy.pk)],
        [
            _button(LANGUAGE_NAMES[code], ApplyStep.LANGUAGE, vacancy.pk, pick=index)
            for index, code in enumerate(LANGUAGES)
            if code != language
        ],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def unavailable(state: str, vacancy: Vacancy | None = None) -> str:
    """Why a link takes no application now (services.LinkState)."""
    company = {"company": html.quote(vacancy.company.name)} if vacancy is not None else {}
    if state == "not_yet" and vacancy is not None and vacancy.opens_on:
        return _("This vacancy takes applications from %(date)s.") % {"date": day(vacancy.opens_on)}
    if state == "draft":
        return _("This vacancy isn't open yet. Try again later.")
    if state == "paused":
        return _("This vacancy is paused for now. Try again in a few days.")
    if state == "closed":
        return _("This vacancy is closed. Thank you for your interest.")
    if state == "member" and company:
        return _("You already work here: %(company)s. Ask your manager about this job.") % company
    if state == "limit":
        return _("You have sent several applications today. Try again tomorrow.")
    return _("This vacancy link is invalid. Ask the company for a new one.")


# Applying, step by step --------------------------------------------------------------------


def ask_name(vacancy: Vacancy, suggestion: str) -> BotMessage:
    text = _("What is your name? Type your first and last name.")
    rows = []
    if suggestion:
        text += "\n" + _("Or tap your name below if it is right.")
        rows.append([_button(suggestion, ApplyStep.NAME, vacancy.pk)])
    rows.append([cancel_button(vacancy.pk)])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def bad_name() -> str:
    return _("Please type your first and last name in letters, for example: Aziza Karimova.")


def ask_question(vacancy: Vacancy, index: int) -> BotMessage:
    question = vacancy.questions[index]
    total = len(vacancy.questions)
    header = _("Question %(number)d of %(count)d") % {"number": index + 1, "count": total}
    lines = [header, f"<b>{html.quote(question['text'])}</b>"]
    rows = []
    kind = question["kind"]
    if kind == QuestionKind.CHOICE:
        rows += [
            [_button(option, ApplyStep.ANSWER, vacancy.pk, q=index, pick=pick)]
            for pick, option in enumerate(question.get("options") or [])
        ]
    elif kind == QuestionKind.YES_NO:
        rows.append(
            [
                _button(_("Yes"), ApplyStep.ANSWER, vacancy.pk, q=index, pick=1),
                _button(_("No"), ApplyStep.ANSWER, vacancy.pk, q=index, pick=0),
            ]
        )
    elif kind == QuestionKind.NUMBER:
        lines.append(_("Answer with a number."))
    else:
        lines.append(_("Type your answer."))
    if not question.get("required", True):
        rows.append([_button(_("Skip"), ApplyStep.SKIP, vacancy.pk, q=index)])
    rows.append([cancel_button(vacancy.pk)])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def answered(vacancy: Vacancy, index: int, row: dict) -> str:
    """The question's message once it's answered: the question and the answer, no buttons."""
    total = len(vacancy.questions)
    header = _("Question %(number)d of %(count)d") % {"number": index + 1, "count": total}
    return f"{header}\n<b>{html.quote(row['text'])}</b>\n{html.quote(questions.shown(row))}"


def use_buttons() -> str:
    return _("Please answer with the buttons above.")


def bad_number() -> str:
    return _("Please answer with a number, for example: 3.")


def bad_text() -> str:
    return _("Please type your answer in one message, up to %(count)d characters.") % {
        "count": questions.ANSWER_MAX
    }


def ask_contact() -> BotMessage:
    text = "\n".join(
        [
            _("Share your phone number with the button below, so the company can call you."),
            _("To stop, send /cancel."),
        ]
    )
    button = KeyboardButton(text=_("Share my phone number"), request_contact=True)
    markup = ReplyKeyboardMarkup(keyboard=[[button]], resize_keyboard=True, one_time_keyboard=True)
    return text, markup


def contact_needed() -> BotMessage:
    text, markup = ask_contact()
    return _("Please tap the button below to share your phone number.") + "\n" + text, markup


def foreign_contact() -> BotMessage:
    _text, markup = ask_contact()
    return _("Please share your own phone number with the button below."), markup


def phone_saved() -> BotMessage:
    return _("Thank you, your phone number is saved."), ReplyKeyboardRemove()


def ask_document(vacancy: Vacancy) -> BotMessage:
    text = "\n".join(
        [
            _("Send a photo of your diploma or specialist certificate."),
            _("No photo at hand? Tap Skip, and bring the document to the interview."),
        ]
    )
    rows = [[_button(_("Skip"), ApplyStep.SKIP, vacancy.pk, q=len(vacancy.questions))]]
    rows.append([cancel_button(vacancy.pk)])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def photo_needed() -> str:
    return _("Please send the document as a photo, or tap Skip.")


def summary(vacancy: Vacancy, data: dict) -> BotMessage:
    lines = [
        _("<b>Check your application</b>"),
        _("Vacancy: %(title)s") % {"title": html.quote(vacancy.title)},
        _("Name: %(name)s") % {"name": html.quote(data.get("name", ""))},
        _("Phone: %(phone)s") % {"phone": html.quote(data.get("phone", ""))},
    ]
    for number, row in enumerate(data.get("answers") or [], start=1):
        lines += ["", f"{number}. {html.quote(row['text'])}", html.quote(questions.shown(row))]
    if vacancy.asks_document:
        lines.append("")
        lines.append(
            _("Document photo: attached") if data.get("document") else _("Document photo: not sent")
        )
    rows = [
        [_button(_("Send application"), ApplyStep.SEND, vacancy.pk)],
        [cancel_button(vacancy.pk)],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def applied(vacancy: Vacancy) -> str:
    return "\n".join(
        [
            _("Thank you! Your application is sent."),
            _("Company: %(company)s") % {"company": html.quote(vacancy.company.name)},
            _("Vacancy: %(title)s") % {"title": html.quote(vacancy.title)},
            "",
            _("We'll write to you here as soon as there is news."),
        ]
    )


def cancelled() -> str:
    return _("Application cancelled. To apply again, open the vacancy link.")


def stale_button() -> str:
    return _("This button is no longer active.")


# Where an application stands, and what the applicant hears later ---------------------------


def stage_for_applicant(stage: str) -> str:
    return {
        Applicant.Stage.NEW: _("received, waiting to be reviewed"),
        Applicant.Stage.SCREENING: _("being reviewed"),
        Applicant.Stage.INTERVIEW: _("invited to an interview"),
        Applicant.Stage.OFFER: _("an offer is being prepared"),
        Applicant.Stage.HIRED: _("hired"),
        Applicant.Stage.REJECTED: _("not selected this time"),
    }.get(stage, "")


def status(applicant: Applicant) -> str:
    """What someone who already applied sees when they open the link again."""
    sent = timezone.localtime(applicant.created_at, ZoneInfo(applicant.company.timezone)).date()
    return "\n".join(
        [
            _("You have already applied for this vacancy."),
            _("Vacancy: %(title)s") % {"title": html.quote(applicant.vacancy.title)},
            _("Sent: %(date)s") % {"date": day(sent)},
            _("Status: %(status)s") % {"status": stage_for_applicant(applicant.stage)},
        ]
    )


def _about(applicant: Applicant) -> list[str]:
    vacancy = applicant.vacancy
    lines = [_("Vacancy: %(title)s") % {"title": html.quote(vacancy.title)}]
    if vacancy.branch_id:
        lines.append(_("Branch: %(branch)s") % {"branch": html.quote(vacancy.branch.name)})
    return lines


def _with_message(lines: list[str], message: str) -> str:
    if message:
        lines += ["", html.quote(message)]
    return "\n".join(lines)


def invited(applicant: Applicant, message: str) -> str:
    company = html.quote(applicant.company.name)
    lines = [_("<b>%(company)s</b> invites you to an interview.") % {"company": company}]
    lines += _about(applicant)
    if not message:
        lines += ["", _("They will call you to agree on the time.")]
    return _with_message(lines, message)


def offered(applicant: Applicant, message: str) -> str:
    company = html.quote(applicant.company.name)
    lines = [_("<b>%(company)s</b> would like to offer you the job.") % {"company": company}]
    lines += _about(applicant)
    return _with_message(lines, message)


def turned_down(applicant: Applicant, message: str) -> str:
    company = html.quote(applicant.company.name)
    lines = [_("Thank you for applying to <b>%(company)s</b>.") % {"company": company}]
    lines += _about(applicant)
    lines += ["", _("This time the company chose another candidate. We wish you success.")]
    return _with_message(lines, message)


def hired(applicant: Applicant, message: str) -> str:
    company = html.quote(applicant.company.name)
    lines = [_("Congratulations! <b>%(company)s</b> is hiring you.") % {"company": company}]
    lines += _about(applicant)
    return _with_message(lines, message)


def from_company(applicant: Applicant, message: str) -> str:
    company = html.quote(applicant.company.name)
    lines = [_("A message from <b>%(company)s</b> about your application.") % {"company": company}]
    lines += _about(applicant)
    return _with_message(lines, message)


# To the hiring team ------------------------------------------------------------------------


def new_applicant_title(applicant: Applicant) -> str:
    return _("New applicant: %(name)s") % {"name": applicant.name}


def new_applicant_body(applicant: Applicant) -> str:
    vacancy = applicant.vacancy
    lines = [_("Vacancy: %(title)s") % {"title": vacancy.title}]
    if vacancy.branch_id:
        lines.append(_("Branch: %(branch)s") % {"branch": vacancy.branch.name})
    if applicant.phone:
        lines.append(_("Phone: %(phone)s") % {"phone": applicant.phone})
    if applicant.source == Applicant.Source.QR:
        lines.append(_("Came through the QR code."))
    return "\n".join(lines)
