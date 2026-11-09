"""The buttons of attendance's shift nudges, which in this edition arrive through this bot."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from aiogram.methods import EditMessageReplyMarkup
from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.attendance import services
from apps.attendance.callbacks import AttendanceAction, AttendanceButton
from apps.attendance.models import AttendanceRecord
from apps.attendance.tests.factories import shift_at
from davomat_bot.tests import updates

pytestmark = pytest.mark.django_db(transaction=True)

TZ = ZoneInfo("Asia/Tashkent")


def press(action: AttendanceAction, ref: int = 0) -> str:
    return AttendanceButton(action=action, ref=ref).pack()


@pytest.fixture
def ali(org, linked):
    org.timezone = "Asia/Tashkent"
    org.save(update_fields=["timezone"])
    services.update_settings(org, by=None, require_location=False)
    return linked("Employee", 8401, first_name="Ali")


async def test_im_off_today_tells_the_managers(dp, bot, ali, linked):
    today = timezone.localdate(timezone.now(), TZ)
    shift = await sync_to_async(shift_at)(ali, today)
    other = await sync_to_async(linked)("Employee", 8402)
    theirs = await sync_to_async(shift_at)(other, today)

    await dp.feed_update(
        bot, updates.callback(updates.tg_user(8401), press(AttendanceAction.OFF_TODAY, shift.pk))
    )
    await dp.feed_update(
        bot, updates.callback(updates.tg_user(8401), press(AttendanceAction.OFF_TODAY, theirs.pk))
    )

    mine, not_mine = bot.answers()
    assert mine.text == "Got it. Your manager will see that you're off today."
    assert not_mine.text == "This shift isn't yours any more."
    assert any(isinstance(r, EditMessageReplyMarkup) for r in bot.requests)


async def test_im_done_now_checks_out_once(dp, bot, ali):
    now = timezone.now()
    day = timezone.localdate(now, TZ)
    start = datetime.combine(day, time(0, 0), tzinfo=TZ)
    await sync_to_async(services.check_in)(
        ali, now=max(start, now - timedelta(hours=2)), quiet=True
    )
    record = await AttendanceRecord.objects.aget(membership=ali)

    await dp.feed_update(
        bot, updates.callback(updates.tg_user(8401), press(AttendanceAction.DONE_NOW, record.pk))
    )
    await dp.feed_update(
        bot, updates.callback(updates.tg_user(8401), press(AttendanceAction.DONE_NOW, record.pk))
    )

    await record.arefresh_from_db()
    assert record.status == AttendanceRecord.Status.CLOSED
    assert record.out_source == AttendanceRecord.Source.BOT
    [edit] = bot.edits()
    assert edit.text.startswith("Checked out at ")
    again = bot.answers()[-1]
    assert (again.text, again.show_alert) == ("You're already checked out.", True)


async def test_still_here_and_the_terminal_buttons(dp, bot, ali):
    await dp.feed_update(
        bot, updates.callback(updates.tg_user(8401), press(AttendanceAction.STILL_HERE, 1))
    )
    await dp.feed_update(
        bot, updates.callback(updates.tg_user(8401), press(AttendanceAction.CHECK_IN))
    )

    still, check_in = bot.answers()
    assert still.text == "Okay! Don't forget to check out when you leave."
    assert check_in.show_alert is True
    assert "at the terminal" in check_in.text


async def test_someone_not_linked_is_told_how(dp, bot, org):
    await dp.feed_update(
        bot, updates.callback(updates.tg_user(8499), press(AttendanceAction.OFF_TODAY, 1))
    )

    [answer] = bot.answers()
    assert answer.show_alert is True and "isn't linked to anyone yet" in answer.text
