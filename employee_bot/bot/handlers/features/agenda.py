"""Employee bot, Package Q. Company calendar: event reminders for attendees.

Registered inside the member router, after the state-bound tasks and announcements routers
and before the home router (docs/PLAN-OWNER.md §10.2, rule 20).

Invitations, moves and reminders arrive through the inbox (their "I'll come / Can't come"
buttons are inbox actions). This router adds:

- `/calendar`: the person's next seven days (their events, company events, and the team
  dates their permissions allow: holidays, birthdays…).
- The answer buttons on an event card, and `/start ev_<id>` to open an event from a link.
"""

from contextlib import suppress
from datetime import date, timedelta

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.accounts.models import User
from apps.agenda import aggregate, bot_messages, queries, services
from apps.agenda.callbacks import EvAction, EvCallback
from apps.agenda.models import Event, EventAttendee
from apps.core.exceptions import DomainError
from apps.members.bot_messages import BotMessage
from apps.members.models import Membership
from apps.members.services import current_membership
from bot.deeplinks import register_start_param
from bot.filters.membership import IsRegistered

router = Router(name="feature_agenda")
# Members who finished registering; home asks the others to register first.
router.message.filter(IsRegistered())
router.callback_query.filter(IsRegistered())

ANSWERS = {
    EvAction.GOING: EventAttendee.Response.GOING,
    EvAction.DECLINE: EventAttendee.Response.DECLINED,
}


@router.message(Command("calendar"))
async def week(message: Message, membership: Membership) -> None:
    text, markup = await _week(membership)
    await message.answer(text, reply_markup=markup)


@router.callback_query(EvCallback.filter())
async def on_button(callback: CallbackQuery, callback_data: EvCallback, membership: Membership):
    if callback_data.action == EvAction.WEEK:
        text, markup = await _week(membership)
        await callback.message.answer(text, reply_markup=markup)
        await callback.answer()
        return
    event = await _event(membership, callback_data.event_id)
    if event is None:
        await callback.answer(bot_messages.cancelled_title_generic(), show_alert=True)
        return
    try:
        text, markup, note = await _answer(membership, event, ANSWERS[callback_data.action])
    except (PermissionDenied, DomainError) as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer(note)


async def open_from_link(message: Message, payload: str, *, user: User, state: FSMContext):
    """`/start ev_12`: the event card, when the person may see it."""
    membership = await sync_to_async(current_membership)(user)
    if (
        membership is None
        or membership.status != Membership.Status.APPROVED
        or not membership.is_onboarded
        or not payload.isdigit()
    ):
        await message.answer(bot_messages.cancelled_title_generic())
        return
    event = await _event(membership, int(payload))
    if event is None:
        await message.answer(bot_messages.cancelled_title_generic())
        return
    text, markup = await _card(membership, event)
    await message.answer(text, reply_markup=markup)


register_start_param("ev_", open_from_link)


@sync_to_async
def _event(membership: Membership, event_id: int) -> Event | None:
    return queries.get_event(membership, event_id)


@sync_to_async
def _card(membership: Membership, event: Event) -> BotMessage:
    return bot_messages.event_card(event, invite=queries.my_invite(membership, event))


@sync_to_async
def _answer(membership: Membership, event: Event, response: str):
    invite = services.respond(event, by=membership, response=response)
    event.refresh_from_db()
    text, markup = bot_messages.event_card(event, invite=invite)
    return text, markup, bot_messages.answered(invite.response)


@sync_to_async
def _week(membership: Membership) -> BotMessage:
    company = membership.company
    today = queries.local_day(timezone.now(), company)
    last = today + timedelta(days=6)
    items = aggregate.items(membership, today, last)
    responses = dict(
        EventAttendee.objects.filter(membership=membership).values_list("event_id", "response")
    )
    marks = {
        EventAttendee.Response.GOING: "",
        EventAttendee.Response.DECLINED: "",
        EventAttendee.Response.PENDING: "",
    }
    days: dict = {}
    for item in items:
        first = item["start"][:10]
        last_day = (item["end"] or item["start"])[:10]
        if not item["all_day"]:
            last_day = first
        label = item["title"]
        if not item["all_day"]:
            label = f"{item['start'][11:16]} {label}"
        if item["kind"] == "agenda.event":
            event_id = int(item["id"].split(":", 1)[1].split("-", 1)[0])
            if responses.get(event_id) == EventAttendee.Response.DECLINED:
                continue
            label = marks.get(responses.get(event_id), "") + label
        day = max(first, today.isoformat())
        while day <= min(last_day, last.isoformat()):
            days.setdefault(day, []).append(label)
            day = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    lines = [(date.fromisoformat(day), entries) for day, entries in sorted(days.items())]
    return bot_messages.week(lines, today=today)
