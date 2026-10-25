import pytest
from django.utils import timezone

from apps.inbox.callbacks import InboxAction
from apps.inbox.models import Notification
from apps.members.callbacks import JoinAction, JoinDecision
from apps.members.models import Membership
from apps.members.notifications import (
    approver_chats,
    send_join_decision,
    send_join_request,
    send_onboarding_complete,
)
from apps.members.permissions import Perm
from apps.members.tests.factories import AccessRoleFactory, MembershipFactory, PositionFactory

pytestmark = pytest.mark.django_db


def test_approvers_are_owners_managers_and_platform_admins(
    company, other_company, member, settings
):
    owner = member(company, "Owner")
    manager = member(company, "Manager")
    member(company)  # employee
    member(company, "Manager", status=Membership.Status.PENDING)
    member(other_company, "Owner")
    settings.PLATFORM_ADMIN_TG_IDS = [999]

    chats = approver_chats(company)

    assert set(chats) == {owner.user.telegram_id, manager.user.telegram_id, 999}


def test_custom_role_with_the_approve_permission_counts(company):
    role = AccessRoleFactory(company=company, permissions=[Perm.MEMBERS_APPROVE])
    hr = MembershipFactory(company=company, role=role, status=Membership.Status.APPROVED)

    assert hr.user.telegram_id in approver_chats(company)


def submitted_request(company, **kwargs):
    """A pending request whose account details are filled in."""
    kwargs.setdefault("first_name", "Ali")
    kwargs.setdefault("last_name", "Valiyev")
    return MembershipFactory(
        company=company, onboarded_at=timezone.now(), user__phone="+998901234567", **kwargs
    )


def test_join_request_reaches_approvers_with_details_and_buttons(
    company, member, sent_messages, django_capture_on_commit_callbacks
):
    manager = member(company, "Manager")
    request = submitted_request(company, position=PositionFactory(company=company, name="Cashier"))

    with django_capture_on_commit_callbacks(execute=True):
        send_join_request(request.pk)

    [message] = sent_messages
    assert message["chat_id"] == manager.user.telegram_id
    assert "Ali Valiyev" in message["text"]
    assert "Position: Cashier" in message["text"]
    assert "Phone: +998901234567" in message["text"]
    # An inbox notification: deciding anywhere (bot, Needs you) settles every approver's copy.
    buttons = message["reply_markup"]["inline_keyboard"][0]
    actions = [InboxAction.unpack(button["callback_data"]) for button in buttons]
    assert [action.key for action in actions] == ["approve", "reject"]
    [item] = Notification.objects.filter(kind="members.join")
    assert (item.target_id, item.in_app) == (request.pk, False)


def test_platform_admins_outside_the_company_get_the_classic_request(
    company, member, sent_messages, settings, django_capture_on_commit_callbacks
):
    member(company, "Manager")
    settings.PLATFORM_ADMIN_TG_IDS = [999]
    request = submitted_request(company)

    with django_capture_on_commit_callbacks(execute=True):
        send_join_request(request.pk)

    [classic] = [message for message in sent_messages if message["chat_id"] == 999]
    buttons = classic["reply_markup"]["inline_keyboard"][0]
    decisions = [JoinDecision.unpack(button["callback_data"]) for button in buttons]
    assert [d.action for d in decisions] == [JoinAction.APPROVE, JoinAction.REJECT]


def test_request_without_details_is_not_sent_yet(company, member, sent_messages):
    member(company, "Manager")
    request = MembershipFactory(company=company)

    send_join_request(request.pk)

    assert sent_messages == []


def test_join_request_text_escapes_html(
    company, member, sent_messages, django_capture_on_commit_callbacks
):
    member(company, "Manager")
    request = submitted_request(company, first_name="<b>Eve</b>")

    with django_capture_on_commit_callbacks(execute=True):
        send_join_request(request.pk)

    assert "&lt;b&gt;Eve&lt;/b&gt;" in sent_messages[0]["text"]


def test_already_decided_request_is_not_sent(company, member, sent_messages):
    member(company, "Manager")
    request = MembershipFactory(company=company, status=Membership.Status.APPROVED)

    send_join_request(request.pk)

    assert sent_messages == []


def test_approved_requester_gets_the_main_menu(company, sent_messages):
    request = submitted_request(company, status=Membership.Status.APPROVED)

    send_join_decision(request.pk)

    [message] = sent_messages
    assert message["chat_id"] == request.user.telegram_id
    assert "was approved" in message["text"]
    assert message["reply_markup"]["keyboard"][0][0]["text"] == "My tasks"


def test_approved_before_registering_gets_the_create_account_button(
    company, settings, sent_messages
):
    settings.EMPLOYEE_MINIAPP_URL = "https://app.example.com"
    request = MembershipFactory(company=company, status=Membership.Status.APPROVED)

    send_join_decision(request.pk)

    button = sent_messages[0]["reply_markup"]["inline_keyboard"][0][0]
    assert button["web_app"]["url"] == "https://app.example.com"


def test_onboarded_member_hears_registration_is_complete(company, sent_messages):
    membership = MembershipFactory(
        company=company,
        status=Membership.Status.APPROVED,
        first_name="Ali",
        onboarded_at=timezone.now(),
    )

    send_onboarding_complete(membership.pk)

    assert "Registration complete! Welcome aboard, Ali." in sent_messages[0]["text"]


def test_rejected_requester_is_told_when_to_retry(company, sent_messages):
    request = MembershipFactory(
        company=company, status=Membership.Status.REJECTED, decided_at=timezone.now()
    )

    send_join_decision(request.pk)

    assert "You can ask again after" in sent_messages[0]["text"]


def test_blocked_person_is_not_told(company, sent_messages):
    request = MembershipFactory(company=company, status=Membership.Status.BLOCKED)

    send_join_decision(request.pk)

    assert sent_messages == []
