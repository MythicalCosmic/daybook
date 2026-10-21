"""The employee bot's project touchpoints: the update conversation behind `/start upd_<id>`,
the one-tap nudge buttons, and "you were added to project X"."""

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from asgiref.sync import sync_to_async

from apps.inbox.callbacks import InboxAction
from apps.inbox.models import Notification
from apps.projects import services
from apps.projects.callbacks import ProjectUpdateCallback, UpdateStep
from apps.projects.models import ProjectUpdate
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


@sync_to_async
def make_project(company, lead, by, **fields):
    return services.create_project(
        company, by=by, name="Chilonzor branch opening", key="OPEN", lead=lead, **fields
    )


def tap(user_id: int, data: str):
    return updates.callback(updates.tg_user(user_id), data)


def health(project, value: str) -> str:
    return ProjectUpdateCallback(step=UpdateStep.HEALTH, project_id=project.pk, health=value).pack()


async def test_a_lead_posts_an_update_from_the_deep_link(dp, bot, company, member):
    owner = await member.aregistered(company, "Owner")
    lead = await member.aregistered(company, first_name="Jasur")
    project = await make_project(company, lead, owner)
    tg = lead.user.telegram_id

    await dp.feed_update(bot, updates.message(updates.tg_user(tg), f"/start upd_{project.pk}"))
    await dp.feed_update(bot, tap(tg, health(project, "at_risk")))
    await dp.feed_update(bot, updates.message(updates.tg_user(tg), "Tiles are three days late."))

    texts = bot.sent_texts()
    assert "OPEN" in texts[0] and "going" in texts[0]
    [asked] = [r for r in bot.requests if isinstance(r, EditMessageText)]
    assert "one or two lines" in asked.text
    update = await ProjectUpdate.objects.aget(project=project)
    assert (update.health, update.text, update.author_id) == (
        "at_risk",
        "Tiles are three days late.",
        lead.pk,
    )
    assert "Update posted" in texts[-1]


async def test_skipping_the_text_posts_just_the_health(dp, bot, company, member):
    owner = await member.aregistered(company, "Owner")
    project = await make_project(company, owner, owner)
    tg = owner.user.telegram_id
    skip = ProjectUpdateCallback(
        step=UpdateStep.SKIP, project_id=project.pk, health="on_track"
    ).pack()

    await dp.feed_update(bot, updates.message(updates.tg_user(tg), f"/start upd_{project.pk}"))
    await dp.feed_update(bot, tap(tg, health(project, "on_track")))
    await dp.feed_update(bot, tap(tg, skip))

    update = await ProjectUpdate.objects.aget(project=project)
    assert (update.health, update.text) == ("on_track", "")


async def test_not_now_ends_the_conversation(dp, bot, company, member):
    owner = await member.aregistered(company, "Owner")
    project = await make_project(company, owner, owner)
    tg = owner.user.telegram_id
    stop = ProjectUpdateCallback(step=UpdateStep.STOP, project_id=project.pk).pack()

    await dp.feed_update(bot, updates.message(updates.tg_user(tg), f"/start upd_{project.pk}"))
    await dp.feed_update(bot, tap(tg, stop))
    await dp.feed_update(bot, updates.message(updates.tg_user(tg), "hello"))

    assert not await ProjectUpdate.objects.filter(project=project).aexists()
    edits = [r.text for r in bot.requests if isinstance(r, EditMessageText)]
    assert edits and "later" in edits[0]


async def test_people_outside_the_project_cant_post(dp, bot, company, member, other_company):
    owner = await member.aregistered(company, "Owner")
    outsider = await member.aregistered(company)
    stranger = await member.aregistered(other_company)
    project = await make_project(company, owner, owner)

    await dp.feed_update(
        bot, updates.message(updates.tg_user(outsider.user.telegram_id), f"/start upd_{project.pk}")
    )
    await dp.feed_update(
        bot, updates.message(updates.tg_user(stranger.user.telegram_id), f"/start upd_{project.pk}")
    )
    await dp.feed_update(bot, tap(outsider.user.telegram_id, health(project, "on_track")))

    texts = bot.sent_texts()
    assert all("isn't there" in text for text in texts[:2])
    alerts = [r.text for r in bot.requests if isinstance(r, AnswerCallbackQuery) and r.show_alert]
    assert alerts and "isn't there" in alerts[0]
    assert not await ProjectUpdate.objects.filter(project=project).aexists()


async def test_a_viewer_is_told_only_members_post(dp, bot, company, member):
    owner = await member.aregistered(company, "Owner")
    viewer = await member.aregistered(company)
    project = await make_project(company, owner, owner)
    await sync_to_async(services.add_member)(project, viewer, by=owner, role="viewer")

    await dp.feed_update(
        bot, updates.message(updates.tg_user(viewer.user.telegram_id), f"/start upd_{project.pk}")
    )

    assert "lead and members" in bot.sent_texts()[-1]


async def test_the_nudge_buttons_post_in_one_tap(dp, bot, company, member):
    from apps.projects import jobs

    owner = await member.aregistered(company, "Owner")
    lead = await member.aregistered(company, first_name="Jasur")
    project = await make_project(company, lead, owner, status="active")
    await sync_to_async(jobs.nudge_leads)(_monday_noon(company))
    note = await Notification.objects.aget(kind="projects.update_nudge", recipient=lead)

    await dp.feed_update(
        bot,
        tap(lead.user.telegram_id, InboxAction(notification_id=note.pk, key="off_track").pack()),
    )

    update = await ProjectUpdate.objects.aget(project=project)
    assert update.health == "off_track"
    answers = [r.text for r in bot.requests if isinstance(r, AnswerCallbackQuery)]
    assert any("Off track" in text for text in answers)


async def test_someone_added_to_a_project_hears_about_it(dp, bot, company, member):
    owner = await member.aregistered(company, "Owner")
    worker = await member.aregistered(company, first_name="Aziz")
    project = await make_project(company, owner, owner)

    await sync_to_async(services.add_member)(project, worker, by=owner)

    note = await Notification.objects.aget(kind="projects.added", recipient=worker)
    assert "OPEN" in note.title
    assert not [r for r in bot.requests if isinstance(r, SendMessage)]  # delivery is Celery's job


def _monday_noon(company):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from django.utils import timezone

    tz = ZoneInfo(company.timezone)
    today = timezone.localtime(timezone.now(), tz).date()
    monday = today - timedelta(days=today.weekday())
    return datetime(monday.year, monday.month, monday.day, 12, 0, tzinfo=tz)
