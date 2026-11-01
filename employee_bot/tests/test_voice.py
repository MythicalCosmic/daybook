"""Voice messages become task drafts, and the card's buttons create them (AI contract §6)."""

import pytest
from aiogram.methods import EditMessageText
from asgiref.sync import sync_to_async

from apps.ai.callbacks import AIDraftCallback, DraftAction
from apps.ai.models import AIDraft
from apps.ai.tests.conftest import OGG, switch_ai_on
from apps.tasks.models import Task
from bot.states.tasks import NewTask
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def heard(monkeypatch):
    """What the bot downloads is a real (tiny) Ogg recording."""
    monkeypatch.setattr("tests.mocked_bot.FILE_CONTENT", OGG)


@pytest.fixture
def card_edits(monkeypatch):
    edits = []
    monkeypatch.setattr(
        "apps.notifications.telegram.edit_message",
        lambda bot, chat_id, message_id, text, reply_markup=None: edits.append(
            {
                "bot": bot,
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": reply_markup,
            }
        ),
    )
    return edits


async def team(company, member):
    await sync_to_async(switch_ai_on)(company)
    manager = await member.aregistered(
        company, "Manager", first_name="Bekzod", last_name="Mirzayev"
    )
    await member.aregistered(company, first_name="Alisher", last_name="Valiyev")
    await member.aregistered(company, first_name="Madina", last_name="Saidova")
    return manager


async def test_with_voice_off_the_bot_says_so_in_one_line(dp, bot, company, member):
    worker = await member.aregistered(company)

    await dp.feed_update(bot, updates.voice(updates.tg_user(worker.user.telegram_id)))

    [reply] = bot.sent_texts()
    assert "Voice tasks aren't switched on" in reply
    assert not await sync_to_async(AIDraft.objects.exists)()


async def test_owners_are_told_where_to_switch_it_on(dp, bot, company, member):
    owner = await member.aregistered(company, "Owner")

    await dp.feed_update(bot, updates.voice(updates.tg_user(owner.user.telegram_id)))

    [reply] = bot.sent_texts()
    assert "dashboard" in reply


async def test_a_voice_message_becomes_a_card(
    dp, bot, company, member, settings, heard, card_edits
):
    settings.AI_FAKE = True
    manager = await team(company, member)
    tg = updates.tg_user(manager.user.telegram_id)

    await dp.feed_update(bot, updates.voice(tg))

    [listening] = bot.sent_texts()
    assert listening == "Listening…"
    draft = await sync_to_async(AIDraft.objects.get)()
    assert (draft.source, draft.tg_bot, draft.tg_chat_id) == ("bot", "employee", tg.id)
    assert draft.status == AIDraft.Status.READY
    assert draft.audio_seconds == 9
    [card] = [edit for edit in card_edits if edit["message_id"] == draft.tg_message_id][-1:]
    assert "Alisher Valiyev" in card["text"]
    assert f"aid:apply:{draft.pk}" in str(card["reply_markup"])


async def test_dictating_replaces_the_new_task_title(
    dp, bot, company, member, settings, heard, card_edits
):
    settings.AI_FAKE = True
    manager = await team(company, member)
    tg = updates.tg_user(manager.user.telegram_id)
    context = dp.fsm.get_context(bot, chat_id=tg.id, user_id=tg.id)
    await context.set_state(NewTask.title)

    await dp.feed_update(bot, updates.voice(tg))

    assert await context.get_state() is None
    assert bot.sent_texts() == ["Listening…"]
    assert await sync_to_async(AIDraft.objects.count)() == 1


async def test_a_recording_that_cannot_be_fetched_does_not_keep_listening(
    dp, bot, company, member, settings, monkeypatch
):
    """Telegram fails to hand over the file: "Listening…" must not stay on screen forever,
    it turns into a line that says to send it again."""
    from aiogram.exceptions import TelegramNetworkError
    from aiogram.methods import GetFile

    settings.AI_FAKE = True
    manager = await team(company, member)

    async def broken_download(*args, **kwargs):
        raise TelegramNetworkError(method=GetFile(file_id="voice"), message="timeout")

    monkeypatch.setattr(type(bot), "download", broken_download)

    await dp.feed_update(bot, updates.voice(updates.tg_user(manager.user.telegram_id)))

    assert bot.sent_texts()[0] == "Listening…"
    [edited] = [r for r in bot.requests if isinstance(r, EditMessageText)]
    assert edited.text == "Something went wrong with this voice note. Send it again."
    assert not await sync_to_async(AIDraft.objects.exists)()


async def test_a_recording_too_long_is_turned_down(dp, bot, company, member, settings):
    settings.AI_FAKE = True
    manager = await team(company, member)

    await dp.feed_update(
        bot, updates.voice(updates.tg_user(manager.user.telegram_id), duration=500)
    )

    [reply] = bot.sent_texts()
    assert "too long" in reply
    assert not await sync_to_async(AIDraft.objects.exists)()


async def test_create_from_the_card(dp, bot, company, member, settings, heard, card_edits):
    settings.AI_FAKE = True
    manager = await team(company, member)
    tg = updates.tg_user(manager.user.telegram_id)
    await dp.feed_update(bot, updates.voice(tg))
    draft = await sync_to_async(AIDraft.objects.get)()

    apply = AIDraftCallback(action=DraftAction.APPLY, id=draft.pk).pack()
    await dp.feed_update(bot, updates.callback(tg, apply))

    await sync_to_async(draft.refresh_from_db)()
    assert draft.status == AIDraft.Status.APPLIED
    assert await sync_to_async(Task.objects.filter(created_by=manager).count)() == 2
    [edited] = [r for r in bot.requests if isinstance(r, EditMessageText)]
    assert edited.text.startswith("<b>Created 2 tasks</b>")
    assert "Alisher Valiyev" in edited.text


async def test_cancel_from_the_card(dp, bot, company, member, settings, heard, card_edits):
    settings.AI_FAKE = True
    manager = await team(company, member)
    tg = updates.tg_user(manager.user.telegram_id)
    await dp.feed_update(bot, updates.voice(tg))
    draft = await sync_to_async(AIDraft.objects.get)()

    cancel = AIDraftCallback(action=DraftAction.CANCEL, id=draft.pk).pack()
    await dp.feed_update(bot, updates.callback(tg, cancel))

    await sync_to_async(draft.refresh_from_db)()
    assert draft.status == AIDraft.Status.DISCARDED
    [edited] = [r for r in bot.requests if isinstance(r, EditMessageText)]
    assert edited.text == "Cancelled."
    assert not await sync_to_async(Task.objects.exists)()


async def test_someone_elses_card_does_nothing(
    dp, bot, company, member, settings, heard, card_edits
):
    settings.AI_FAKE = True
    manager = await team(company, member)
    await dp.feed_update(bot, updates.voice(updates.tg_user(manager.user.telegram_id)))
    draft = await sync_to_async(AIDraft.objects.get)()
    other = await member.aregistered(company, "Manager")

    apply = AIDraftCallback(action=DraftAction.APPLY, id=draft.pk).pack()
    await dp.feed_update(bot, updates.callback(updates.tg_user(other.user.telegram_id), apply))

    await sync_to_async(draft.refresh_from_db)()
    assert draft.status == AIDraft.Status.READY
    assert not await sync_to_async(Task.objects.exists)()


@pytest.mark.parametrize("action", list(DraftAction))
async def test_a_forged_button_shows_nothing_of_someone_elses_voice_note(
    dp, bot, company, member, settings, heard, card_edits, action
):
    """Callback data can be forged (any client can send any bytes): another person's draft id
    must not turn the tapped message into that draft's card, with its transcript and names."""
    settings.AI_FAKE = True
    manager = await team(company, member)
    await dp.feed_update(bot, updates.voice(updates.tg_user(manager.user.telegram_id)))
    draft = await sync_to_async(AIDraft.objects.get)()
    other = await member.aregistered(company, "Manager")
    bot.requests.clear()

    forged = AIDraftCallback(action=action, id=draft.pk).pack()
    await dp.feed_update(bot, updates.callback(updates.tg_user(other.user.telegram_id), forged))

    shown = " ".join(r.text for r in bot.requests if isinstance(r, EditMessageText))
    assert "Alisher" not in shown and "muzlatgich" not in shown.lower()
    markups = [getattr(request, "reply_markup", None) for request in bot.requests]
    assert f"aid:apply:{draft.pk}" not in str(markups)
    await sync_to_async(draft.refresh_from_db)()
    assert draft.status == AIDraft.Status.READY


async def test_a_forged_button_on_a_group_message_edits_nothing_there(
    dp, bot, company, member, settings, heard, card_edits
):
    """The card lives in a private chat: a draft (or "+1 hour") button forged onto one of the
    bot's messages in a team group must not rewrite that group message."""
    from apps.ai.callbacks import AILateCallback, LateAction

    settings.AI_FAKE = True
    manager = await team(company, member)
    tg = updates.tg_user(manager.user.telegram_id)
    await dp.feed_update(bot, updates.voice(tg))
    draft = await sync_to_async(AIDraft.objects.get)()
    task = await sync_to_async(Task.objects.create)(
        company=company, title="Kassa", assignee=manager, created_by=manager
    )
    bot.requests.clear()

    for data in (
        AIDraftCallback(action=DraftAction.CANCEL, id=draft.pk).pack(),
        AILateCallback(action=LateAction.HOUR_MORE, task_id=task.pk).pack(),
    ):
        await dp.feed_update(bot, updates.group_callback(tg, data))

    assert not [r for r in bot.requests if isinstance(r, EditMessageText)]
    await sync_to_async(draft.refresh_from_db)()
    assert draft.status == AIDraft.Status.READY


async def test_the_card_escapes_what_was_said(bot, company, member, settings):
    from apps.ai import bot_messages

    manager = await team(company, member)

    def card():
        draft = AIDraft.objects.create(
            company=company,
            created_by=manager,
            source="bot",
            status=AIDraft.Status.READY,
            transcript="<script>alert(1)</script> Alisher",
            payload={
                "drafts": [
                    {
                        "title": "<b>Kassa</b> & <i>",
                        "assignee_id": None,
                        "assignee_guess": "<u>",
                        "due_at": None,
                        "priority": "normal",
                        "checklist": [],
                        "proof": "none",
                        "problems": ["no_assignee_match"],
                    }
                ],
                "questions": ["<a href='x'>?</a>"],
            },
        )
        return bot_messages.draft_card(draft)

    text, _markup = await sync_to_async(card)()
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert "&lt;b&gt;Kassa&lt;/b&gt; &amp; &lt;i&gt;" in text
    assert "<u>" not in text and "<a href" not in text
