"""The voice-note flow both bots share (v0.2 AI contract §6); their routers stay thin.

    sent = await take_voice(message, membership, bot, bot_name="employee")
    card, note = await act_on_draft(membership, callback_data)

`take_voice` checks that voice tasks can be used, answers "Eshitayapman…" at once, downloads
the recording with aiogram (never blocking the event loop: Django runs on the bots' database
threads through sync_to_async) and starts the draft with that message's id, so the ai worker
edits it into the card. `act_on_draft` is what the card's buttons do.
"""

import logging
from contextlib import suppress

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import Message
from asgiref.sync import sync_to_async
from django.core.exceptions import PermissionDenied

from apps.ai import bot_messages, services
from apps.ai.callbacks import AIDraftCallback, DraftAction
from apps.ai.models import AIDraft
from apps.core.exceptions import DomainError
from apps.members.models import Membership

SOURCES = {"employee": AIDraft.Source.BOT, "owner": AIDraft.Source.OWNER_BOT}
logger = logging.getLogger(__name__)


async def take_voice(
    message: Message, membership: Membership, bot: Bot, *, bot_name: str
) -> Message | None:
    """Start the draft of a voice message, audio file or video note. Returns the bot's
    message that becomes the card (None when the voice was turned down)."""
    media = message.voice or message.audio or message.video_note
    seconds = media.duration or 0
    size = media.file_size or 0
    if refusal := await refused(membership, seconds=seconds, size=size, bot_name=bot_name):
        await message.answer(refusal)
        return None
    sent = await message.answer(bot_messages.listening())
    await start_from_telegram(sent, membership, bot, media, seconds=seconds, bot_name=bot_name)
    return sent


async def refused(
    membership: Membership, *, seconds: int, size: int, bot_name: str = "employee"
) -> str | None:
    """Why this recording can't become tasks (voice off, too long, too big), or None."""
    found = await sync_to_async(services.voice_status)(membership)
    if not found.voice:
        return bot_messages.voice_off(
            membership, speech_missing=found.smart_text, typed_here=bot_name == "employee"
        )
    if seconds > found.max_seconds:
        return bot_messages.too_long(found.max_seconds)
    if size > services.AUDIO_MAX_BYTES:
        return bot_messages.too_big()
    return None


@sync_to_async
def member_for_draft(user, draft_id: int) -> Membership | None:
    """The tapping person's membership in the company of draft `draft_id` (owner bot)."""
    company_id = AIDraft.objects.filter(pk=draft_id).values_list("company_id", flat=True).first()
    if company_id is None:
        return None
    return (
        Membership.objects.filter(
            user=user, company_id=company_id, status=Membership.Status.APPROVED
        )
        .select_related("company", "user", "role", "position")
        .first()
    )


async def start_from_telegram(
    card: Message, membership: Membership, bot: Bot, media, *, seconds: int, bot_name: str
) -> None:
    """Download `media` (a Voice, Audio, VideoNote or its file id) and start its draft, to be
    shown in `card`. A file Telegram doesn't hand over turns "Listening…" into a line that says
    to send it again, never a card that listens forever."""
    try:
        downloaded = await bot.download(media)
    except TelegramAPIError:
        logger.warning("Voice note of member %s could not be fetched", membership.pk)
        await edit(card, (bot_messages.error_text("not_fetched"), None))
        return
    try:
        await sync_to_async(services.start_draft)(
            membership,
            audio=downloaded.getvalue(),
            seconds=seconds,
            source=SOURCES[bot_name],
            tg={"bot": bot_name, "chat_id": card.chat.id, "message_id": card.message_id},
        )
    except services.DraftRefused as exc:
        await edit(card, (str(exc), None))


@sync_to_async
def act_on_draft(member: Membership, data: AIDraftCallback) -> tuple[bot_messages.BotMessage, str]:
    """What a card button does, and the card afterwards with a short note for the tap.
    Callback data can be forged: a draft that isn't the tapper's own is as good as gone, so
    nobody else's transcript or tasks are ever drawn into the tapped message."""
    draft = (
        AIDraft.objects.for_company(member.company_id)
        .select_related("company", "created_by__user", "created_by__company", "created_by__role")
        .filter(pk=data.id, created_by=member)
        .first()
    )
    if draft is None:
        return (bot_messages.gone(), None), ""
    note = ""
    try:
        match data.action:
            case DraftAction.APPLY:
                result = services.apply_draft(draft, member, refresh=False)
                if result.failed:
                    note = result.failed[0]["detail"]
            case DraftAction.CANCEL:
                services.discard_draft(draft, member, refresh=False)
            case DraftAction.UNDO:
                services.undo_draft(draft, member, refresh=False)
    except (DomainError, PermissionDenied) as exc:
        note = str(exc)
    draft.refresh_from_db()
    return bot_messages.draft_card(draft), note


async def edit(target: Message, card: bot_messages.BotMessage) -> None:
    text, markup = card
    with suppress(TelegramBadRequest):  # unchanged, or too old to edit
        await target.edit_text(text, reply_markup=markup)
