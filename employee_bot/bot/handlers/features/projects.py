"""Employee bot, Package T. Projects.

- "You were added to project X" and the weekly nudge reach people as inbox notifications
  (`apps.projects.services` / `jobs`); the nudge's buttons post a one-tap update through the
  generic inbox handler.
- `/start upd_<project id>` (the link in the nudge) opens a short conversation for a fuller
  update: how it's going (buttons), then a line or two, or skip.

Registered inside the member router, after the state-bound tasks and announcements routers
and before the home router (docs/PLAN-OWNER.md §10.2, rule 20). The deep link runs before the
member gate, so it finds the person's membership in the project's company itself.
"""

from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async
from django.core.exceptions import PermissionDenied

from apps.accounts.models import User
from apps.core.exceptions import DomainError
from apps.members.models import Membership
from apps.projects import bot_messages, queries, services
from apps.projects.callbacks import ProjectUpdateCallback, UpdateStep
from apps.projects.models import Health, Project
from bot.deeplinks import register_start_param
from bot.filters.membership import IsRegistered

router = Router(name="feature_projects")
# Members who finished registering; home asks the others to register first.
router.message.filter(IsRegistered())
router.callback_query.filter(IsRegistered())


class PostUpdate(StatesGroup):
    text = State()


def _project_for(user: User, project_id: int) -> tuple[Project, Membership] | None:
    """The project and `user`'s approved membership in its company, if they may post on it."""
    project = Project.objects.select_related("company").filter(pk=project_id).first()
    if project is None or project.archived_at is not None:
        return None
    membership = (
        Membership.objects.select_related("company", "user", "role")
        .filter(company=project.company, user=user, status=Membership.Status.APPROVED)
        .first()
    )
    if membership is None or not queries.can_view(project, membership):
        return None
    return project, membership


@sync_to_async
def _start(user: User, project_id: int):
    found = _project_for(user, project_id)
    if found is None:
        return None, bot_messages.not_found()
    project, membership = found
    if not queries.can_post_update(project, membership):
        return None, bot_messages.not_allowed()
    return bot_messages.ask_health(project), None


async def open_update(message: Message, payload: str, *, user: User, state: FSMContext) -> None:
    """`/start upd_<project id>`: start the update conversation."""
    if not payload.isdigit():
        await message.answer(bot_messages.not_found())
        return
    await state.clear()
    reply, problem = await _start(user, int(payload))
    if problem:
        await message.answer(problem)
        return
    text, markup = reply
    await message.answer(text, reply_markup=markup)


register_start_param("upd_", open_update)


async def _edit(callback: CallbackQuery, text: str, markup=None) -> None:
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=markup)


@router.callback_query(ProjectUpdateCallback.filter(F.step == UpdateStep.STOP))
async def stop(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _edit(callback, bot_messages.cancelled())
    await callback.answer()


@sync_to_async
def _ask_text(user: User, project_id: int, health: str):
    found = _project_for(user, project_id)
    if found is None:
        return None
    return bot_messages.ask_text(found[0], health)


@router.callback_query(ProjectUpdateCallback.filter(F.step == UpdateStep.HEALTH))
async def picked_health(
    callback: CallbackQuery, callback_data: ProjectUpdateCallback, user: User, state: FSMContext
) -> None:
    if callback_data.health not in Health.values:
        await callback.answer()
        return
    reply = await _ask_text(user, callback_data.project_id, callback_data.health)
    if reply is None:
        await callback.answer(bot_messages.not_found(), show_alert=True)
        return
    await state.set_state(PostUpdate.text)
    await state.update_data(project_id=callback_data.project_id, health=callback_data.health)
    await _edit(callback, *reply)
    await callback.answer()


@sync_to_async
def _post(user: User, project_id: int, health: str, text: str):
    found = _project_for(user, project_id)
    if found is None:
        return None, bot_messages.not_found()
    project, membership = found
    try:
        update = services.post_update(project, by=membership, health=health, text=text)
    except PermissionDenied:
        return None, bot_messages.not_allowed()
    except DomainError as exc:
        return None, str(exc)
    return bot_messages.posted(project, update), None


@router.callback_query(ProjectUpdateCallback.filter(F.step == UpdateStep.SKIP))
async def skip_text(
    callback: CallbackQuery, callback_data: ProjectUpdateCallback, user: User, state: FSMContext
) -> None:
    await state.clear()
    reply, problem = await _post(user, callback_data.project_id, callback_data.health, "")
    if problem:
        await callback.answer(problem, show_alert=True)
        return
    await _edit(callback, *reply)
    await callback.answer()


@router.message(PostUpdate.text, F.text)
async def got_text(message: Message, user: User, state: FSMContext) -> None:
    data = await state.get_data()
    if len(message.text) > services.MAX_UPDATE_LENGTH:
        await message.answer(bot_messages.too_long())
        return
    await state.clear()
    reply, problem = await _post(
        user, data.get("project_id", 0), data.get("health", ""), message.text
    )
    if problem:
        await message.answer(problem)
        return
    text, markup = reply
    await message.answer(text, reply_markup=markup)
