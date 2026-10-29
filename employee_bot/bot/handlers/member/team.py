"""\"My team\": a department head's people, their work and its history (apps.members.departments),
and the proof photo of any task one may open."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from asgiref.sync import sync_to_async
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.members.bot_messages import MENU_MY_TEAM
from apps.members.departments import heads_any, manages
from apps.members.models import Membership
from apps.tasks import bot_messages as task_messages
from apps.tasks.callbacks import TaskAction, TaskCallback, TeamCallback
from bot.filters.menu import MenuButton
from bot.handlers.member import cards

router = Router(name="member_team")


@router.message(MenuButton(MENU_MY_TEAM))
async def show_team(message: Message, membership: Membership, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _team(membership, 0)
    await message.answer(text, reply_markup=markup)


@router.callback_query(TeamCallback.filter())
async def team_page(callback: CallbackQuery, callback_data: TeamCallback, membership: Membership):
    text, markup = await _team(membership, callback_data.member_id)
    await callback.message.answer(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(TaskCallback.filter(F.action == TaskAction.PHOTO))
async def show_photo(callback: CallbackQuery, callback_data: TaskCallback, membership: Membership):
    found = await _photo(membership, callback_data.task_id)
    if found is None:
        await callback.answer(_("There's no photo to show."), show_alert=True)
        return
    data, caption = found
    await callback.message.answer_photo(
        BufferedInputFile(data, filename="proof.jpg"), caption=caption
    )
    await callback.answer()


@sync_to_async
def _team(membership: Membership, member_id: int):
    if not heads_any(membership):
        return _("You don't head a department."), None
    if not member_id:
        return task_messages.team_summary(membership)
    person = (
        Membership.objects.select_related("company", "position", "user")
        .filter(pk=member_id, company_id=membership.company_id)
        .first()
    )
    if person is None or not manages(membership, person):
        return _("This person isn't in your departments."), None
    return task_messages.team_person(membership, person)


@sync_to_async
def _photo(membership: Membership, task_id: int):
    """The proof photo of a task the member may see, with a short caption."""
    task = cards.visible(membership).filter(pk=task_id).first()
    if task is None or not task.proof_photo:
        return None
    with task.proof_photo.open("rb") as file:
        data = file.read()
    caption = task_messages.display_title(task)
    if task.completed_at:
        when = timezone.localtime(task.completed_at).strftime("%d.%m %H:%M")
        caption = f"{caption} — {task.assignee}, {when}"
    return data, caption[:1000]
