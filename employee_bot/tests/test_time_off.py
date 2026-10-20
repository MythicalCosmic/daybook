from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText
from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.timeoff.callbacks import TimeOffAction, TimeOffDecision
from apps.timeoff.models import TimeOff
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


def press(action: TimeOffAction, time_off: TimeOff) -> str:
    return TimeOffDecision(action=action, time_off_id=time_off.pk).pack()


def alerts(bot) -> list[str]:
    return [r.text for r in bot.requests if isinstance(r, AnswerCallbackQuery) and r.show_alert]


@sync_to_async
def asking(member) -> TimeOff:
    today = timezone.localdate(timezone=ZoneInfo("Asia/Tashkent"))
    return TimeOff.objects.create(
        company=member.company,
        membership=member,
        first_day=today + timedelta(days=1),
        last_day=today + timedelta(days=2),
    )


async def test_a_manager_approves_time_off_from_the_bot(dp, bot, company, member, sent_messages):
    worker = await member.aregistered(company, first_name="Ali")
    manager = await member.aregistered(company, "Manager", first_name="Mona")
    time_off = await asking(worker)

    await dp.feed_update(
        bot,
        updates.callback(
            updates.tg_user(manager.user.telegram_id), press(TimeOffAction.APPROVE, time_off)
        ),
    )

    await time_off.arefresh_from_db()
    assert time_off.status == TimeOff.Status.APPROVED
    [edit] = [r for r in bot.requests if isinstance(r, EditMessageText)]
    assert "Approved by" in edit.text
    assert edit.reply_markup is None
    [told] = [m for m in sent_messages if m["chat_id"] == worker.user.telegram_id]
    assert "approved" in told["text"]


async def test_others_cannot_decide(dp, bot, company, member):
    worker = await member.aregistered(company)
    colleague = await member.aregistered(company)
    time_off = await asking(worker)

    await dp.feed_update(
        bot,
        updates.callback(
            updates.tg_user(colleague.user.telegram_id), press(TimeOffAction.APPROVE, time_off)
        ),
    )

    assert alerts(bot)
    await time_off.arefresh_from_db()
    assert time_off.status == TimeOff.Status.PENDING


async def test_a_second_decision_shows_the_first(dp, bot, company, member):
    worker = await member.aregistered(company)
    first = await member.aregistered(company, "Manager")
    second = await member.aregistered(company, "Manager")
    time_off = await asking(worker)

    await dp.feed_update(
        bot,
        updates.callback(
            updates.tg_user(first.user.telegram_id), press(TimeOffAction.REJECT, time_off)
        ),
    )
    await dp.feed_update(
        bot,
        updates.callback(
            updates.tg_user(second.user.telegram_id), press(TimeOffAction.APPROVE, time_off)
        ),
    )

    assert any("already rejected" in alert for alert in alerts(bot))
    await time_off.arefresh_from_db()
    assert time_off.status == TimeOff.Status.REJECTED
    assert "Rejected by" in [r for r in bot.requests if isinstance(r, EditMessageText)][-1].text
