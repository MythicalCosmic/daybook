"""The company calendar in the employee bot: /calendar, answering an invitation, event links."""

from datetime import timedelta

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.agenda.callbacks import EvAction, EvCallback
from apps.agenda.models import EventAttendee
from apps.agenda.tests.factories import AttendeeFactory, EventFactory
from apps.inbox.callbacks import InboxAction
from apps.inbox.models import Notification
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)

make_event = sync_to_async(EventFactory)
invite = sync_to_async(AttendeeFactory)


def press(action: EvAction, **fields) -> str:
    return EvCallback(action=action, **fields).pack()


def sent(bot) -> list[SendMessage]:
    return [r for r in bot.requests if isinstance(r, SendMessage)]


def answers(bot) -> list[AnswerCallbackQuery]:
    return [r for r in bot.requests if isinstance(r, AnswerCallbackQuery)]


async def test_calendar_shows_my_next_seven_days(dp, bot, company, member):
    worker = await member.aregistered(company)
    soon = timezone.now() + timedelta(days=2)
    training = await make_event(company=company, title="Kassa trening", start=soon)
    await invite(event=training, membership=worker)
    await make_event(company=company, title="Jamoa kechasi", start=soon + timedelta(hours=3))
    await make_event(company=company, title="Far away", start=timezone.now() + timedelta(days=20))

    await dp.feed_update(
        bot, updates.message(updates.tg_user(worker.user.telegram_id), "/calendar")
    )

    text = sent(bot)[-1].text
    assert "Your next seven days" in text
    assert "" in text and "Kassa trening" in text  # invited, not answered yet
    assert "Jamoa kechasi" in text and "Far away" not in text


async def test_an_empty_week(dp, bot, company, member):
    worker = await member.aregistered(company)

    await dp.feed_update(
        bot, updates.message(updates.tg_user(worker.user.telegram_id), "/calendar")
    )

    assert "Nothing on the calendar" in sent(bot)[-1].text


async def test_answer_from_an_event_card(dp, bot, company, member):
    worker = await member.aregistered(company)
    event = await make_event(company=company, title="Inventarizatsiya")
    await invite(event=event, membership=worker)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, f"/start ev_{event.pk}"))
    card = sent(bot)[-1]
    assert "Inventarizatsiya" in card.text
    assert [b.text for b in card.reply_markup.inline_keyboard[0]] == [
        "I'll come",
        "Can't come",
    ]

    await dp.feed_update(bot, updates.callback(tg, press(EvAction.DECLINE, event_id=event.pk)))

    answer = await EventAttendee.objects.aget(event=event, membership=worker)
    assert answer.response == "declined"
    edited = [r for r in bot.requests if isinstance(r, EditMessageText)][-1]
    assert "You said you can't come" in edited.text


async def test_not_invited_people_cant_answer(dp, bot, company, member):
    worker = await member.aregistered(company)
    event = await make_event(company=company)

    await dp.feed_update(
        bot,
        updates.callback(
            updates.tg_user(worker.user.telegram_id), press(EvAction.GOING, event_id=event.pk)
        ),
    )

    assert answers(bot)[-1].show_alert is True
    assert "not invited" in answers(bot)[-1].text


async def test_private_events_dont_open_from_links(dp, bot, company, member):
    worker = await member.aregistered(company)
    event = await make_event(company=company, visibility="attendees")

    await dp.feed_update(
        bot, updates.message(updates.tg_user(worker.user.telegram_id), f"/start ev_{event.pk}")
    )

    assert "isn't on the calendar" in sent(bot)[-1].text


async def test_the_invitation_buttons_answer_through_the_inbox(dp, bot, company, member):
    from apps.agenda import services

    owner = await member.aregistered(company, "Owner")
    worker = await member.aregistered(company)
    event = await sync_to_async(services.create_event)(
        company,
        by=owner,
        title="Planning",
        start=timezone.now() + timedelta(days=1),
        attendee_ids=[worker.pk],
    )
    note = await Notification.objects.aget(kind="agenda.event_invite", recipient=worker)

    await dp.feed_update(
        bot,
        updates.callback(
            updates.tg_user(worker.user.telegram_id),
            InboxAction(notification_id=note.pk, key="going").pack(),
        ),
    )

    answer = await EventAttendee.objects.aget(event=event, membership=worker)
    assert answer.response == "going"
