"""Recognition in the employee bot: /kudos opens the mini app's "Say thanks" sheet, and the
receiver's plain message with "Say thanks back" (PLAN-LEARNING §9.2)."""

import pytest
from aiogram.methods import SendMessage
from asgiref.sync import sync_to_async
from django.utils import translation

from apps.notifications.emoji import has_emoji
from apps.recognition import bot_messages, conf, services
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)

APP = "https://app.example.uz/app/"


def sent(bot) -> list[SendMessage]:
    return [r for r in bot.requests if isinstance(r, SendMessage)]


@sync_to_async
def switch_on(company, **settings):
    company.features = ["recognition"]
    company.save(update_fields=["features"])
    row = conf.get_settings(company)
    for field, value in settings.items():
        setattr(row, field, value)
    row.save()


async def test_kudos_opens_the_sheet_and_says_how_many_are_left(dp, bot, company, member, settings):
    settings.EMPLOYEE_MINIAPP_URL = APP
    await switch_on(company)
    worker = await member.aregistered(company)

    await dp.feed_update(bot, updates.message(updates.tg_user(worker.user.telegram_id), "/kudos"))

    reply = sent(bot)[-1]
    assert "Thank a colleague for their help" in reply.text
    assert "You can thank 3 more colleagues today." in reply.text
    [[button]] = reply.reply_markup.inline_keyboard
    assert button.text == "Say thanks"
    assert button.web_app.url == f"{APP}?screen=thank"
    assert not has_emoji(reply.text)


async def test_kudos_after_today_s_thanks(dp, bot, company, member):
    await switch_on(company, kudos_per_day=1)
    worker = await member.aregistered(company)
    colleague = await member.aregistered(company, user__phone="+998901112233")
    await sync_to_async(services.send_kudos)(worker, to=colleague)

    await dp.feed_update(bot, updates.message(updates.tg_user(worker.user.telegram_id), "/kudos"))

    reply = sent(bot)[-1]
    assert "You've used today's thanks. More tomorrow." in reply.text
    # Without the app's https address there is no Mini App button: the menu button opens it.
    assert reply.reply_markup is None
    assert "menu button" in reply.text


async def test_kudos_while_switched_off(dp, bot, company, member):
    worker = await member.aregistered(company)

    await dp.feed_update(bot, updates.message(updates.tg_user(worker.user.telegram_id), "/kudos"))

    assert sent(bot)[-1].text == "Thanks between colleagues aren't switched on in your company."


async def test_the_receiver_s_message(company, member, settings):
    settings.EMPLOYEE_MINIAPP_URL = APP
    await switch_on(company)
    giver = await member.aregistered(company, first_name="Madina")
    receiver = await member.aregistered(company, user__phone="+998901112244")
    kudos = await sync_to_async(services.send_kudos)(
        giver, to=receiver, badge="careful", message="Sovutgich <jurnali>"
    )

    def render():
        with translation.override("en"):
            return bot_messages.kudos(kudos, points=5)

    text, markup = await sync_to_async(render)()
    assert text.splitlines() == [
        "<b>Madina thanked you: careful work.</b>",
        "«Sovutgich &lt;jurnali&gt;»",
        "+5 points",
    ]
    [[button]] = markup.inline_keyboard
    assert button.text == "Say thanks back"
    assert button.web_app.url == f"{APP}?screen=thank%3A{giver.pk}"
    assert not has_emoji(text)

    def render_uz():
        with translation.override("uz"):
            return bot_messages.thanked_line(kudos)

    # Uzbek and Russian come from the .po files the lead fills; the line is built either way.
    assert "Madina" in await sync_to_async(render_uz)()
