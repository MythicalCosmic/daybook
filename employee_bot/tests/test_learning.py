"""The question of the day in the employee bot (docs/PLAN-LEARNING.md §9.2): one tap answers,
several right answers toggle then "Answer", the message becomes the result, and a forged, stale
or repeated tap changes nothing."""

from datetime import timedelta

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText
from asgiref.sync import sync_to_async

from apps.companies.models import Feature
from apps.learning import daily as daily_service
from apps.learning.callbacks import FALSE, DailyAction, DailyCallback
from apps.learning.models import AnswerLog, DailyQuestion
from apps.learning.tests.q2.fixtures import question
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


def press(daily, action=DailyAction.PICK, option="") -> str:
    return DailyCallback(action=action, daily_id=daily.pk, option=option).pack()


def edits(bot) -> list[EditMessageText]:
    return [r for r in bot.requests if isinstance(r, EditMessageText)]


def answers(bot) -> list[AnswerCallbackQuery]:
    return [r for r in bot.requests if isinstance(r, AnswerCallbackQuery)]


@sync_to_async
def learning_on(company):
    company.features = [*company.features, Feature.LEARNING]
    company.save(update_fields=["features"])


@sync_to_async
def make_daily(company, member, kind="single", *, days_ago=0, order=None):
    return DailyQuestion.objects.create(
        company=company,
        membership=member,
        day=daily_service.today(company) - timedelta(days=days_ago),
        question=question(company, kind, explanation="Muzlatgichda saqlanadi."),
        order=order if order is not None else ["c", "a", "b"],
    )


@sync_to_async
def fresh(daily):
    daily.refresh_from_db()
    return daily


@sync_to_async
def logs():
    return AnswerLog.objects.count()


async def test_one_tap_answers_and_the_message_becomes_the_result(dp, bot, company, member):
    await learning_on(company)
    worker = await member.aregistered(company)
    daily = await make_daily(company, worker)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(daily, option="a")))

    daily = await fresh(daily)
    assert (daily.correct, daily.answer) == (True, {"option": "a"})
    assert await logs() == 1
    edited = edits(bot)[-1]
    assert "Right!" in edited.text and "Muzlatgichda saqlanadi." in edited.text
    assert answers(bot)[-1].text == "Right!"


async def test_true_or_false(dp, bot, company, member):
    await learning_on(company)
    worker = await member.aregistered(company)
    daily = await make_daily(company, worker, "true_false", order=[])
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(daily, option=FALSE)))

    assert (await fresh(daily)).correct is True
    assert "Your answer: False" in edits(bot)[-1].text


async def test_several_right_answers_toggle_then_answer(dp, bot, company, member):
    await learning_on(company)
    worker = await member.aregistered(company)
    daily = await make_daily(company, worker, "multi", order=["c", "b", "a"])
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(daily, DailyAction.SEND)))
    assert answers(bot)[-1].text == "Choose an answer first."

    await dp.feed_update(bot, updates.callback(tg, press(daily, option="a")))
    await dp.feed_update(bot, updates.callback(tg, press(daily, option="c")))
    assert "Chosen: A, C" in edits(bot)[-1].text
    assert (await fresh(daily)).answered_at is None

    await dp.feed_update(bot, updates.callback(tg, press(daily, DailyAction.SEND)))
    daily = await fresh(daily)
    assert (daily.correct, daily.answer) == (True, {"options": ["c", "a"]})
    assert "Right!" in edits(bot)[-1].text


async def test_a_forged_tap_on_someone_elses_question_does_nothing(dp, bot, company, member):
    await learning_on(company)
    worker = await member.aregistered(company)
    colleague = await member.aregistered(company, user__phone="+998901112233")
    theirs = await make_daily(company, colleague)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(theirs, option="a")))

    assert (await fresh(theirs)).answered_at is None
    assert await logs() == 0
    assert edits(bot) == []
    assert answers(bot)[-1].text == "This question isn't yours."


async def test_yesterdays_question_cant_be_answered(dp, bot, company, member):
    await learning_on(company)
    worker = await member.aregistered(company)
    old = await make_daily(company, worker, days_ago=1)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(old, option="a")))

    assert (await fresh(old)).answered_at is None
    assert answers(bot)[-1].text == "This was the question of another day."


async def test_a_second_tap_shows_the_result_and_counts_nothing(dp, bot, company, member):
    await learning_on(company)
    worker = await member.aregistered(company)
    daily = await make_daily(company, worker)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(daily, option="b")))
    await dp.feed_update(bot, updates.callback(tg, press(daily, option="a")))

    daily = await fresh(daily)
    assert (daily.correct, daily.answer) == (False, {"option": "b"})
    assert await logs() == 1
    assert answers(bot)[-1].text == "You've answered it already."


async def test_a_question_for_the_app_says_so(dp, bot, company, member):
    await learning_on(company)
    worker = await member.aregistered(company)
    daily = await make_daily(company, worker, "order", order=["b", "a", "c"])
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(daily, option="a")))

    assert (await fresh(daily)).answered_at is None
    assert answers(bot)[-1].text == "This one is answered in the app."


async def test_nothing_while_learning_is_off(dp, bot, company, member):
    worker = await member.aregistered(company)
    daily = await make_daily(company, worker)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(daily, option="a")))

    assert (await fresh(daily)).answered_at is None
    assert answers(bot)[-1].text == "Training isn't switched on for this company."
