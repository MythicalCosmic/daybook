"""Who uses the owner bot: owners and top managers. Other heads work from the employee bot."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.inbox.delivery import bots_for
from apps.members import departments
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.tests.factories import AccessRoleFactory
from apps.notifications.telegram import BotName
from apps.tasks import bot_messages, services
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


def fresh(member):
    return Membership.objects.select_related("role", "company", "user").get(pk=member.pk)


def test_owners_managers_and_top_department_heads_are_top_managers(company, member):
    owner = member.registered(company, "Owner")
    manager = member.registered(company, "Manager")  # every branch, gives work
    accountant = member.registered(company, "Accountant")
    role = AccessRoleFactory(
        company=company, permissions=[Perm.DASHBOARD_ACCESS, Perm.TASKS_ASSIGN]
    )
    branch_head = member.registered(company, role.name)
    top_head = member.registered(company, role.name)
    top = departments.create_department(company, by=owner, name="Rahbariyat", head=top_head)
    departments.create_department(company, by=owner, name="Savdo", parent=top, head=branch_head)

    assert departments.is_top_manager(fresh(owner))
    assert departments.is_top_manager(fresh(manager))
    assert departments.is_top_manager(fresh(top_head))
    assert not departments.is_top_manager(fresh(accountant))
    assert not departments.is_top_manager(fresh(branch_head))


def test_owner_notices_reach_others_through_the_employee_bot(company, member, settings):
    settings.OWNER_BOT_TOKEN = "43:OWNER"
    owner = member.registered(company, "Owner", user__owner_bot_started_at=timezone.now())
    accountant = member.registered(company, "Accountant", user__owner_bot_started_at=timezone.now())

    assert bots_for(owner.user, "owner", fresh(owner))[0] == BotName.OWNER
    assert bots_for(accountant.user, "owner", fresh(accountant)) == [BotName.EMPLOYEE]


def test_my_team_lists_people_and_their_late_work(company, member):
    owner = member.registered(company, "Owner")
    head = member.registered(company, first_name="Bekzod")
    alisher = member.registered(company, first_name="Alisher")
    sales = departments.create_department(company, by=owner, name="Savdo", head=head)
    departments.place(sales, by=owner, people=[head, alisher])
    task = services.create_task(
        by=owner, assignee=alisher, title="Vitrina", due_at=timezone.now() + timedelta(hours=1)
    )
    Task.objects.filter(pk=task.pk).update(due_at=timezone.now() - timedelta(hours=2))

    text, markup = bot_messages.team_summary(fresh(head))

    assert "My team" in text
    assert "Alisher" in text and "late: 1" in text
    assert "Vitrina" in text
    labels = [button.text for row in markup.inline_keyboard for button in row]
    assert "Remind" in labels
