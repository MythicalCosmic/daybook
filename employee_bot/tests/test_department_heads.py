"""Department heads in the employee bot: "New task" asks whom it's for and offers their people,
and "To check" is on their menu."""

import pytest
from aiogram.methods import SendMessage
from aiogram.types import ReplyKeyboardMarkup
from asgiref.sync import sync_to_async

from apps.members import departments
from apps.members.bot_messages import main_menu
from apps.members.models import Membership
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


def sent(bot) -> list[SendMessage]:
    return [r for r in bot.requests if isinstance(r, SendMessage)]


@pytest.fixture
def sales(company, member):
    owner = member.registered(company, "Owner")
    bekzod = member.registered(company, first_name="Bekzod")
    alisher = member.registered(company, first_name="Alisher")
    otabek = member.registered(company, first_name="Otabek")
    department = departments.create_department(company, by=owner, name="Savdo", head=bekzod)
    departments.place(department, by=owner, people=[bekzod, alisher])
    return {"bekzod": bekzod, "alisher": alisher, "otabek": otabek}


async def test_a_heads_new_task_asks_whom_its_for_and_offers_their_people(dp, bot, sales):
    head = updates.tg_user(sales["bekzod"].user.telegram_id)

    await dp.feed_update(bot, updates.message(head, "New task"))
    await dp.feed_update(bot, updates.message(head, "Vitrinani tozalash"))

    question = sent(bot)[-1]
    assert "Who is it for?" in question.text
    names = [button.text for row in question.reply_markup.inline_keyboard for button in row]
    assert any("Alisher" in name for name in names)
    assert not any("Otabek" in name for name in names)  # not one of theirs


async def test_someone_heading_nothing_just_adds_their_own_task(dp, bot, sales):
    worker = updates.tg_user(sales["alisher"].user.telegram_id)

    await dp.feed_update(bot, updates.message(worker, "New task"))
    await dp.feed_update(bot, updates.message(worker, "Kassani sanash"))

    assert "Who is it for?" not in sent(bot)[-1].text


async def test_heads_get_to_check_on_their_menu(sales):
    def labels(person: Membership) -> list[str]:
        fresh = Membership.objects.select_related("company", "role", "user").get(pk=person.pk)
        menu: ReplyKeyboardMarkup = main_menu(fresh)
        return [button.text for row in menu.keyboard for button in row]

    assert "To check" in await sync_to_async(labels)(sales["bekzod"])
    assert "To check" not in await sync_to_async(labels)(sales["alisher"])


async def test_heads_get_my_team_on_their_menu_and_it_answers(dp, bot, sales):
    def labels(person: Membership) -> list[str]:
        fresh = Membership.objects.select_related("company", "role", "user").get(pk=person.pk)
        return [button.text for row in main_menu(fresh).keyboard for button in row]

    assert "My team" in await sync_to_async(labels)(sales["bekzod"])
    assert "My team" not in await sync_to_async(labels)(sales["alisher"])

    head = updates.tg_user(sales["bekzod"].user.telegram_id)
    await dp.feed_update(bot, updates.message(head, "My team"))

    assert "My team" in sent(bot)[-1].text
    assert "Alisher" in sent(bot)[-1].text
