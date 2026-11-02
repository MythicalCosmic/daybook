"""Voice notes in the owner bot: the company's tasks by voice, a picker with several companies."""

import pytest
from aiogram.methods import EditMessageText
from asgiref.sync import sync_to_async

from apps.ai.callbacks import AIDraftCallback, DraftAction
from apps.ai.models import AIDraft
from apps.ai.tests.conftest import switch_ai_on
from apps.companies.tests.factories import CompanyFactory
from ownerbot.callbacks import VoicePick
from ownerbot.tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def owner(company, member):
    switch_ai_on(company)
    person = member(
        company, "Owner", user__telegram_id=7601, first_name="Dilnoza", last_name="Karimova"
    )
    member.registered(company, first_name="Alisher", last_name="Valiyev")
    return person


async def test_one_company_hears_the_voice_note_at_once(dp, bot, owner, settings, monkeypatch):
    settings.AI_FAKE = True
    monkeypatch.setattr("apps.notifications.telegram.edit_message", lambda *a, **k: None)

    await dp.feed_update(bot, updates.voice(updates.tg_user(7601)))

    [listening] = bot.sent()
    assert listening.text == "Listening…"
    draft = await sync_to_async(AIDraft.objects.get)()
    assert (draft.source, draft.tg_bot, draft.status) == ("owner_bot", "owner", "ready")
    assert draft.created_by_id == owner.pk


async def test_several_companies_ask_which_first(dp, bot, owner, member, settings, monkeypatch):
    settings.AI_FAKE = True
    monkeypatch.setattr("apps.notifications.telegram.edit_message", lambda *a, **k: None)
    other = await sync_to_async(CompanyFactory)(name="Demo Distribyutor")
    await sync_to_async(switch_ai_on)(other)
    await member.acreate(other, "Owner", user=owner.user)
    tg = updates.tg_user(7601)

    await dp.feed_update(bot, updates.voice(tg))

    [question] = bot.sent()
    assert question.text == "Which company is this voice note for?"
    assert not await sync_to_async(AIDraft.objects.exists)()

    await dp.feed_update(bot, updates.callback(tg, VoicePick(company=owner.company_id).pack()))

    draft = await sync_to_async(AIDraft.objects.get)()
    assert draft.company_id == owner.company_id
    edits = [request.text for request in bot.requests if isinstance(request, EditMessageText)]
    assert "Listening…" in edits


async def test_without_ai_the_owner_is_told_where_to_switch_it_on(dp, bot, company, member):
    await member.acreate(company, "Owner", user__telegram_id=7602)

    await dp.feed_update(bot, updates.voice(updates.tg_user(7602)))

    [reply] = bot.sent()
    assert "dashboard" in reply.text
    # The owner bot takes no typed task: it used to say "Type the task instead" (a dead end).
    assert "Type the task" not in reply.text


async def test_a_forged_draft_button_shows_nothing_of_another_persons_voice_note(
    dp, bot, owner, member, monkeypatch
):
    """An owner who also works in another company forges its manager's draft id: the owner
    bot must not show that voice note (its transcript, its tasks), nor act on it."""
    monkeypatch.setattr("apps.notifications.telegram.edit_message", lambda *a, **k: None)
    other = await sync_to_async(CompanyFactory)(name="Demo Distribyutor")
    await sync_to_async(switch_ai_on)(other)
    await member.acreate(other, user=owner.user)  # a plain employee there
    manager = await member.aregistered(other, "Manager", first_name="Bekzod")
    draft = await sync_to_async(AIDraft.objects.create)(
        company=other,
        created_by=manager,
        source="bot",
        status=AIDraft.Status.READY,
        transcript="Alisher, kassani sanab qo‘y. Maxfiy gap.",
        payload={"drafts": [{"title": "Kassani sanash", "assignee_id": None}], "questions": []},
    )

    for action in DraftAction:
        forged = AIDraftCallback(action=action, id=draft.pk).pack()
        await dp.feed_update(bot, updates.callback(updates.tg_user(7601), forged))

    shown = " ".join(r.text for r in bot.requests if isinstance(r, EditMessageText))
    assert "Maxfiy" not in shown and "Kassani" not in shown
    await sync_to_async(draft.refresh_from_db)()
    assert draft.status == AIDraft.Status.READY
