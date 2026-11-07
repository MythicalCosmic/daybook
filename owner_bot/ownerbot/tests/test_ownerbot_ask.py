"""Questions typed to the owner bot: Ask AI answers them in place of "Thinking…"."""

from datetime import timedelta

import pytest
from aiogram.methods import EditMessageText
from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.ai.models import AIConversation, AITurn
from apps.ai.tests.conftest import switch_ai_on
from apps.companies.tests.factories import CompanyFactory
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory
from ownerbot import answers
from ownerbot.callbacks import AskPick
from ownerbot.handlers.ask import answers_sent
from ownerbot.tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def owner(company, member):
    switch_ai_on(company)
    person = member(
        company, "Owner", user__telegram_id=7701, first_name="Dilnoza", last_name="Karimova"
    )
    worker = member.registered(company, first_name="Alisher", last_name="Valiyev")
    TaskFactory(
        company=company,
        kind=Task.Kind.ASSIGNED,
        created_by=person,
        assignee=worker,
        due_at=timezone.now() - timedelta(hours=5),
        title="Muzlatgich haroratini tekshirish",
    )
    return person


def edits(bot) -> list[str]:
    return [request.text for request in bot.requests if isinstance(request, EditMessageText)]


async def test_a_typed_question_is_answered_in_place(dp, bot, owner, settings):
    settings.AI_FAKE = True
    tg = updates.tg_user(7701)

    await dp.feed_update(bot, updates.message(tg, "Nechta vazifa kechikmoqda?"))
    await answers_sent()

    [thinking] = bot.sent()
    assert thinking.text == "Thinking…"
    [answer] = edits(bot)
    # The fake answer names the late task; its record link became the plain title.
    assert "<b>1 task is late right now:</b>" in answer
    assert "• Muzlatgich haroratini tekshirish" in answer and "(task:" not in answer
    turn = await sync_to_async(AITurn.objects.get)()
    assert (turn.page, turn.status, turn.membership_id) == ("telegram", "done", owner.pk)

    # A follow-up continues the same conversation.
    await dp.feed_update(bot, updates.message(tg, "Kecha-chi?"))
    await answers_sent()
    assert await sync_to_async(AIConversation.objects.count)() == 1
    assert await sync_to_async(AITurn.objects.count)() == 2


async def test_an_old_conversation_is_not_continued(dp, bot, owner, settings):
    settings.AI_FAKE = True
    tg = updates.tg_user(7701)
    await dp.feed_update(bot, updates.message(tg, "Nechta vazifa kechikmoqda?"))
    await answers_sent()
    await sync_to_async(AIConversation.objects.update)(
        last_activity_at=timezone.now() - timedelta(hours=3)
    )

    await dp.feed_update(bot, updates.message(tg, "Bugun-chi?"))
    await answers_sent()

    assert await sync_to_async(AIConversation.objects.count)() == 2


async def test_without_ask_ai_text_gets_the_home_message(dp, bot, company, member):
    await member.acreate(company, "Owner", user__telegram_id=7702)

    await dp.feed_update(bot, updates.message(updates.tg_user(7702), "Salom"))

    [home] = bot.sent()
    assert home.text.startswith("Hello") and "Your companies:" in home.text
    assert not await sync_to_async(AITurn.objects.exists)()


async def test_commands_are_never_questions(dp, bot, owner, settings):
    settings.AI_FAKE = True

    await dp.feed_update(bot, updates.message(updates.tg_user(7701), "/unknown"))

    assert not await sync_to_async(AITurn.objects.exists)()


async def test_several_companies_ask_which_first(dp, bot, owner, member, settings):
    settings.AI_FAKE = True
    other = await sync_to_async(CompanyFactory)(name="Demo Distribyutor")
    await sync_to_async(switch_ai_on)(other)
    await member.acreate(other, "Owner", user=owner.user)
    tg = updates.tg_user(7701)

    await dp.feed_update(bot, updates.message(tg, "Nechta vazifa kechikmoqda?"))

    [picker] = bot.sent()
    assert picker.text == "Which company is the question about?"
    assert not await sync_to_async(AITurn.objects.exists)()

    await dp.feed_update(bot, updates.callback(tg, AskPick(company=owner.company_id).pack()))
    await answers_sent()

    turn = await sync_to_async(AITurn.objects.get)()
    assert turn.company_id == owner.company_id
    assert "Thinking…" in [message.text for message in bot.sent()]
    assert edits(bot)


def test_markdown_becomes_telegram_html():
    markdown = "\n".join(
        [
            "## Kechikkanlar <3 & co",
            "**2 ta vazifa** kechikdi, *bugun*:",
            "- [Kirim](task:12): [Alisher](member:7)",
            "* `SRT-2026-1`",
            "",
            "",
            "",
            "| Filial | Vazifa |",
            "|---|---|",
            "| Chilonzor | 2 |",
        ]
    )
    assert answers.to_telegram(markdown) == "\n".join(
        [
            "<b>Kechikkanlar &lt;3 &amp; co</b>",
            "<b>2 ta vazifa</b> kechikdi, <i>bugun</i>:",
            "• Kirim: Alisher",
            "• <code>SRT-2026-1</code>",
            "",
            "Filial · Vazifa",
            "Chilonzor · 2",
        ]
    )
    # Whatever the answer holds, it can't open a tag of its own.
    assert answers.to_telegram('<a href="x">hi</a>') == '&lt;a href="x"&gt;hi&lt;/a&gt;'
