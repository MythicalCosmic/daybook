import pytest
from django.utils import timezone

from apps.members.callbacks import JoinAction, JoinDecision
from apps.members.models import Membership
from apps.members.notifications import approver_chats, send_join_decision, send_join_request
from apps.members.permissions import Perm
from apps.members.tests.factories import AccessRoleFactory, MembershipFactory

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


def test_join_request_reaches_approvers_with_buttons(company, member, sent_messages):
    manager = member(company, "Manager")
    request = MembershipFactory(company=company)

    send_join_request(request.pk)

    [message] = sent_messages
    assert message["chat_id"] == manager.user.telegram_id
    assert request.user.get_full_name() in message["text"]
    buttons = message["reply_markup"]["inline_keyboard"][0]
    decisions = [JoinDecision.unpack(button["callback_data"]) for button in buttons]
    assert [d.action for d in decisions] == [JoinAction.APPROVE, JoinAction.REJECT]
    assert {d.membership_id for d in decisions} == {request.pk}


def test_join_request_text_escapes_html(company, member, sent_messages):
    member(company, "Manager")
    request = MembershipFactory(company=company, user__first_name="<b>Eve</b>")

    send_join_request(request.pk)

    assert "&lt;b&gt;Eve&lt;/b&gt;" in sent_messages[0]["text"]


def test_already_decided_request_is_not_sent(company, member, sent_messages):
    member(company, "Manager")
    request = MembershipFactory(company=company, status=Membership.Status.APPROVED)

    send_join_request(request.pk)

    assert sent_messages == []


def test_approved_requester_gets_the_app_button(company, settings, sent_messages):
    settings.EMPLOYEE_MINIAPP_URL = "https://app.example.com"
    request = MembershipFactory(company=company, status=Membership.Status.APPROVED)

    send_join_decision(request.pk)

    [message] = sent_messages
    assert message["chat_id"] == request.user.telegram_id
    assert "was approved" in message["text"]
    button = message["reply_markup"]["inline_keyboard"][0][0]
    assert button["web_app"]["url"] == "https://app.example.com"


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
