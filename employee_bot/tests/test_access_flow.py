import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText
from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.members import services
from apps.members.callbacks import JoinAction, JoinDecision
from apps.members.models import Membership
from tests import updates

# Handlers reach the ORM from worker threads, so test data must really be committed.
pytestmark = pytest.mark.django_db(transaction=True)


async def get_membership(company, telegram_id) -> Membership:
    return await Membership.objects.aget(company=company, user__telegram_id=telegram_id)


async def test_invite_link_opens_a_request_and_points_to_account_creation(
    dp, bot, company, settings
):
    settings.EMPLOYEE_MINIAPP_URL = "https://app.example.com"
    ali = updates.tg_user(501)

    await dp.feed_update(bot, updates.message(ali, f"/start {company.invite_start_param}"))

    membership = await get_membership(company, 501)
    assert membership.status == Membership.Status.PENDING
    reply = bot.requests[-1]
    assert "You're joining" in reply.text
    assert reply.reply_markup.inline_keyboard[0][0].web_app.url == "https://app.example.com"


async def test_approvers_hear_once_the_account_is_created(dp, bot, company, member, sent_messages):
    manager = await member.acreate(company, "Manager")
    ali = updates.tg_user(502)
    await dp.feed_update(bot, updates.message(ali, f"/start {company.invite_start_param}"))
    assert sent_messages == []  # nothing to decide on yet

    membership = await Membership.objects.select_related("user").aget(user__telegram_id=502)
    membership.user.phone = "+998901234567"
    await membership.user.asave()
    await sync_to_async(services.complete_onboarding)(
        membership, first_name="Ali", last_name="Valiyev", position_id=None
    )

    [message] = sent_messages
    assert message["chat_id"] == manager.user.telegram_id
    assert "Ali Valiyev" in message["text"]
    assert "+998901234567" in message["text"]
    buttons = message["reply_markup"]["inline_keyboard"][0]
    assert [b["text"] for b in buttons] == ["✅ Approve", "❌ Reject"]


async def test_invalid_invite_link_is_explained(dp, bot, db):
    await dp.feed_update(bot, updates.message(updates.tg_user(503), "/start c_nope"))

    assert "invalid or has expired" in bot.sent_texts()[-1]


async def test_plain_start_without_membership_asks_for_invite_link(dp, bot, db):
    await dp.feed_update(bot, updates.message(updates.tg_user(504), "/start"))

    assert "open the invite link" in bot.sent_texts()[-1]


async def test_gate_sends_new_people_to_account_creation(dp, bot, company):
    ali = updates.tg_user(505)
    await dp.feed_update(bot, updates.message(ali, f"/start {company.invite_start_param}"))

    await dp.feed_update(bot, updates.message(ali, "show me my tasks"))

    assert "You're joining" in bot.sent_texts()[-1]


async def test_gate_blocks_people_waiting_for_approval(dp, bot, company, member):
    waiting = await member.acreate(
        company, status=Membership.Status.PENDING, onboarded_at=timezone.now()
    )

    await dp.feed_update(
        bot, updates.message(updates.tg_user(waiting.user.telegram_id), "show me my tasks")
    )

    assert "waiting for approval" in bot.sent_texts()[-1]


async def test_gate_stays_silent_for_blocked_member(dp, bot, company, member):
    blocked = await member.acreate(company, status=Membership.Status.BLOCKED)
    sent_before = len(bot.sent_texts())

    await dp.feed_update(bot, updates.message(updates.tg_user(blocked.user.telegram_id), "hi"))

    assert len(bot.sent_texts()) == sent_before


async def test_gate_lets_registered_member_through(dp, bot, company, member):
    employee = await member.acreate(company, onboarded_at=timezone.now())

    await dp.feed_update(bot, updates.message(updates.tg_user(employee.user.telegram_id), "hi"))

    assert "You're a member of" in bot.sent_texts()[-1]


async def test_gate_ignores_group_chats(dp, bot, company, member):
    employee = await member.acreate(company)

    await dp.feed_update(
        bot, updates.message(updates.tg_user(employee.user.telegram_id), "hi", chat_type="group")
    )

    assert bot.sent_texts() == []


async def test_manager_approves_from_the_button(dp, bot, company, member, sent_messages):
    manager = await member.acreate(company, "Manager")
    ali = updates.tg_user(506)
    await dp.feed_update(bot, updates.message(ali, f"/start {company.invite_start_param}"))
    request = await get_membership(company, 506)
    data = JoinDecision(action=JoinAction.APPROVE, membership_id=request.pk).pack()

    await dp.feed_update(bot, updates.callback(updates.tg_user(manager.user.telegram_id), data))

    request = await get_membership(company, 506)
    assert request.status == Membership.Status.APPROVED
    edit = next(r for r in bot.requests if isinstance(r, EditMessageText))
    assert "Approved by" in edit.text
    assert edit.reply_markup is None
    assert "was approved" in sent_messages[-1]["text"]
    assert sent_messages[-1]["chat_id"] == 506


async def test_employee_cannot_approve_from_the_button(dp, bot, company, member):
    employee = await member.acreate(company)
    ali = updates.tg_user(507)
    await dp.feed_update(bot, updates.message(ali, f"/start {company.invite_start_param}"))
    request = await get_membership(company, 507)
    data = JoinDecision(action=JoinAction.APPROVE, membership_id=request.pk).pack()

    await dp.feed_update(bot, updates.callback(updates.tg_user(employee.user.telegram_id), data))

    request = await get_membership(company, 507)
    assert request.status == Membership.Status.PENDING
    answer = next(r for r in bot.requests if isinstance(r, AnswerCallbackQuery))
    assert answer.show_alert
    assert "permission" in answer.text


async def test_second_approver_sees_who_decided_first(dp, bot, company, member):
    first = await member.acreate(company, "Manager")
    second = await member.acreate(company, "Owner")
    await dp.feed_update(
        bot, updates.message(updates.tg_user(508), f"/start {company.invite_start_param}")
    )
    request = await get_membership(company, 508)
    approve = JoinDecision(action=JoinAction.APPROVE, membership_id=request.pk).pack()
    reject = JoinDecision(action=JoinAction.REJECT, membership_id=request.pk).pack()
    await dp.feed_update(bot, updates.callback(updates.tg_user(first.user.telegram_id), approve))

    await dp.feed_update(bot, updates.callback(updates.tg_user(second.user.telegram_id), reject))

    request = await get_membership(company, 508)
    assert request.status == Membership.Status.APPROVED
    answer = [r for r in bot.requests if isinstance(r, AnswerCallbackQuery)][-1]
    assert "already approved" in answer.text
