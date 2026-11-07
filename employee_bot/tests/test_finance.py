"""Expense claims in the employee bot (Package I, §10.2): `/expense` and a receipt photo
captioned `#xarajat`, the amount and note from the caption, category, paid from, confirm and
submit, with AI unavailable (manual entry always works) and the module switched off."""

import io
from decimal import Decimal

import pytest
from aiogram.methods import EditMessageText, SendMessage
from asgiref.sync import sync_to_async
from PIL import Image

from apps.finance import defaults, services
from apps.finance.callbacks import ClaimAction, ClaimButton
from apps.finance.models import Category, Claim, MoneyAccount
from bot.handlers.features import finance as flow
from tests import mocked_bot, updates

pytestmark = pytest.mark.django_db(transaction=True)


def jpeg_bytes() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 120, 60)).save(out, "JPEG")
    return out.getvalue()


def texts(bot) -> list[str]:
    return [r.text for r in bot.requests if isinstance(r, SendMessage | EditMessageText)]


def press(action: ClaimAction, value: int = 0) -> str:
    return ClaimButton(action=action, value=value).pack()


@sync_to_async
def books(company, features=("finance",)):
    company.features = list(features)
    company.save(update_fields=["features"])
    defaults.ensure(company)
    return Category.objects.get(company=company, system_code="transport").pk


@sync_to_async
def claims_of(member):
    return list(Claim.objects.filter(membership=member).prefetch_related("receipts"))


@sync_to_async
def give_cash(company, member, amount):
    owner_cash = MoneyAccount.objects.get(company=company, kind="cash")
    owner_cash.allow_negative = True
    owner_cash.save(update_fields=["allow_negative"])
    account = services.account_for_holder(company, member)
    from apps.finance import queries

    services.transfer(
        company,
        by=None,
        from_account=owner_cash,
        to_account=account,
        amount_out=Decimal(amount),
        occurred_on=queries.local_today(company),
        source=services.Source("finance.demo", member.pk, "cash"),
    )


def test_amounts_and_captions_are_read():
    assert flow.parse_amount("450000") == Decimal("450000")
    assert flow.parse_amount("450 000") == Decimal("450000")
    assert flow.parse_amount("450.000") == Decimal("450000")
    assert flow.parse_amount("1250,50") == Decimal("1250.50")
    assert flow.parse_amount("abc") is None
    assert flow.parse_amount("0") is None
    assert flow.split_caption("#xarajat 450 000 taksi") == (Decimal("450000"), "taksi")
    assert flow.split_caption("#Расход такси 30000") == (Decimal("30000"), "такси")
    assert flow.split_caption("#expense") == (None, "")


async def test_expense_command_typed_amount_category_submit(dp, bot, company, member):
    worker = await member.aregistered(company)
    transport = await books(company)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "/expense"))
    assert "Send a photo of the receipt" in texts(bot)[-1]
    await dp.feed_update(bot, updates.message(tg, "150 000 taksi"))
    assert "Pick a category" in texts(bot)[-1]
    await dp.feed_update(bot, updates.callback(tg, press(ClaimAction.CATEGORY, transport)))
    assert "Transport · 150" in texts(bot)[-1]  # nothing held: own money, straight to confirm
    assert "Paid from: My own money" in texts(bot)[-1]
    await dp.feed_update(bot, updates.callback(tg, press(ClaimAction.SUBMIT)))

    assert "Sent for approval" in texts(bot)[-1]
    [made] = await claims_of(worker)
    assert (made.amount, made.description, made.paid_from, made.via, made.status) == (
        Decimal("150000.00"),
        "taksi",
        "own_money",
        "bot",
        "submitted",
    )


@sync_to_async
def add_categories(company, count):
    """The owner's own expense categories, sorted after the defaults."""
    return [
        Category.objects.create(
            company=company, name=f"Own {index:02d}", kind=Category.Kind.EXPENSE, order=900 + index
        ).pk
        for index in range(count)
    ]


def buttons(bot) -> list[tuple[str, str]]:
    """(text, callback data) of the last message's inline keyboard."""
    last = [r for r in bot.requests if isinstance(r, SendMessage | EditMessageText)][-1]
    rows = last.reply_markup.inline_keyboard if last.reply_markup else []
    return [(button.text, button.callback_data) for row in rows for button in row]


async def test_every_category_is_reachable_a_page_at_a_time(dp, bot, company, member):
    """The picker used to show the first 12 categories only, so an owner's own never appeared."""
    worker = await member.aregistered(company)
    await books(company)
    own = await add_categories(company, 15)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "/expense"))
    await dp.feed_update(bot, updates.message(tg, "90 000 boshqa"))
    first = buttons(bot)
    picks = [data for _text, data in first if data.startswith(press(ClaimAction.CATEGORY)[:-1])]
    assert len(picks) == flow.CATEGORIES_PER_PAGE
    assert ("More ›", press(ClaimAction.PAGE, 1)) in first
    assert not any(text == "‹ Back" for text, _data in first)

    pages = 0
    while ("More ›", press(ClaimAction.PAGE, pages + 1)) in buttons(bot):
        pages += 1
        await dp.feed_update(bot, updates.callback(tg, press(ClaimAction.PAGE, pages)))
    last = buttons(bot)
    assert ("‹ Back", press(ClaimAction.PAGE, pages - 1)) in last
    assert ("Own 14", press(ClaimAction.CATEGORY, own[-1])) in last

    await dp.feed_update(bot, updates.callback(tg, press(ClaimAction.CATEGORY, own[-1])))
    await dp.feed_update(bot, updates.callback(tg, press(ClaimAction.SUBMIT)))
    [made] = await claims_of(worker)
    assert made.category_id == own[-1]


async def test_a_tagged_receipt_photo_becomes_a_claim_with_its_receipt(
    dp, bot, company, member, monkeypatch
):
    monkeypatch.setattr(mocked_bot, "FILE_CONTENT", jpeg_bytes())
    worker = await member.aregistered(company)
    transport = await books(company)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.photo(tg, caption="#xarajat 450 000 dorixonaga yetkazish"))
    assert "Pick a category" in texts(bot)[-1]
    await dp.feed_update(bot, updates.callback(tg, press(ClaimAction.CATEGORY, transport)))
    await dp.feed_update(bot, updates.callback(tg, press(ClaimAction.SUBMIT)))

    [made] = await claims_of(worker)
    assert made.amount == Decimal("450000.00")
    assert made.description == "dorixonaga yetkazish"
    assert len(made.receipts.all()) == 1


async def test_a_photo_without_an_amount_asks_for_it_and_cancel_stops(dp, bot, company, member):
    worker = await member.aregistered(company)
    await books(company)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.photo(tg, caption="#xarajat"))
    assert "How much did you spend" in texts(bot)[-1]
    await dp.feed_update(bot, updates.message(tg, "lots"))
    assert "doesn't look like an amount" in texts(bot)[-1]
    await dp.feed_update(bot, updates.message(tg, "/cancel"))
    assert "Cancelled" in texts(bot)[-1]
    assert await claims_of(worker) == []


async def test_company_cash_i_hold_is_offered_when_held(dp, bot, company, member):
    worker = await member.aregistered(company)
    transport = await books(company)
    await give_cash(company, worker, "500000")
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "/expense"))
    await dp.feed_update(bot, updates.message(tg, "200000"))
    await dp.feed_update(bot, updates.callback(tg, press(ClaimAction.CATEGORY, transport)))
    assert "Where did the money come from" in texts(bot)[-1]
    await dp.feed_update(bot, updates.callback(tg, press(ClaimAction.SOURCE, 1)))
    await dp.feed_update(bot, updates.callback(tg, press(ClaimAction.SUBMIT)))

    [made] = await claims_of(worker)
    assert made.paid_from == "held_cash"


async def test_the_flow_needs_the_finance_module(dp, bot, company, member):
    worker = await member.aregistered(company)
    await books(company, features=())
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "/expense"))

    assert "aren't switched on" in texts(bot)[-1]


async def test_works_without_ai(dp, bot, company, member):
    from apps.ai import receipts

    worker = await member.aregistered(company)
    assert receipts.start_scan(io.BytesIO(b""), by=worker, source="bot") is None


async def test_a_stale_button_says_so(dp, bot, company, member):
    worker = await member.aregistered(company)
    await books(company)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(ClaimAction.SUBMIT)))

    assert await claims_of(worker) == []


async def test_an_untagged_photo_is_still_the_tasks_routers(dp, bot, company, member):
    worker = await member.aregistered(company)
    await books(company)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.photo(tg, caption="Shelf after restock"))

    assert "No task is waiting for a photo" in texts(bot)[-1]
    assert await claims_of(worker) == []
