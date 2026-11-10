"""Applying for a vacancy in the employee bot (Package G, v11): `/start job_<code>` (and the QR
code's `job_<code>-q`), the questions one by one, the phone number, a diploma photo when asked,
the summary and "Send application"; someone who applied sees where they stand; a closed or
unknown vacancy says so; "Cancel" and /cancel stop at any step."""

import io

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.types import User as TelegramUser
from asgiref.sync import sync_to_async
from PIL import Image

from apps.accounts.models import User
from apps.accounts.tests.factories import UserFactory
from apps.hr.hiring import services
from apps.hr.hiring.callbacks import ApplyButton, ApplyStep
from apps.hr.models import Applicant
from tests import mocked_bot, updates

pytestmark = pytest.mark.django_db(transaction=True)

QUESTIONS = [
    {"text": "Farmatsevtik ma’lumotingiz bormi?", "kind": "yes_no"},
    {"text": "Qaysi smena qulay?", "kind": "choice", "options": ["Kunduzgi", "Tungi"]},
    {"text": "Necha yil tajribangiz bor?", "kind": "number", "required": False},
]


def jpeg_bytes() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (90, 140, 200)).save(out, "JPEG")
    return out.getvalue()


def sent(bot) -> list:
    return [r for r in bot.requests if isinstance(r, SendMessage | EditMessageText)]


def last_text(bot) -> str:
    return sent(bot)[-1].text


def buttons(bot) -> dict[str, str]:
    """Text -> callback data of the newest inline keyboard the bot sent."""
    for request in reversed(sent(bot)):
        markup = request.reply_markup
        if markup is not None and hasattr(markup, "inline_keyboard"):
            return {b.text: b.callback_data for row in markup.inline_keyboard for b in row}
    return {}


@sync_to_async
def open_vacancy(company, member, **fields):
    company.features = ["hr"]
    company.save(update_fields=["features"])
    owner = member(company, "Owner")
    fields.setdefault("title", "Farmatsevt")
    fields.setdefault("questions", QUESTIONS)
    fields.setdefault("branch", company.branches.first())
    return services.create_vacancy(company, by=owner, publish=True, **fields)


@sync_to_async
def person(telegram_id: int, language: str = "en") -> User:
    return UserFactory(
        telegram_id=telegram_id, first_name="Aziza", last_name="Karimova", language=language
    )


def tg_person(telegram_id: int) -> TelegramUser:
    """Aziza as Telegram knows her (first and last name), writing to the bot."""
    return TelegramUser(
        id=telegram_id,
        is_bot=False,
        first_name="Aziza",
        last_name="Karimova",
        username=f"aziza{telegram_id}",
        language_code="en",
    )


@sync_to_async
def applications(vacancy) -> list[Applicant]:
    return list(Applicant.objects.filter(vacancy=vacancy).select_related("user"))


async def start(dp, bot, tg, vacancy, *, qr: bool = False) -> None:
    await dp.feed_update(bot, updates.message(tg, f"/start {vacancy.start_param(qr=qr)}"))


async def press(dp, bot, tg, label: str) -> None:
    data = buttons(bot)[label]
    await dp.feed_update(bot, updates.callback(tg, data))


async def test_applying_step_by_step(dp, bot, company, member):
    vacancy = await open_vacancy(company, member, salary_from=4_000_000, description="Tungi smena")
    user = await person(7001)
    tg = tg_person(7001)

    await start(dp, bot, tg, vacancy)
    card = last_text(bot)
    assert "<b>Farmatsevt</b>" in card and company.name in card and "Tungi smena" in card
    assert "4\xa0000\xa0000" in card and "answer 3 questions" in card
    assert {"Apply", "O‘zbekcha", "Русский"} <= set(buttons(bot))  # English is on already

    await press(dp, bot, tg, "Apply")
    assert "What is your name?" in last_text(bot)
    assert "Aziza Karimova" in buttons(bot)  # the name Telegram knows, one tap away
    await dp.feed_update(bot, updates.message(tg, "Aziza"))
    assert "first and last name" in last_text(bot)
    await dp.feed_update(bot, updates.message(tg, "Aziza  Karimova"))

    assert "Question 1 of 3" in last_text(bot) and set(buttons(bot)) >= {"Yes", "No", "Cancel"}
    await dp.feed_update(bot, updates.message(tg, "ha"))
    assert "buttons" in last_text(bot)
    await press(dp, bot, tg, "Yes")
    assert any("Question 1 of 3" in r.text and "Yes" in r.text for r in sent(bot)[-3:])
    assert "Question 2 of 3" in last_text(bot)
    await press(dp, bot, tg, "Tungi")
    assert "Question 3 of 3" in last_text(bot) and "Skip" in buttons(bot)
    await dp.feed_update(bot, updates.message(tg, "uch"))
    assert "with a number" in last_text(bot)
    await dp.feed_update(bot, updates.message(tg, "3 yil"))

    asked = sent(bot)[-1]
    assert isinstance(asked.reply_markup, ReplyKeyboardMarkup)
    assert asked.reply_markup.keyboard[0][0].request_contact
    await dp.feed_update(bot, updates.message(tg, "+998901234567"))
    assert "tap the button below" in last_text(bot)
    await dp.feed_update(bot, updates.contact(tg, "998901234567"))
    saved = [r for r in sent(bot) if isinstance(r.reply_markup, ReplyKeyboardRemove)]
    assert saved and "phone number is saved" in saved[-1].text
    summary = last_text(bot)
    assert "Check your application" in summary and "Aziza Karimova" in summary
    assert "+998901234567" in summary and "Tungi" in summary

    await press(dp, bot, tg, "Send application")
    assert "Your application is sent" in last_text(bot)
    [made] = await applications(vacancy)
    assert made.user == user and made.name == "Aziza Karimova" and made.phone == "+998901234567"
    assert made.source == "link" and made.stage == "new"
    assert [row["answer"] for row in made.answers] == ["yes", "Tungi", "3"]
    assert (await sync_to_async(User.objects.get)(pk=user.pk)).phone == "+998901234567"

    # Opening the link again shows where the application stands.
    await start(dp, bot, tg, vacancy)
    assert "already applied" in last_text(bot)
    assert "received, waiting to be reviewed" in last_text(bot)


async def test_the_qr_code_counts_apart_and_the_name_is_one_tap(dp, bot, company, member):
    vacancy = await open_vacancy(company, member, questions=[])
    await person(7002)
    tg = tg_person(7002)
    await start(dp, bot, tg, vacancy, qr=True)
    assert "give your name and share your phone number" in last_text(bot)
    await press(dp, bot, tg, "Apply")
    await press(dp, bot, tg, "Aziza Karimova")
    await dp.feed_update(bot, updates.contact(tg, "+998 90 765 43 21"))
    await press(dp, bot, tg, "Send application")
    [made] = await applications(vacancy)
    assert made.source == "qr" and made.name == "Aziza Karimova" and made.answers == []
    assert made.phone == "+998907654321"


async def test_only_their_own_phone_number(dp, bot, company, member):
    vacancy = await open_vacancy(company, member, questions=[])
    await person(7003)
    tg = tg_person(7003)
    await start(dp, bot, tg, vacancy)
    await press(dp, bot, tg, "Apply")
    await dp.feed_update(bot, updates.message(tg, "Aziza Karimova"))
    await dp.feed_update(bot, updates.contact(tg, "+998901110000", owner_id=999))
    assert "your own phone number" in last_text(bot)
    assert await applications(vacancy) == []


async def test_cancel_stops_at_any_step(dp, bot, company, member):
    vacancy = await open_vacancy(company, member)
    await person(7004)
    tg = tg_person(7004)
    await start(dp, bot, tg, vacancy)
    await press(dp, bot, tg, "Apply")
    await dp.feed_update(bot, updates.message(tg, "Aziza Karimova"))
    stale_yes = buttons(bot)["Yes"]
    await press(dp, bot, tg, "Cancel")
    assert "Application cancelled" in last_text(bot)
    await dp.feed_update(bot, updates.callback(tg, stale_yes))
    answered = [r for r in bot.requests if isinstance(r, AnswerCallbackQuery)]
    assert answered[-1].text == "This button is no longer active."

    # Typed, at the phone number step: the phone button goes too.
    await start(dp, bot, tg, vacancy)
    await press(dp, bot, tg, "Apply")
    await dp.feed_update(bot, updates.message(tg, "Aziza Karimova"))
    await press(dp, bot, tg, "No")
    await press(dp, bot, tg, "Kunduzgi")
    await press(dp, bot, tg, "Skip")
    await dp.feed_update(bot, updates.message(tg, "/cancel"))
    last = sent(bot)[-1]
    assert "Application cancelled" in last.text and isinstance(
        last.reply_markup, ReplyKeyboardRemove
    )
    assert await applications(vacancy) == []


async def test_a_button_of_an_answered_question_does_nothing(dp, bot, company, member):
    vacancy = await open_vacancy(company, member)
    await person(7005)
    tg = tg_person(7005)
    await start(dp, bot, tg, vacancy)
    await press(dp, bot, tg, "Apply")
    await dp.feed_update(bot, updates.message(tg, "Aziza Karimova"))
    yes = buttons(bot)["Yes"]
    await press(dp, bot, tg, "Yes")
    await dp.feed_update(bot, updates.callback(tg, yes))  # question 1 again
    assert "Question 2 of 3" in last_text(bot)
    other = ApplyButton(step=ApplyStep.ANSWER, v=vacancy.pk + 99, q=1, pick=0).pack()
    await dp.feed_update(bot, updates.callback(tg, other))
    assert "Question 2 of 3" in last_text(bot)


async def test_a_diploma_photo_when_the_vacancy_asks(dp, bot, company, member, monkeypatch):
    vacancy = await open_vacancy(company, member, questions=[], asks_document=True)
    await person(7006)
    tg = tg_person(7006)
    await start(dp, bot, tg, vacancy)
    assert "diploma or specialist certificate" in last_text(bot)
    await press(dp, bot, tg, "Apply")
    await dp.feed_update(bot, updates.message(tg, "Aziza Karimova"))
    await dp.feed_update(bot, updates.contact(tg, "+998901112233"))
    assert "Send a photo of your diploma" in last_text(bot) and "Skip" in buttons(bot)
    await dp.feed_update(bot, updates.message(tg, "keyin"))
    assert "as a photo" in last_text(bot)
    await dp.feed_update(bot, updates.photo(tg))  # what Telegram sent isn't a picture
    assert "picture" in last_text(bot)
    monkeypatch.setattr(mocked_bot, "FILE_CONTENT", jpeg_bytes())
    await dp.feed_update(bot, updates.photo(tg))
    assert "Document photo: attached" in last_text(bot)
    await press(dp, bot, tg, "Send application")
    [made] = await applications(vacancy)
    assert made.document.name.endswith(".jpg")


async def test_the_diploma_can_wait_for_the_interview(dp, bot, company, member):
    vacancy = await open_vacancy(company, member, questions=[], asks_document=True)
    await person(7007)
    tg = tg_person(7007)
    await start(dp, bot, tg, vacancy)
    await press(dp, bot, tg, "Apply")
    await dp.feed_update(bot, updates.message(tg, "Aziza Karimova"))
    await dp.feed_update(bot, updates.contact(tg, "+998901112244"))
    await press(dp, bot, tg, "Skip")
    assert "Document photo: not sent" in last_text(bot)
    await press(dp, bot, tg, "Send application")
    [made] = await applications(vacancy)
    assert not made.document


async def test_closed_unknown_and_member_links(dp, bot, company, member):
    vacancy = await open_vacancy(company, member)
    await person(7008)
    tg = tg_person(7008)
    await dp.feed_update(bot, updates.message(tg, "/start job_nosuchcode"))
    assert "link is invalid" in last_text(bot)

    owner = await sync_to_async(lambda: vacancy.created_by)()
    await sync_to_async(services.set_status)(vacancy, "paused", by=owner)
    await start(dp, bot, tg, vacancy)
    assert "paused" in last_text(bot)
    await sync_to_async(services.set_status)(vacancy, "closed", by=owner)
    await start(dp, bot, tg, vacancy)
    assert "closed" in last_text(bot)

    await sync_to_async(services.set_status)(vacancy, "open", by=owner)
    worker = await member.aregistered(company)
    await start(dp, bot, updates.tg_user(worker.user.telegram_id), vacancy)
    assert "already work here" in last_text(bot)


async def test_a_vacancy_closed_meanwhile_refuses_the_application(dp, bot, company, member):
    vacancy = await open_vacancy(company, member, questions=[])
    await person(7009)
    tg = tg_person(7009)
    await start(dp, bot, tg, vacancy)
    await press(dp, bot, tg, "Apply")
    await dp.feed_update(bot, updates.message(tg, "Aziza Karimova"))
    await dp.feed_update(bot, updates.contact(tg, "+998901112255"))
    owner = await sync_to_async(lambda: vacancy.created_by)()
    await sync_to_async(services.set_status)(vacancy, "closed", by=owner)
    await press(dp, bot, tg, "Send application")
    assert "closed" in last_text(bot)
    assert await applications(vacancy) == []


async def test_the_vacancy_in_another_language(dp, bot, company, member):
    vacancy = await open_vacancy(company, member)
    user = await person(7010, language="uz")
    tg = tg_person(7010)
    await start(dp, bot, tg, vacancy)
    assert "English" in buttons(bot) and "O‘zbekcha" not in buttons(bot)
    await press(dp, bot, tg, "Русский")
    edited = [r for r in bot.requests if isinstance(r, EditMessageText)]
    assert edited and "<b>Farmatsevt</b>" in edited[-1].text
    assert "Русский" not in {b.text for row in edited[-1].reply_markup.inline_keyboard for b in row}
    assert (await sync_to_async(User.objects.get)(pk=user.pk)).language == "ru"
