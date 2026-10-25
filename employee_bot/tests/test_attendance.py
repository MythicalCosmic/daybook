"""The employee bot's attendance: `/checkin` and the menu button with a location share, the
selfie step, check-out, and the nudge buttons."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from itertools import count
from zoneinfo import ZoneInfo

import pytest
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageReplyMarkup,
    EditMessageText,
    SendMessage,
)
from aiogram.types import Chat, Location, Message, Update
from asgiref.sync import sync_to_async

from apps.attendance import services
from apps.attendance.callbacks import AttendanceAction, AttendanceButton
from apps.attendance.models import AttendanceRecord, JobMark, WorkShift
from apps.inbox.models import Notification
from apps.tasks.tests.factories import jpeg_bytes
from tests import mocked_bot, updates

pytestmark = pytest.mark.django_db(transaction=True)

TZ = ZoneInfo("Asia/Tashkent")
_ids = count(10_000)
CHILONZOR = (41.28568, 69.20343)


def sent(bot) -> list[SendMessage]:
    return [r for r in bot.requests if isinstance(r, SendMessage)]


def location(user, lat=CHILONZOR[0], lng=CHILONZOR[1], accuracy=12.0) -> Update:
    return Update(
        update_id=next(_ids),
        message=Message(
            message_id=next(_ids),
            date=datetime.now(),
            chat=Chat(id=user.id, type="private"),
            from_user=user,
            location=Location(latitude=lat, longitude=lng, horizontal_accuracy=accuracy),
        ),
    )


def press(action: AttendanceAction, ref: int = 0) -> str:
    return AttendanceButton(action=action, ref=ref).pack()


@sync_to_async
def shop_with_shift(company, member, *, starts=time(9, 0), ends=time(18, 0), require_photo=False):
    """A registered worker with a published shift around now, at a branch with coordinates."""
    company.features = ["attendance"]
    company.save()
    branch = company.branches.first()
    branch.latitude, branch.longitude = Decimal("41.285680"), Decimal("69.203430")
    branch.save()
    worker = member.registered(company, home_branch=branch)
    worker.branches.add(branch)
    manager = member.registered(company, "Manager", home_branch=branch)
    now = datetime.now(TZ)
    start = now - timedelta(minutes=5)
    WorkShift.objects.create(
        company=company,
        membership=worker,
        date=start.date(),
        starts_at=start,
        ends_at=start + timedelta(hours=8),
        branch=branch,
        published_at=now - timedelta(days=1),
    )
    if require_photo:
        services.update_settings(company, by=None, require_photo=True)
    return worker, manager


async def test_checkin_command_then_location(dp, bot, company, member):
    worker, _manager = await shop_with_shift(company, member)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "/checkin"))
    prompt = sent(bot)[-1]
    assert "Check in" in prompt.text and "Your shift" in prompt.text
    assert prompt.reply_markup.keyboard[0][0].request_location is True

    await dp.feed_update(bot, location(tg))
    assert "Checked in at" in sent(bot)[-1].text
    record = await AttendanceRecord.objects.aget(membership=worker)
    assert record.in_source == AttendanceRecord.Source.BOT
    assert record.in_distance_m is not None and record.in_distance_m < 20
    assert record.in_accuracy_m == 12


async def test_menu_button_then_check_out(dp, bot, company, member):
    worker, _manager = await shop_with_shift(company, member)
    tg = updates.tg_user(worker.user.telegram_id)
    await dp.feed_update(bot, updates.message(tg, "Check in / out"))
    await dp.feed_update(bot, location(tg))
    await dp.feed_update(bot, updates.message(tg, "Check in / out"))
    assert "Check out" in sent(bot)[-1].text
    await dp.feed_update(bot, location(tg))
    assert "Checked out at" in sent(bot)[-1].text
    record = await AttendanceRecord.objects.aget(membership=worker)
    assert record.status == AttendanceRecord.Status.CLOSED


async def test_menu_button_ends_another_conversation(dp, bot, company, member):
    worker, _manager = await shop_with_shift(company, member)
    tg = updates.tg_user(worker.user.telegram_id)
    await dp.feed_update(bot, updates.message(tg, "/new"))
    await dp.feed_update(bot, updates.message(tg, "Check in / out"))
    assert "Check in" in sent(bot)[-1].text


async def test_selfie_step(dp, bot, company, member, monkeypatch):
    monkeypatch.setattr(mocked_bot, "FILE_CONTENT", jpeg_bytes())
    worker, _manager = await shop_with_shift(company, member, require_photo=True)
    tg = updates.tg_user(worker.user.telegram_id)
    await dp.feed_update(bot, updates.message(tg, "/checkin"))
    await dp.feed_update(bot, location(tg))
    assert "selfie" in sent(bot)[-1].text
    await dp.feed_update(bot, updates.message(tg, "hello"))
    assert "selfie" in sent(bot)[-1].text
    await dp.feed_update(bot, updates.photo(tg))
    assert "Checked in at" in sent(bot)[-1].text
    record = await AttendanceRecord.objects.aget(membership=worker)
    assert record.in_photo.name.endswith(".jpg")


async def test_text_instead_of_location_and_cancel(dp, bot, company, member):
    worker, _manager = await shop_with_shift(company, member)
    tg = updates.tg_user(worker.user.telegram_id)
    await dp.feed_update(bot, updates.message(tg, "/checkin"))
    await dp.feed_update(bot, updates.message(tg, "I'm here"))
    assert "share where you are" in sent(bot)[-1].text
    await dp.feed_update(bot, updates.message(tg, "Cancel"))
    assert "nothing changed" in sent(bot)[-1].text
    assert not await AttendanceRecord.objects.filter(membership=worker).aexists()


async def test_far_away_in_reject_mode_is_refused(dp, bot, company, member):
    worker, _manager = await shop_with_shift(company, member)
    await sync_to_async(services.update_settings)(company, by=None, outside_action="reject")
    tg = updates.tg_user(worker.user.telegram_id)
    await dp.feed_update(bot, updates.message(tg, "/checkin"))
    await dp.feed_update(bot, location(tg, lat=41.30, lng=69.21))
    assert "Check in when you get there" in sent(bot)[-1].text


async def test_module_off(dp, bot, company, member):
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)
    await dp.feed_update(bot, updates.message(tg, "/checkin"))
    assert "isn't switched on" in sent(bot)[-1].text


async def test_off_today_button_tells_the_managers(dp, bot, company, member):
    worker, manager = await shop_with_shift(company, member)
    shift = await WorkShift.objects.aget(membership=worker)
    tg = updates.tg_user(worker.user.telegram_id)
    await dp.feed_update(bot, updates.callback(tg, press(AttendanceAction.OFF_TODAY, shift.pk)))
    answers = [r.text for r in bot.requests if isinstance(r, AnswerCallbackQuery)]
    assert "manager will see" in answers[-1]
    assert any(isinstance(r, EditMessageReplyMarkup) for r in bot.requests)
    assert await JobMark.objects.filter(key=f"off:{shift.pk}").aexists()
    alert = await Notification.objects.aget(kind="attendance.no_show", recipient=manager)
    assert "off today" in alert.title


async def test_done_now_checks_out_without_a_location(dp, bot, company, member):
    worker, _manager = await shop_with_shift(company, member)
    tg = updates.tg_user(worker.user.telegram_id)
    await dp.feed_update(bot, updates.message(tg, "/checkin"))
    await dp.feed_update(bot, location(tg))
    record = await AttendanceRecord.objects.aget(membership=worker)
    await dp.feed_update(bot, updates.callback(tg, press(AttendanceAction.DONE_NOW, record.pk)))
    await record.arefresh_from_db()
    assert record.status == AttendanceRecord.Status.CLOSED
    assert AttendanceRecord.Flag.NO_LOCATION in record.flags
    assert "Checked out" in [r for r in bot.requests if isinstance(r, EditMessageText)][-1].text
    # A second press on an old button just says so.
    await dp.feed_update(bot, updates.callback(tg, press(AttendanceAction.DONE_NOW, record.pk)))
    alerts = [r.text for r in bot.requests if isinstance(r, AnswerCallbackQuery) and r.show_alert]
    assert "already checked out" in alerts[-1]


async def test_still_here_and_check_in_buttons(dp, bot, company, member):
    worker, _manager = await shop_with_shift(company, member)
    tg = updates.tg_user(worker.user.telegram_id)
    await dp.feed_update(bot, updates.callback(tg, press(AttendanceAction.STILL_HERE, 1)))
    assert "check out" in [r.text for r in bot.requests if isinstance(r, AnswerCallbackQuery)][-1]
    await dp.feed_update(bot, updates.callback(tg, press(AttendanceAction.CHECK_IN)))
    assert "Send your location" in sent(bot)[-1].text


async def test_a_forwarded_location_is_refused(dp, bot, company, member):
    from aiogram.types import MessageOriginUser

    worker, _manager = await shop_with_shift(company, member)
    tg = updates.tg_user(worker.user.telegram_id)
    await dp.feed_update(bot, updates.message(tg, "/checkin"))
    forwarded = location(tg)
    origin = MessageOriginUser(type="user", date=datetime.now(), sender_user=updates.tg_user(77))
    forwarded = forwarded.model_copy(
        update={"message": forwarded.message.model_copy(update={"forward_origin": origin})}
    )
    await dp.feed_update(bot, forwarded)
    assert "forwarded" in sent(bot)[-1].text
    assert not await AttendanceRecord.objects.filter(membership=worker).aexists()
    # Their own location still works afterwards: the conversation waits for it.
    await dp.feed_update(bot, location(tg))
    assert "Checked in at" in sent(bot)[-1].text
