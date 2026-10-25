"""`/today`, `/dashboard`, the welcome and the menu button."""

from datetime import time

import pytest
from aiogram.methods import SetChatMenuButton, SetMyCommands
from aiogram.types import MenuButtonCommands, MenuButtonWebApp
from asgiref.sync import sync_to_async

from apps.companies.tests.factories import CompanyFactory
from apps.console import registry
from apps.notifications.emoji import has_emoji
from ownerbot.callbacks import TodayPick
from ownerbot.commands import set_commands
from ownerbot.tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def owner(company, member):
    company.name = "Demo Dorixona"
    company.save()
    branch = company.branches.get()
    branch.name = "Chilonzor"
    branch.opens_at, branch.closes_at = time(0, 0), time(23, 59)
    branch.save()
    return member(company, "Owner", user__telegram_id=7501, user__first_name="Dilnoza")


async def test_today_shows_branches_sections_and_approvals(
    dp, bot, owner, settings, isolated_registries
):
    settings.DASHBOARD_URL = "https://app.example.uz/dashboard/"

    def tasks_section(company, day, now, branch_ids):
        # A section may still bring an emoji: the bot leaves it out.
        return {"emoji": chr(0x2705), "title": "Tasks", "lines": ["18 of 24 done", "3 late"]}

    isolated_registries.register_brief_section(
        "tasks.today", perm=None, order=10, build=tasks_section
    )
    isolated_registries.register_brief_section(
        "tasks.silent", perm=None, order=20, build=lambda *args: None
    )

    await dp.feed_update(bot, updates.message(updates.tg_user(7501), "/today"))

    [reply] = bot.sent()
    assert "Demo Dorixona" in reply.text
    assert "Chilonzor" in reply.text
    assert "<b>Tasks</b>\n    18 of 24 done\n    3 late" in reply.text
    assert "Nothing waits for your decision." in reply.text
    assert not has_emoji(reply.text)
    [[opened]] = reply.reply_markup.inline_keyboard
    assert opened.web_app.url == f"https://app.example.uz/dashboard/c/{owner.company_id}"


async def test_with_several_companies_today_asks_which(dp, bot, owner, member):
    cafe = await sync_to_async(CompanyFactory)(name="Demo Distribyutor")
    await sync_to_async(member)(cafe, "Owner", user=owner.user)

    await dp.feed_update(bot, updates.message(updates.tg_user(7501), "/today"))
    question = bot.sent()[0]
    names = [row[0].text for row in question.reply_markup.inline_keyboard]
    assert names == ["Demo Distribyutor", "Demo Dorixona"]

    await dp.feed_update(
        bot, updates.callback(updates.tg_user(7501), TodayPick(company=cafe.pk).pack())
    )
    assert "Demo Distribyutor" in bot.sent()[-1].text


async def test_today_without_companies(dp, bot):
    await dp.feed_update(bot, updates.message(updates.tg_user(7502), "/today"))

    assert "/new" in bot.sent()[0].text


async def test_welcome_lists_companies_and_what_waits(dp, bot, owner, isolated_registries):
    isolated_registries.register_queue(
        "tasks.reviews",
        perm=None,
        label="Reviews",
        count=lambda member: 3,
        items=lambda member, limit: [],
    )

    await dp.feed_update(bot, updates.message(updates.tg_user(7501), "/start"))

    text = bot.sent()[0].text
    assert "Dilnoza" in text and "Demo Dorixona" in text and "3 waiting for you" in text
    assert "/today" in text


async def test_dashboard_command(dp, bot, settings):
    settings.DASHBOARD_URL = "https://app.example.uz/dashboard/"
    await dp.feed_update(bot, updates.message(updates.tg_user(7503), "/dashboard"))
    [[button]] = bot.sent()[0].reply_markup.inline_keyboard
    assert button.web_app.url == "https://app.example.uz/dashboard/"

    settings.DASHBOARD_URL = "http://localhost:28111/dashboard/"
    await dp.feed_update(bot, updates.message(updates.tg_user(7503), "/dashboard"))
    assert "localhost:28111" in bot.sent()[-1].text


async def test_commands_and_the_menu_button(bot, settings):
    settings.DASHBOARD_URL = "https://app.example.uz/dashboard/"

    await set_commands(bot)

    menus = [r for r in bot.requests if isinstance(r, SetMyCommands)]
    assert [c.command for c in menus[0].commands] == [
        "today",
        "dashboard",
        "new",
        "language",
        "start",
    ]
    [menu] = [r for r in bot.requests if isinstance(r, SetChatMenuButton)]
    assert isinstance(menu.menu_button, MenuButtonWebApp)
    assert menu.menu_button.web_app.url == "https://app.example.uz/dashboard/"

    settings.DASHBOARD_URL = ""
    await set_commands(bot)
    assert isinstance(
        [r for r in bot.requests if isinstance(r, SetChatMenuButton)][-1].menu_button,
        MenuButtonCommands,
    )
    assert registry  # the registry module is importable from the bot


async def test_figures_from_modules_read_in_words(dp, bot, owner, monkeypatch):
    """The tasks, attendance, finance and people sections send figures for the dashboard; the
    chat gets them in words, and a section of figures the bot has no words for stays out."""
    sections = {
        "tasks": {
            "done": 3,
            "total": 5,
            "late": 2,
            "review": 1,
            "on_time_7d": "80.0",
            "late_tasks": [{"id": 1, "title": "Count the till", "assignee": {"name": "Ali"}}],
        },
        "attendance": {
            "present": 4,
            "rostered": 6,
            "late": [{"id": 1, "name": "Ali"}],
            "absent": [],
            "not_in_yet": [{"id": 2, "name": "Vali"}],
        },
        "finance": {
            "currency": "UZS",
            "cash": "1500000.00",
            "income_yesterday": "200000.00",
            "expense_yesterday": "50000.00",
            "receivable_overdue": "0",
            "receivable_overdue_count": 0,
            "payable_overdue": "700000.00",
            "payable_overdue_count": 1,
            "due_today_count": 0,
            "url": "/c/1/finance",
        },
        "members.people": {
            "pending_requests": 2,
            "joined_this_week": [],
            "off_today": [{"id": 3, "name": "Madina"}],
            "suspended": 0,
            "headcount": 15,
        },
        "insights.raw": {"score": 7, "items": [1, 2]},
    }
    monkeypatch.setattr(
        registry, "collect_brief_sections", lambda *args, **kwargs: list(sections.items())
    )

    await dp.feed_update(bot, updates.message(updates.tg_user(7501), "/today"))

    [reply] = bot.sent()
    text = reply.text.replace(chr(0xA0), " ")
    assert "<b>Tasks</b>\n    Done today: 3 of 5\n    Late: 2\n    Waiting for check: 1" in text
    assert "On time over 7 days: 80.0%" in text
    assert "Most overdue:" in text and "Count the till · Ali" in text
    assert "<b>Attendance</b>\n    At work: 4/6\n    Late: Ali\n    Not in yet: Vali" in text
    assert "<b>Finance</b>\n    Balance: 1 500 000 UZS" in text
    assert "Overdue to pay:" in text and "Overdue to receive" not in text
    assert "<b>People</b>\n    Team: 15\n    Join requests: 2\n    Off today: Madina" in text
    # No raw data anywhere: no keys, brackets or the section nobody put into words.
    for raw in ("score", "late_tasks", "{", "[", "url:", "/c/1/finance"):
        assert raw not in text
