"""The bot in company group chats: linking a group, choosing what it gets, and housekeeping."""

from contextlib import suppress
from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import IS_MEMBER, IS_NOT_MEMBER, ChatMemberUpdatedFilter, Command
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message
from asgiref.sync import sync_to_async
from django.core.exceptions import PermissionDenied
from django.utils import translation

from apps.accounts.models import User
from apps.core.exceptions import DomainError
from apps.groups import bot_messages, services
from apps.groups.callbacks import GroupAction, GroupCallback
from apps.groups.models import GroupEvent, TelegramGroup
from apps.members.bot_messages import BotMessage

GROUP_CHATS = (ChatType.GROUP, ChatType.SUPERGROUP)

router = Router(name="groups")
router.message.filter(F.chat.type.in_(GROUP_CHATS))
router.my_chat_member.filter(F.chat.type.in_(GROUP_CHATS))
router.callback_query.filter(F.message.chat.type.in_(GROUP_CHATS))


@dataclass
class Outcome:
    """What a settings button produced: the refreshed message, and an alert if it was refused."""

    message: BotMessage | None = None
    alert: str | None = None
    keep_text: bool = False  # only the buttons changed


# `user` is missing when someone posts as the group itself (an anonymous admin).


@router.my_chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def added(event: ChatMemberUpdated, bot: Bot, user: User | None = None) -> None:
    reply = await _added(event.chat.id, event.chat.title or "", user)
    if reply is not None:
        text, markup = reply
        await bot.send_message(event.chat.id, text, reply_markup=markup)


@router.my_chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def removed(event: ChatMemberUpdated, user: User | None = None) -> None:
    await sync_to_async(services.bot_removed)(event.chat.id, by=user)


# Upgrading to a supergroup changes the chat id; both sides of the move are announced.


@router.message(F.migrate_to_chat_id)
async def upgraded(message: Message) -> None:
    await sync_to_async(services.migrated)(message.chat.id, message.migrate_to_chat_id)


@router.message(F.migrate_from_chat_id)
async def upgraded_into(message: Message) -> None:
    await sync_to_async(services.migrated)(message.migrate_from_chat_id, message.chat.id)


@router.message(Command("connect"))
async def connect(message: Message, user: User | None = None) -> None:
    text, markup = await _connect(message.chat.id, message.chat.title or "", user)
    await message.answer(text, reply_markup=markup)


@router.message(Command("settings"))
async def settings(message: Message, user: User | None = None) -> None:
    text, markup = await _settings(message.chat.id, user)
    await message.answer(text, reply_markup=markup)


@router.message(Command("disconnect"))
async def disconnect(message: Message, user: User | None = None) -> None:
    text, markup = await _disconnect(message.chat.id, user)
    await message.answer(text, reply_markup=markup)


@router.callback_query(GroupCallback.filter())
async def settings_button(
    callback: CallbackQuery, callback_data: GroupCallback, user: User
) -> None:
    outcome = await _press(callback.message.chat.id, callback_data, user)
    if outcome.message is not None and isinstance(callback.message, Message):
        text, markup = outcome.message
        # Unchanged or too old to edit: nothing more to do.
        with suppress(TelegramBadRequest):
            if outcome.keep_text:
                await callback.message.edit_reply_markup(reply_markup=markup)
            else:
                await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer(outcome.alert, show_alert=outcome.alert is not None)


@sync_to_async
def _added(chat_id: int, title: str, user: User | None) -> BotMessage | None:
    if services.find(chat_id) is not None:
        return None  # still linked, e.g. the group just became a supergroup
    if user is None or services.managing_membership(user) is None:
        return bot_messages.welcome()
    group = services.connect(chat_id, title, by=user)
    with translation.override(group.company.default_language):
        return bot_messages.connected(group)


@sync_to_async
def _connect(chat_id: int, title: str, user: User | None) -> BotMessage:
    if user is None:
        return bot_messages.anonymous()
    try:
        group = services.connect(chat_id, title, by=user)
    except (PermissionDenied, DomainError) as exc:
        return str(exc), None
    with translation.override(group.company.default_language):
        return bot_messages.connected(group)


@sync_to_async
def _settings(chat_id: int, user: User | None) -> BotMessage:
    group, refusal = _for_manager(chat_id, user)
    if group is None:
        return refusal
    with translation.override(group.company.default_language):
        return bot_messages.settings(group)


@sync_to_async
def _disconnect(chat_id: int, user: User | None) -> BotMessage:
    group, refusal = _for_manager(chat_id, user)
    if group is None:
        return refusal
    services.disconnect(group, by=user)
    with translation.override(group.company.default_language):
        return bot_messages.disconnected()


@sync_to_async
def _press(chat_id: int, data: GroupCallback, user: User) -> Outcome:
    group, refusal = _for_manager(chat_id, user)
    if group is None:
        return Outcome(alert=refusal[0])
    keep_text = False
    try:
        match data.action:
            case GroupAction.TOGGLE if data.event in GroupEvent.values:
                group = services.toggle_event(group, GroupEvent(data.event), by=user)
                build, keep_text = bot_messages.settings, True
            case GroupAction.POSITION:
                group = services.toggle_position(group, data.position_id, by=user)
                build, keep_text = bot_messages.positions_picker, True
            case GroupAction.WHO:
                build = bot_messages.positions_picker
            case GroupAction.BACK:
                build = bot_messages.settings
            case GroupAction.CLOSE:
                build = bot_messages.settings_saved
            case _:
                return Outcome()  # a button from an older version of the bot
    except (PermissionDenied, DomainError) as exc:
        return Outcome(alert=str(exc))
    with translation.override(group.company.default_language):
        return Outcome(message=build(group), keep_text=keep_text)


def _for_manager(chat_id: int, user: User | None) -> tuple[TelegramGroup | None, BotMessage | None]:
    """This chat's group when `user` may change it; otherwise the reply saying why not."""
    group = services.find(chat_id)
    if group is None:
        return None, bot_messages.not_connected()
    if user is None:
        return None, bot_messages.anonymous()
    try:
        services.ensure_manager(group, user)
    except PermissionDenied as exc:
        return None, (str(exc), None)
    return group, None
