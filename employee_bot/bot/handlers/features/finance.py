"""Employee bot, Package I. Finance: expense claims from `/expense` or a receipt photo
captioned `#xarajat`, `#расход` or `#expense` (docs/PLAN-OWNER.md §10.2).

    photo "#xarajat 450000 taksi" → category → paid from (my money / cash I hold) → confirm
    → submitted for approval, or recorded at once below the approval threshold

The amount and a note may come in the caption ("#xarajat 450 000 taksi"); otherwise the bot
asks. AI receipt reading (`apps.ai.receipts.start_scan`) only prefills when it is available;
without it everything is typed, so the flow always works. Approvals, decisions and bill
reminders arrive as inbox notifications with the inbox's generic buttons
(`apps.finance.claims`, `apps.finance.reminders`).

Photo handlers here are caption-filtered or bound to this flow's own states, never a bare
`F.photo`, so a task's proof photo always reaches the tasks router (rule 20). The handlers
live in a child router: the feature router's own filters still gate them, and anything
registered on the feature router itself is offered the update first.

Registered inside the member router, after the state-bound tasks and announcements routers
and before the home router (docs/PLAN-OWNER.md §10.2, rule 20).
"""

import re
from decimal import Decimal, InvalidOperation

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from asgiref.sync import sync_to_async
from django.core.files.base import ContentFile

from apps.core.exceptions import DomainError
from apps.finance import bot_messages
from apps.finance.callbacks import ClaimAction, ClaimButton
from apps.members.models import Membership
from bot.filters.membership import IsRegistered

router = Router(name="feature_finance")
# Members who finished registering; home asks the others to register first.
router.message.filter(IsRegistered())
router.callback_query.filter(IsRegistered())
flow = Router(name="finance_claims")
router.include_router(flow)

TAGS = ("#xarajat", "#расход", "#expense")
CANCEL_WORDS = frozenset({"/cancel", "cancel", "bekor", "bekor qilish", "отмена", "отменить"})
MAX_PHOTOS = 5
MAX_CATEGORIES = 12
THOUSANDS = re.compile(r"^\d{1,3}([.,]\d{3})+$")
PLAIN = re.compile(r"^\d+([.,]\d{1,2})?$")
NUMBER = re.compile(r"\d[\d .,]*\d|\d")


class ClaimFlow(StatesGroup):
    amount = State()  # waiting for the amount (a receipt photo is welcome too)
    category = State()
    source = State()
    confirm = State()


def tagged(message: Message) -> bool:
    caption = (message.caption or "").strip().lower()
    return any(caption.startswith(tag) for tag in TAGS)


def parse_amount(text: str) -> Decimal | None:
    """ "450000", "450 000", "450.000" or "1250,50" as so‘m; None for anything else."""
    value = (text or "").strip().replace(" ", "").replace(" ", "")
    if THOUSANDS.match(value):
        value = value.replace(".", "").replace(",", "")
    elif PLAIN.match(value):
        value = value.replace(",", ".")
    else:
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None
    return amount if amount > 0 else None


def split_caption(caption: str) -> tuple[Decimal | None, str]:
    """The amount and the note in "#xarajat 450 000 taksi" (either may be missing)."""
    text = (caption or "").strip()
    for tag in TAGS:
        if text.lower().startswith(tag):
            text = text[len(tag) :].strip()
            break
    match = NUMBER.search(text)
    if match is None:
        return None, text[:300]
    amount = parse_amount(match.group())
    if amount is None:
        return None, text[:300]
    rest = (text[: match.start()] + " " + text[match.end() :]).strip()
    return amount, " ".join(rest.split())[:300]


# Starting -------------------------------------------------------------------------------------


@flow.message(Command("expense"))
async def start(message: Message, membership: Membership, state: FSMContext) -> None:
    if not await _can_claim(membership):
        await message.answer(bot_messages.claim_off())
        return
    await state.set_state(ClaimFlow.amount)
    await state.set_data({"photos": []})
    await message.answer(bot_messages.claim_start())


@flow.message(F.photo, F.func(tagged))
async def tagged_photo(message: Message, membership: Membership, state: FSMContext) -> None:
    if not await _can_claim(membership):
        await message.answer(bot_messages.claim_off())
        return
    amount, note = split_caption(message.caption or "")
    await state.set_data({"photos": [message.photo[-1].file_id], "description": note})
    if amount is None:
        await state.set_state(ClaimFlow.amount)
        await message.answer(bot_messages.claim_ask_amount())
        return
    await state.update_data(amount=str(amount))
    await _ask_category(message, membership, state)


# Steps ----------------------------------------------------------------------------------------


@flow.message(ClaimFlow.amount, F.photo)
async def photo_for_amount(message: Message, membership: Membership, state: FSMContext) -> None:
    data = await state.get_data()
    photos = [*data.get("photos", []), message.photo[-1].file_id][:MAX_PHOTOS]
    amount, note = split_caption(message.caption or "")
    await state.update_data(photos=photos, description=note or data.get("description", ""))
    if amount is None:
        await message.answer(bot_messages.claim_ask_amount())
        return
    await state.update_data(amount=str(amount))
    await _ask_category(message, membership, state)


@flow.message(ClaimFlow.amount, F.text)
async def typed_amount(message: Message, membership: Membership, state: FSMContext) -> None:
    if message.text.strip().lower() in CANCEL_WORDS:
        await state.clear()
        await message.answer(bot_messages.claim_cancelled())
        return
    amount, note = split_caption(message.text)
    if amount is None:
        await message.answer(bot_messages.claim_bad_amount())
        return
    data = await state.get_data()
    await state.update_data(amount=str(amount), description=note or data.get("description", ""))
    if data.get("category"):
        await _confirm(message, membership, state)
        return
    await _ask_category(message, membership, state)


@flow.callback_query(ClaimFlow.category, ClaimButton.filter(F.action == ClaimAction.CATEGORY))
async def picked_category(
    query: CallbackQuery, callback_data: ClaimButton, membership: Membership, state: FSMContext
) -> None:
    name = await _category_name(membership, callback_data.value)
    if name is None:
        await query.answer(bot_messages.claim_no_categories(), show_alert=True)
        return
    await query.answer()
    await state.update_data(category=callback_data.value, category_name=name)
    held = await _held(membership)
    if held is None:
        await state.update_data(paid_from="own_money")
        await _confirm(query.message, membership, state, edit=True)
        return
    await state.set_state(ClaimFlow.source)
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [_button(bot_messages.claim_own_money(), ClaimAction.SOURCE, 0)],
            [_button(bot_messages.claim_held_cash(held), ClaimAction.SOURCE, 1)],
        ]
    )
    await query.message.edit_text(bot_messages.claim_ask_source(), reply_markup=markup)


@flow.callback_query(ClaimFlow.source, ClaimButton.filter(F.action == ClaimAction.SOURCE))
async def picked_source(
    query: CallbackQuery, callback_data: ClaimButton, membership: Membership, state: FSMContext
) -> None:
    await query.answer()
    await state.update_data(paid_from="held_cash" if callback_data.value == 1 else "own_money")
    await _confirm(query.message, membership, state, edit=True)


@flow.callback_query(ClaimFlow.confirm, ClaimButton.filter(F.action == ClaimAction.AMOUNT))
async def change_amount(query: CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    await state.set_state(ClaimFlow.amount)
    await query.message.edit_text(bot_messages.claim_ask_amount())


@flow.callback_query(ClaimFlow.confirm, ClaimButton.filter(F.action == ClaimAction.CHANGE_CATEGORY))
async def change_category(query: CallbackQuery, membership: Membership, state: FSMContext) -> None:
    await query.answer()
    await _ask_category(query.message, membership, state, edit=True)


@flow.callback_query(ClaimButton.filter(F.action == ClaimAction.CANCEL))
async def cancel(query: CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    await state.clear()
    await query.message.edit_text(bot_messages.claim_cancelled())


@flow.callback_query(ClaimFlow.confirm, ClaimButton.filter(F.action == ClaimAction.SUBMIT))
async def submit(query: CallbackQuery, membership: Membership, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    photos = []
    for file_id in data.get("photos", [])[:MAX_PHOTOS]:
        downloaded = await bot.download(file_id)
        photos.append(ContentFile(downloaded.getvalue(), name="receipt.jpg"))
    try:
        text = await _submit(membership, data, photos)
    except DomainError as error:
        await query.answer(str(error), show_alert=True)
        await state.set_state(ClaimFlow.confirm)
        await state.set_data(data)
        return
    await query.answer()
    await query.message.edit_text(text)


@flow.callback_query(ClaimButton.filter())
async def stale_button(query: CallbackQuery) -> None:
    """A button of a flow that is over (sent, cancelled, or the bot restarted)."""
    await query.answer(bot_messages.claim_expired(), show_alert=True)


# Helpers --------------------------------------------------------------------------------------


def _button(text: str, action: ClaimAction, value: int = 0) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text, callback_data=ClaimButton(action=action, value=value).pack()
    )


async def _ask_category(message: Message, membership: Membership, state: FSMContext, *, edit=False):
    rows = await _categories(membership)
    if not rows:
        await state.clear()
        await message.answer(bot_messages.claim_no_categories())
        return
    await state.set_state(ClaimFlow.category)
    buttons = [_button(name, ClaimAction.CATEGORY, pk) for pk, name in rows]
    keyboard = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    keyboard.append([_button(bot_messages.claim_button_cancel(), ClaimAction.CANCEL)])
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    if edit:
        await message.edit_text(bot_messages.claim_ask_category(), reply_markup=markup)
    else:
        await message.answer(bot_messages.claim_ask_category(), reply_markup=markup)


async def _confirm(message: Message, membership: Membership, state: FSMContext, *, edit=False):
    data = await state.get_data()
    await state.set_state(ClaimFlow.confirm)
    text = await _summary(membership, data)
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [_button(bot_messages.claim_button_submit(), ClaimAction.SUBMIT)],
            [
                _button(bot_messages.claim_button_amount(), ClaimAction.AMOUNT),
                _button(bot_messages.claim_button_category(), ClaimAction.CHANGE_CATEGORY),
            ],
            [_button(bot_messages.claim_button_cancel(), ClaimAction.CANCEL)],
        ]
    )
    if edit:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


@sync_to_async
def _can_claim(membership: Membership) -> bool:
    from apps.members.permissions import Perm

    return membership.company.has_feature("finance") and membership.has_perm(Perm.FINANCE_CLAIM)


@sync_to_async
def _categories(membership: Membership) -> list[tuple[int, str]]:
    from apps.finance import claims

    rows = claims.expense_categories(membership.company)[:MAX_CATEGORIES]
    return [
        (row.pk, row.name if row.parent_id is None else f"{row.parent.name} · {row.name}")
        for row in rows
    ]


@sync_to_async
def _category_name(membership: Membership, pk: int) -> str | None:
    from apps.finance import claims

    row = claims.expense_categories(membership.company).filter(pk=pk).first()
    return row.name if row is not None else None


@sync_to_async
def _held(membership: Membership) -> str | None:
    """What the person holds of the company's cash, formatted; None when nothing."""
    from apps.finance import claims

    base = membership.company.base_currency
    held = sum(
        (a.balance for a in claims.held_accounts(membership) if a.currency == base), Decimal(0)
    )
    if held <= 0:
        return None
    return bot_messages.money(held, base, membership.user.language)


@sync_to_async
def _summary(membership: Membership, data: dict) -> str:
    from apps.finance.models import Claim

    company = membership.company
    source = str(Claim.PaidFrom(data.get("paid_from") or Claim.PaidFrom.OWN_MONEY).label)
    return bot_messages.claim_summary(
        data.get("category_name", ""),
        bot_messages.money(
            Decimal(data["amount"]), company.base_currency, membership.user.language
        ),
        source,
        data.get("description", ""),
    )


@sync_to_async
def _submit(membership: Membership, data: dict, photos: list) -> str:
    from apps.finance import claims
    from apps.finance.models import Claim

    category = claims.expense_categories(membership.company).filter(pk=data.get("category")).first()
    if category is None or not data.get("amount"):
        raise DomainError(bot_messages.claim_expired())
    claim = claims.submit_claim(
        membership.company,
        by=membership,
        amount=Decimal(data["amount"]),
        category=category,
        spent_on=_today(membership),
        paid_from=data.get("paid_from") or Claim.PaidFrom.OWN_MONEY,
        description=data.get("description", ""),
        receipt_files=photos,
        via=Claim.Via.BOT,
    )
    if claim.status == Claim.Status.SUBMITTED:
        return bot_messages.claim_sent()
    return bot_messages.claim_recorded()


def _today(membership: Membership):
    from apps.finance import queries

    return queries.local_today(membership.company)
