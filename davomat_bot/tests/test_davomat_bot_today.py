"""`/today` (the board of a manager's branches) and `/me` (a person's day and month)."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from asgiref.sync import sync_to_async

from apps.attendance import services
from apps.attendance.tests.factories import shift_at
from apps.companies.models import Branch
from apps.notifications.emoji import has_emoji
from apps.timeoff.models import TimeOff
from davomat_bot.callbacks import MeView, TodayView
from davomat_bot.tests import updates

pytestmark = pytest.mark.django_db(transaction=True)

TZ = ZoneInfo("Asia/Tashkent")
DAY = date(2026, 10, 21)  # a Wednesday
MONDAY = date(2026, 10, 19)


def at(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ)


@pytest.fixture
def clock(monkeypatch):
    def set_now(moment: datetime) -> datetime:
        monkeypatch.setattr("django.utils.timezone.now", lambda: moment)
        return moment

    return set_now


@pytest.fixture
def morning(org, linked, clock):
    """09:40 on Wednesday: Ali in on time, Vali 25 minutes late, Bob's shift started at 09:30
    (not in yet), Sara's at 08:00 (absent), Madina on leave; Bekzod manages them all."""
    org.timezone = "Asia/Tashkent"
    org.save(update_fields=["timezone"])
    services.update_settings(org, by=None, require_location=False)
    people = {
        key: linked(role, telegram_id, first_name=first, last_name="Karimov")
        for key, role, telegram_id, first in (
            ("boss", "Manager", 8101, "Bekzod"),
            ("ali", "Employee", 8102, "Ali"),
            ("vali", "Employee", 8103, "Vali"),
            ("bob", "Employee", 8104, "Bob"),
            ("sara", "Employee", 8105, "Sara"),
            ("madina", "Employee", 8106, "Madina"),
        )
    }
    shift_at(people["ali"], DAY)
    shift_at(people["vali"], DAY)
    shift_at(people["bob"], DAY, time(9, 30), time(18, 0))
    shift_at(people["sara"], DAY, time(8, 0), time(17, 0))
    TimeOff.objects.create(
        company=org,
        membership=people["madina"],
        first_day=DAY,
        last_day=DAY,
        status=TimeOff.Status.APPROVED,
    )
    # Earlier this month: Ali 20 minutes late on Monday, 09:20-18:00.
    shift_at(people["ali"], MONDAY)
    services.check_in(people["ali"], now=at(9, 20, MONDAY), quiet=True)
    services.check_out(people["ali"], now=at(18, 0, MONDAY), quiet=True)
    services.check_in(people["ali"], now=at(8, 55), quiet=True)
    services.check_in(people["vali"], now=at(9, 25), quiet=True)
    clock(at(9, 40))
    return people


async def test_today_shows_the_board_of_the_managers_branches(dp, bot, morning):
    await dp.feed_update(bot, updates.message(updates.tg_user(8101), "/today"))

    [reply] = bot.sent()
    text = reply.text
    assert text.startswith("<b>Namuna MChJ</b> · 21.10.2026 09:40")
    assert "In the building now: 2" in text
    assert "Came today: 2 of 4" in text
    assert "<b>Late</b>\n    Vali Karimov · 25 min late, at 09:25" in text
    assert "<b>Not in yet</b>\n    Bob Karimov · shift from 09:30" in text
    assert "<b>Absent</b>\n    Sara Karimov" in text
    assert "<b>On leave</b>\n    Madina Karimov" in text
    assert "Ali Karimov" not in text  # on time: counted, not listed
    assert not has_emoji(text)
    [[refresh]] = reply.reply_markup.inline_keyboard
    assert refresh.callback_data == TodayView(branch=0).pack()


async def test_an_employee_gets_their_own_day_instead(dp, bot, morning):
    await dp.feed_update(bot, updates.message(updates.tg_user(8102), "/today"))

    assert bot.sent()[0].text == "Only managers see who is at work today. Your own day: /me"


async def test_someone_not_linked_is_told_how(dp, bot, morning):
    await dp.feed_update(bot, updates.message(updates.tg_user(8199), "/today"))
    await dp.feed_update(bot, updates.message(updates.tg_user(8199), "/me"))

    assert all("isn't linked to anyone yet" in reply.text for reply in bot.sent())


async def test_refresh_redraws_in_place_and_branches_narrow_it(dp, bot, morning, org):
    other = await Branch.objects.acreate(company=org, name="Yunusobod", order=1)
    await morning["sara"].branches.aadd(other)
    await sync_to_async(shift_at)(morning["sara"], DAY, time(10, 0), time(18, 0), branch=other)
    person = updates.tg_user(8101)

    await dp.feed_update(bot, updates.message(person, "/today"))
    board = bot.sent()[-1]
    labels = [b.text for row in board.reply_markup.inline_keyboard[1:] for b in row]
    assert labels[0] == "All branches" and "Yunusobod" in labels
    assert "<b>Branches</b>" in board.text

    await dp.feed_update(
        bot,
        updates.callback(person, TodayView(branch=other.pk).pack(), text=board.text),
    )
    [edit] = bot.edits()
    assert edit.text.startswith("<b>Namuna MChJ · Yunusobod</b>")
    assert "<b>Not in yet</b>\n    Sara Karimov · shift from 10:00" in edit.text
    assert "Bob Karimov" not in edit.text
    assert bot.answers()[-1].text == "Updated"


async def test_me_shows_today_and_the_month(dp, bot, morning):
    await dp.feed_update(bot, updates.message(updates.tg_user(8102), "/me"))

    [reply] = bot.sent()
    text = reply.text
    assert text.startswith("<b>Ali Karimov</b> · Namuna MChJ")
    assert "<b>Today</b>, 21.10\n    Shift: 09:00–18:00" in text
    assert "    In: 08:55\n    Still here" in text
    assert "<b>October</b>" in text
    assert "Days at work: 2 of 2" in text
    assert "Hours worked: 8 h 25 min" in text  # 460 on Monday, 45 so far today
    assert "Late: 1 time, 20 min in all" in text
    assert "On time: 50%" in text
    assert not has_emoji(text)

    await dp.feed_update(bot, updates.callback(updates.tg_user(8102), MeView().pack()))
    assert bot.edits() and bot.answers()[-1].text == "Updated"


async def test_me_on_a_day_off(dp, bot, morning):
    await dp.feed_update(bot, updates.message(updates.tg_user(8101), "/me"))

    text = bot.sent()[0].text
    assert "No shift today" in text
    assert "Days at work: 0" in text


async def test_me_on_leave(dp, bot, morning):
    await dp.feed_update(bot, updates.message(updates.tg_user(8106), "/me"))

    assert "    On leave" in bot.sent()[0].text
