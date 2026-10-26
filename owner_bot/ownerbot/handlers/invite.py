"""`/invite`: QR codes of the company's invite links, as pictures to show people, and a team link
made in three taps (ownerbot.invite). Like every menu command it ends a conversation in progress.
"""

from contextlib import suppress

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from asgiref.sync import sync_to_async
from django.core.exceptions import PermissionDenied
from django.utils import translation

from apps.accounts.models import User
from apps.core.exceptions import DomainError
from ownerbot import invite
from ownerbot.callbacks import InviteAct, InviteNew, InvitePick

router = Router(name="invite")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)


@router.message(Command("invite"))
async def cmd_invite(message: Message, user: User, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _in_language(user, invite.start, user)
    await message.answer(text, reply_markup=markup)


@router.callback_query(InvitePick.filter())
async def picked(callback: CallbackQuery, callback_data: InvitePick, user: User) -> None:
    reply = await _for_company(user, callback_data.company, invite.overview)
    await _replace(callback, reply)
    await callback.answer()


@router.callback_query(InviteAct.filter(F.action == "list"))
async def back_to_list(callback: CallbackQuery, callback_data: InviteAct, user: User) -> None:
    reply = await _for_company(user, callback_data.company, invite.overview)
    if callback.message.photo:  # under a QR code: the list comes as a new message
        text, markup = _message(reply)
        await callback.message.answer(text, reply_markup=markup)
    else:
        await _replace(callback, reply)
    await callback.answer()


@router.callback_query(InviteAct.filter(F.action.in_({"main", "show"})))
async def show_code(callback: CallbackQuery, callback_data: InviteAct, user: User) -> None:
    def build(member):
        if callback_data.action == "main":
            return invite.main_link(member)
        return invite.team_link(member, callback_data.link)

    picture = await _for_company(user, callback_data.company, build)
    if isinstance(picture, invite.Picture):
        await _send_picture(callback.message, picture)
        await callback.answer()
    else:
        await callback.answer(_text(picture), show_alert=True)


@router.callback_query(InviteAct.filter(F.action == "stop"))
async def stop_link(callback: CallbackQuery, callback_data: InviteAct, user: User) -> None:
    @sync_to_async
    def run():
        member = invite.membership(user, callback_data.company)
        with translation.override(user.language):
            if member is None:
                return invite.no_access(), None
            answer, link = invite.stop(member, callback_data.link)
            edited = invite.edited_caption(member, link) if link is not None else None
            return answer, edited

    answer, edited = await run()
    if edited is not None:
        caption, markup = edited
        with suppress(TelegramBadRequest):  # the same caption already (a second tap)
            await callback.message.edit_caption(caption=caption, reply_markup=markup)
    await callback.answer(answer, show_alert=edited is None)


@router.callback_query(InviteNew.filter())
async def new_link(callback: CallbackQuery, callback_data: InviteNew, user: User) -> None:
    @sync_to_async
    def run():
        member = invite.membership(user, callback_data.company)
        with translation.override(user.language):
            if member is None:
                return invite.no_access()
            try:
                made = invite.new_link(member, callback_data)
            except (DomainError, PermissionDenied) as exc:
                return str(exc)
            if isinstance(made, tuple):
                return made
            return invite.team_link(member, made.pk)

    result = await run()
    if isinstance(result, invite.Picture):
        await _send_picture(callback.message, result)
        await callback.answer()
    elif isinstance(result, tuple):
        await _replace(callback, result)
        await callback.answer()
    else:
        await callback.answer(result, show_alert=True)


async def _send_picture(message: Message, picture: invite.Picture) -> None:
    photo = BufferedInputFile(picture.png, filename="invite.png")
    await message.answer_photo(photo, caption=picture.caption, reply_markup=picture.markup)


async def _replace(callback: CallbackQuery, reply) -> None:
    """Show `reply` in place of the tapped message (a new one if it can't be edited)."""
    text, markup = _message(reply)
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=markup)


def _message(reply) -> tuple:
    """A (text, keyboard) pair from a builder's answer, which may be just a text."""
    return reply if isinstance(reply, tuple) else (reply, None)


def _text(reply) -> str:
    return _message(reply)[0]


@sync_to_async
def _in_language(user: User, build, *args):
    with translation.override(user.language):
        return build(*args)


@sync_to_async
def _for_company(user: User, company_id: int, build):
    with translation.override(user.language):
        member = invite.membership(user, company_id)
        if member is None:
            return invite.no_access()
        return build(member)
