"""Ko‘z alerts in the employee bot: "I'll go" under a queue alert, pressed by someone on shift."""

import pytest
from aiogram.methods import AnswerCallbackQuery
from asgiref.sync import sync_to_async

from apps.vision.callbacks import KozButton
from apps.vision.models import Alert
from apps.vision.tests import factories
from bot.handlers.features import vision
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


def answers(bot) -> list[AnswerCallbackQuery]:
    return [request for request in bot.requests if isinstance(request, AnswerCallbackQuery)]


@sync_to_async
def alert_for(company, *people) -> Alert:
    company.features = [*company.features, "vision"]
    company.save(update_fields=["features"])
    branch = company.branches.order_by("pk").first()
    alert = factories.make_alert(factories.make_camera(factories.make_box(branch)))
    for person in people:
        factories.copy_to(alert, person)
    return alert


def press(alert: Alert) -> str:
    return KozButton(alert_id=alert.pk).pack()


def test_the_feature_router_handles_the_button():
    assert vision.router.name == "feature_vision"
    assert vision.router.callback_query.handlers


async def test_the_one_who_goes_is_thanked(dp, bot, company, member):
    worker = await member.aregistered(company, "Pharmacist", first_name="Alimardon")
    alert = await alert_for(company, worker)

    await dp.feed_update(
        bot, updates.callback(updates.tg_user(worker.user.telegram_id), press(alert))
    )

    [answer] = answers(bot)
    assert (answer.text, answer.show_alert) == ("Thank you: everyone sees you're going.", False)
    await alert.arefresh_from_db()
    assert alert.acknowledged_by_id == worker.pk


async def test_the_second_one_is_told_who_goes(dp, bot, company, member):
    first = await member.aregistered(company, "Pharmacist", first_name="Alimardon")
    second = await member.aregistered(company, "Pharmacist", first_name="Gulnora")
    alert = await alert_for(company, first, second)

    for person in (first, second):
        await dp.feed_update(
            bot, updates.callback(updates.tg_user(person.user.telegram_id), press(alert))
        )

    late = answers(bot)[-1]
    assert (late.text, late.show_alert) == ("Alimardon is already going.", True)


async def test_someone_without_a_copy_cant_press_it(dp, bot, company, member):
    worker = await member.aregistered(company, "Pharmacist")
    other = await member.aregistered(company, "Pharmacist")
    alert = await alert_for(company, worker)

    await dp.feed_update(
        bot, updates.callback(updates.tg_user(other.user.telegram_id), press(alert))
    )

    [answer] = answers(bot)
    assert (answer.text, answer.show_alert) == ("You don't have access to this.", True)
    await alert.arefresh_from_db()
    assert alert.acknowledged_by_id is None
