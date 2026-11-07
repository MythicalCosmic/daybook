"""Employee bot, package Q2. The question of the day: answering it with the message's buttons
(docs/PLAN-LEARNING.md §9.2).

Registered inside the member router, after the state-bound tasks and announcements routers
and before the home router (docs/PLAN-OWNER.md §10.2, rule 20).

- One-answer and true-or-false questions: one tap answers; the message becomes the result.
- Several right answers: each tap chooses or unchooses an option (the chosen letters show in
  the message), "Answer" sends them.
- The buttons carry only the question's id and an option id. A question that isn't the
  person's (a forged button), of a day that is over, or already answered changes nothing: the
  person gets a short answer to the tap.
"""

from contextlib import suppress
from dataclasses import dataclass

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from asgiref.sync import sync_to_async
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.learning import bot_messages, conf, daily
from apps.learning.callbacks import FALSE, TRUE, DailyAction, DailyCallback
from apps.learning.models import DailyQuestion, Question
from apps.members.bot_messages import BotMessage
from apps.members.models import Membership
from bot.filters.membership import IsRegistered

router = Router(name="feature_learning")
# Members who finished registering; home asks the others to register first.
router.callback_query.filter(IsRegistered())


@dataclass(frozen=True)
class Reply:
    """How the bot answers a tap: a short note (an alert when `alert`) and the message's new
    text and buttons, if it changes."""

    note: str
    alert: bool = False
    message: BotMessage | None = None


@router.callback_query(DailyCallback.filter())
async def on_daily(callback: CallbackQuery, callback_data: DailyCallback, membership: Membership):
    reply = await sync_to_async(press)(membership, callback_data)
    if reply.message is not None and callback.message is not None:
        text, markup = reply.message
        with suppress(TelegramBadRequest):  # unchanged, or too old to edit
            await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer(reply.note[:200], show_alert=reply.alert)


def press(member: Membership, data: DailyCallback) -> Reply:
    """What a tap on a question-of-the-day button does (no async: it runs in a thread)."""
    found = (
        DailyQuestion.objects.filter(membership=member, pk=data.daily_id)
        .select_related("question", "membership__company", "membership__user")
        .first()
    )
    if found is None:  # someone else's, or gone: nothing happens
        return Reply(_("This question isn't yours."), alert=True)
    if not conf.is_on(member.company):
        return Reply(_("Training isn't switched on for this company."), alert=True)
    if found.answered_at is not None:
        message = bot_messages.daily_result(
            found, points=daily.points_of(found), streak=daily.streak_of(member)
        )
        return Reply(_("You've answered it already."), message=message)
    kind = found.question.kind
    try:
        if kind == Question.Kind.MULTI and data.action == DailyAction.PICK:
            daily.toggle(found, member, data.option)
            found.refresh_from_db()
            return Reply("", message=bot_messages.daily_message(found))
        if kind == Question.Kind.MULTI:
            outcome = daily.answer(found, member, found.answer, in_bot=True)
        elif kind == Question.Kind.SINGLE and data.action == DailyAction.PICK:
            outcome = daily.answer(found, member, {"option": data.option}, in_bot=True)
        elif kind == Question.Kind.TRUE_FALSE and data.option in (TRUE, FALSE):
            outcome = daily.answer(found, member, {"value": data.option == TRUE}, in_bot=True)
        else:
            return Reply(_("This one is answered in the app."), alert=True)
    except DomainError as exc:
        return Reply(str(exc), alert=True)
    found.refresh_from_db()
    message = bot_messages.daily_result(found, points=outcome.points, streak=outcome.streak)
    return Reply(_("Right!") if outcome.correct else _("Not quite."), message=message)
