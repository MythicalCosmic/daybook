from datetime import datetime

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import (
    Chat,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    Update,
    WebAppData,
)
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
    await dp.feed_update(bot, updates.pick_language(ali))  # a new person picks first

    membership = await get_membership(company, 501)
    assert membership.status == Membership.Status.PENDING
    # The last message (the chat's menu button gets its label after it: test_menu_button.py).
    reply = sent(bot)[-1]
    assert "You're joining" in reply.text
    assert reply.reply_markup.inline_keyboard[0][0].web_app.url == "https://app.example.com"


async def test_approvers_hear_once_the_account_is_created(dp, bot, company, member, sent_messages):
    manager = await member.acreate(company, "Manager")
    ali = updates.tg_user(502)
    await dp.feed_update(bot, updates.message(ali, f"/start {company.invite_start_param}"))
    await dp.feed_update(bot, updates.pick_language(ali))  # a new person picks first
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
    assert [b["text"] for b in buttons] == ["Approve", "Reject"]


async def test_invalid_invite_link_is_explained(dp, bot, db):
    nobody = updates.tg_user(503)
    await dp.feed_update(bot, updates.message(nobody, "/start c_nope"))

    # Someone new is answered in Uzbek.
    assert "taklif havolasi noto‘g‘ri" in bot.sent_texts()[-1]


async def test_plain_start_without_membership_asks_for_invite_link(dp, bot, db):
    nobody = updates.tg_user(504)
    await dp.feed_update(bot, updates.message(nobody, "/start"))
    await dp.feed_update(bot, updates.pick_language(nobody))

    assert "open the invite link" in bot.sent_texts()[-1]


async def test_gate_sends_new_people_to_account_creation(dp, bot, company):
    ali = updates.tg_user(505)
    await dp.feed_update(bot, updates.message(ali, f"/start {company.invite_start_param}"))
    await dp.feed_update(bot, updates.pick_language(ali))  # a new person picks first

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
    await dp.feed_update(bot, updates.pick_language(ali))  # a new person picks first
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
    await dp.feed_update(bot, updates.pick_language(ali))  # a new person picks first
    request = await get_membership(company, 507)
    data = JoinDecision(action=JoinAction.APPROVE, membership_id=request.pk).pack()

    await dp.feed_update(bot, updates.callback(updates.tg_user(employee.user.telegram_id), data))

    request = await get_membership(company, 507)
    assert request.status == Membership.Status.PENDING
    answer = [r for r in bot.requests if isinstance(r, AnswerCallbackQuery)][-1]
    assert answer.show_alert
    assert "permission" in answer.text


async def test_second_approver_sees_who_decided_first(dp, bot, company, member):
    first = await member.acreate(company, "Manager")
    second = await member.acreate(company, "Owner")
    applicant = updates.tg_user(508)
    await dp.feed_update(bot, updates.message(applicant, f"/start {company.invite_start_param}"))
    await dp.feed_update(bot, updates.pick_language(applicant))
    request = await get_membership(company, 508)
    approve = JoinDecision(action=JoinAction.APPROVE, membership_id=request.pk).pack()
    reject = JoinDecision(action=JoinAction.REJECT, membership_id=request.pk).pack()
    await dp.feed_update(bot, updates.callback(updates.tg_user(first.user.telegram_id), approve))

    await dp.feed_update(bot, updates.callback(updates.tg_user(second.user.telegram_id), reject))

    request = await get_membership(company, 508)
    assert request.status == Membership.Status.APPROVED
    answer = [r for r in bot.requests if isinstance(r, AnswerCallbackQuery)][-1]
    assert "already approved" in answer.text


# Approving through the inbox copy, with branches -----------------------------------------


@sync_to_async
def notified_request(company, telegram_id=601):
    """A filled-in join request, announced to the approvers (inbox notifications)."""
    from apps.members.notifications import send_join_request
    from apps.members.tests.factories import MembershipFactory

    request = MembershipFactory(
        company=company,
        first_name="Akmal",
        last_name="Jorayev",
        onboarded_at=timezone.now(),
        user__telegram_id=telegram_id,
        user__phone="+998901239988",
    )
    send_join_request(request.pk)
    return request


@sync_to_async
def copy_for(member):
    from apps.inbox.models import Notification

    return Notification.objects.get(kind="members.join", recipient=member)


@sync_to_async
def add_branch(company, name):
    from apps.companies.tests.factories import BranchFactory

    return BranchFactory(company=company, name=name, order=1)


@sync_to_async
def state_of(request):
    request.refresh_from_db()
    return (
        request.status,
        sorted(request.branches.values_list("name", flat=True)),
        request.home_branch.name if request.home_branch else None,
    )


def last_markup(bot):
    edit = [r for r in bot.requests if isinstance(r, EditMessageText)][-1]
    return edit, [button for row in edit.reply_markup.inline_keyboard for button in row]


async def test_one_branch_approves_at_once_from_the_inbox_copy(dp, bot, company, member):
    from apps.inbox.callbacks import InboxAction

    manager = await member.acreate(company, "Manager")
    request = await notified_request(company)
    copy = await copy_for(manager)

    await dp.feed_update(
        bot,
        updates.callback(
            updates.tg_user(manager.user.telegram_id),
            InboxAction(notification_id=copy.pk, key="approve").pack(),
        ),
    )

    status, branches, home = await state_of(request)
    assert status == Membership.Status.APPROVED
    assert len(branches) == 1 and home == branches[0]


async def test_several_branches_ask_for_branches_then_the_home_branch(dp, bot, company, member):
    from apps.inbox.callbacks import InboxAction
    from apps.members.callbacks import JoinSetup

    first_branch = await sync_to_async(lambda: company.branches.order_by("pk").first().name)()
    await add_branch(company, "Yunusobod")
    owner = await member.acreate(company, "Owner")
    request = await notified_request(company, telegram_id=602)
    copy = await copy_for(owner)
    presser = updates.tg_user(owner.user.telegram_id)

    await dp.feed_update(
        bot, updates.callback(presser, InboxAction(notification_id=copy.pk, key="approve").pack())
    )
    edit, buttons = last_markup(bot)
    assert "Where will Akmal work?" in edit.text
    toggles = [b for b in buttons if JoinSetup.unpack(b.callback_data).step == "b"]
    assert len(toggles) == 2
    approve = next(b for b in buttons if JoinSetup.unpack(b.callback_data).step == "ok")
    # Nothing chosen yet: Approve asks for a branch first.
    await dp.feed_update(bot, updates.callback(presser, approve.callback_data))
    assert (await state_of(request))[0] == Membership.Status.PENDING

    def unchosen(buttons):
        # A chosen branch is coloured, and the text names it (no tick marks).
        return [
            b
            for b in buttons
            if JoinSetup.unpack(b.callback_data).step == "b" and b.style != "success"
        ]

    for _ in range(2):  # choose both branches, one tap each
        await dp.feed_update(bot, updates.callback(presser, unchosen(buttons)[0].callback_data))
        edit, buttons = last_markup(bot)
    assert unchosen(buttons) == []
    assert f"Chosen: {first_branch}, Yunusobod" in edit.text
    approve = next(b for b in buttons if JoinSetup.unpack(b.callback_data).step == "ok")
    assert JoinSetup.unpack(approve.callback_data).branches == "3"  # both bits of the mask
    await dp.feed_update(bot, updates.callback(presser, approve.callback_data))
    edit, buttons = last_markup(bot)
    assert "home branch" in edit.text
    yunusobod = next(b for b in buttons if "Yunusobod" in b.text)
    await dp.feed_update(bot, updates.callback(presser, yunusobod.callback_data))

    status, branches, home = await state_of(request)
    assert status == Membership.Status.APPROVED
    assert branches == sorted([first_branch, "Yunusobod"])
    assert home == "Yunusobod"
    final = [r for r in bot.requests if isinstance(r, EditMessageText)][-1]
    assert "Approved" in final.text and final.reply_markup is None


def test_branch_choices_fit_telegrams_callback_limit():
    """Twelve branches with long ids, all chosen, still fit 64 bytes of callback data."""
    from types import SimpleNamespace

    from apps.members import bot_messages
    from apps.members.callbacks import JoinSetup, JoinStep

    branches = [SimpleNamespace(pk=9_000_000 + index) for index in range(12)]
    chosen = [branch.pk for branch in branches]

    packed = bot_messages._pack(chosen, branches)
    data = JoinSetup(
        step=JoinStep.HOME,
        membership_id=98_765_432,
        nid=987_654_321,
        branches=packed,
        role=12_345_678,
        pick=9_000_011,
    ).pack()

    assert len(data.encode()) <= 64
    assert bot_messages.unpack_branches(packed, branches) == chosen
    assert (
        bot_messages.unpack_branches(bot_messages._pack(chosen[3:5], branches), branches)
        == chosen[3:5]
    )
    assert bot_messages.unpack_branches("", branches) == []
    assert bot_messages.unpack_branches("not base36!", branches) == []


def app_data(telegram_id: int, data: str = "open_app") -> Update:
    """What Telegram sends when a mini app opened from a keyboard button calls sendData()."""
    return Update(
        update_id=telegram_id * 10 + 1,
        message=Message(
            message_id=telegram_id * 10 + 2,
            date=datetime.now(),
            chat=Chat(id=telegram_id, type="private"),
            from_user=updates.tg_user(telegram_id),
            web_app_data=WebAppData(data=data, button_text="Open app"),
        ),
    )


def sent(bot) -> list[SendMessage]:
    return [r for r in bot.requests if isinstance(r, SendMessage)]


async def test_an_app_opened_from_an_old_keyboard_gets_a_button_that_signs_in(
    dp, bot, company, member, settings
):
    """Telegram signs nobody in from a keyboard button: the app asks the bot for a way that does.
    The member gets today's menu (which replaces the old keyboard) and then the app's button."""
    settings.EMPLOYEE_MINIAPP_URL = "https://app.example.com/app/"
    worker = await member.aregistered(company)

    await dp.feed_update(bot, app_data(worker.user.telegram_id))

    menu, button = sent(bot)[-2:]
    assert isinstance(menu.reply_markup, ReplyKeyboardMarkup)
    assert not any(key.web_app for row in menu.reply_markup.keyboard for key in row)
    assert isinstance(button.reply_markup, InlineKeyboardMarkup)
    assert button.reply_markup.inline_keyboard[0][0].web_app.url == "https://app.example.com/app/"


async def test_someone_creating_an_account_gets_the_create_account_button_once(
    dp, bot, company, settings
):
    settings.EMPLOYEE_MINIAPP_URL = "https://app.example.com/app/"
    newcomer = updates.tg_user(503)
    await dp.feed_update(bot, updates.message(newcomer, f"/start {company.invite_start_param}"))
    await dp.feed_update(bot, updates.pick_language(newcomer))  # a new person picks first
    before = len(sent(bot))

    await dp.feed_update(bot, app_data(503))

    [reply] = sent(bot)[before:]
    assert "create your account" in reply.text
    assert reply.reply_markup.inline_keyboard[0][0].web_app.url == "https://app.example.com/app/"


async def test_other_app_data_is_left_alone(dp, bot, company, member, settings):
    settings.EMPLOYEE_MINIAPP_URL = "https://app.example.com/app/"
    worker = await member.aregistered(company)
    before = len(sent(bot))

    await dp.feed_update(bot, app_data(worker.user.telegram_id, data="something else"))

    assert not any(
        isinstance(r.reply_markup, InlineKeyboardMarkup)
        and r.reply_markup.inline_keyboard[0][0].web_app
        for r in sent(bot)[before:]
        if r.reply_markup is not None
    )
