"""The one-off "check your details" survey after the launch (apps.members.profile_fix):
branch → department → job title → save. Works for approved and waiting people alike."""

from contextlib import suppress

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery
from asgiref.sync import sync_to_async

from apps.accounts.models import User
from apps.members import profile_fix
from apps.members.callbacks import ProfileFix

router = Router(name="profile_fix")
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)


@sync_to_async
def _next(user: User, data: ProfileFix) -> tuple[str, object] | None:
    member = profile_fix.member_for(user)
    if member is None:
        return None
    company = member.company
    if data.step == "redo":
        return profile_fix.INTRO, profile_fix.branch_keyboard(company)
    if data.step == "b":
        return profile_fix.ASK_DEPARTMENT, profile_fix.department_keyboard(company, data.b)
    if data.step == "d":
        return profile_fix.ASK_TITLE, profile_fix.title_keyboard(company, data.b, data.d)
    if data.step == "p":
        text = profile_fix.summary(company, data.b, data.d, data.p)
        return text, profile_fix.confirm_keyboard(data.b, data.d, data.p)
    if data.step == "ok":
        if not profile_fix.apply(member, b=data.b, d=data.d, p=data.p):
            return profile_fix.INTRO, profile_fix.branch_keyboard(company)
        return (
            f"{profile_fix.SAVED}\n\n{profile_fix.summary(company, data.b, data.d, data.p)}",
            None,
        )
    return None


@router.callback_query(ProfileFix.filter())
async def step(callback: CallbackQuery, callback_data: ProfileFix, user: User) -> None:
    result = await _next(user, callback_data)
    if result is None:
        await callback.answer(profile_fix.GONE, show_alert=True)
        return
    text, markup = result
    with suppress(TelegramAPIError):
        await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()
