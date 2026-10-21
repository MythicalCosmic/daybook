"""Onboarding tasks (docs/PLAN-OWNER.md §1.3, §10.1): when someone is approved, the onboarding
templates that name them give them one task each, once per approval, for their position."""

from datetime import time

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.members import services as member_services
from apps.members.models import Membership
from apps.members.tests.factories import PositionFactory
from apps.tasks import onboarding
from apps.tasks.models import Task, TaskTemplate
from apps.tasks.tests.factories import TaskTemplateFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def cashier(company):
    return PositionFactory(company=company, name="Cashier")


@pytest.fixture
def templates(company, member, cashier):
    owner = member.registered(company, "Owner")
    everyone = TaskTemplateFactory(
        company=company,
        title="Read the safety rules",
        onboarding=True,
        due_after_days=1,
        due_time=time(12, 0),
        created_by=owner,
        checklist=["Fire exits", "First aid kit"],
    )
    cashiers = TaskTemplateFactory(
        company=company,
        title="Learn the till",
        onboarding=True,
        due_after_days=2,
        created_by=owner,
        positions=[cashier],
    )
    routine = TaskTemplateFactory(company=company, title="Daily opening", positions=[cashier])
    return everyone, cashiers, routine


def approve(company, member, position, django_capture_on_commit_callbacks):
    approver = member.registered(company, "Owner")
    newcomer = member(company, status=Membership.Status.PENDING, position=position)
    with django_capture_on_commit_callbacks(execute=True):
        member_services.approve(newcomer, by=approver.user)
    return newcomer


def test_a_new_cashier_gets_every_onboarding_task_for_them(
    company, member, cashier, templates, django_capture_on_commit_callbacks, sent_messages
):
    everyone, _cashiers, _routine = templates
    newcomer = approve(company, member, cashier, django_capture_on_commit_callbacks)

    tasks = Task.objects.filter(assignee=newcomer).order_by("due_at")
    assert [task.title for task in tasks] == ["Read the safety rules", "Learn the till"]
    first = tasks[0]
    assert first.kind == Task.Kind.ASSIGNED and first.template == everyone
    assert [item.text for item in first.checklist.all()] == ["Fire exits", "First aid kit"]
    assert first.due_at > timezone.now()
    assert first.next_reminder_at is not None
    assert AuditLog.objects.filter(
        action="tasks.onboarding_assigned", target_id=newcomer.pk
    ).exists()
    assert (
        len(
            [
                m
                for m in sent_messages
                if m["chat_id"] == newcomer.user.telegram_id and "Welcome" in m["text"]
            ]
        )
        == 1
    )


def test_people_of_other_positions_only_get_the_general_ones(
    company, member, templates, django_capture_on_commit_callbacks
):
    stocker = PositionFactory(company=company, name="Stock")
    newcomer = approve(company, member, stocker, django_capture_on_commit_callbacks)
    assert list(Task.objects.filter(assignee=newcomer).values_list("title", flat=True)) == [
        "Read the safety rules"
    ]


def test_once_per_approval(company, member, cashier, templates, django_capture_on_commit_callbacks):
    newcomer = approve(company, member, cashier, django_capture_on_commit_callbacks)
    assert onboarding.assign_onboarding(newcomer) == []
    assert Task.objects.filter(assignee=newcomer).count() == 2


def test_a_branch_template_only_reaches_that_branchs_people(company, member, cashier, templates):
    there = company.branches.create(name="Yunusobod")
    TaskTemplateFactory(
        company=company, title="Meet the Yunusobod lead", onboarding=True, branch=there
    )
    here_person = member.registered(
        company, position=cashier, home_branch=company.branches.order_by("pk").first()
    )
    there_person = member.registered(company, position=cashier, home_branch=there)
    assert "Meet the Yunusobod lead" not in [
        t.title for t in onboarding.assign_onboarding(here_person)
    ]
    assert "Meet the Yunusobod lead" in [
        t.title for t in onboarding.assign_onboarding(there_person)
    ]


def test_paused_templates_and_routines_dont_count(company, member, cashier, templates):
    everyone, _, _ = templates
    TaskTemplate.objects.filter(pk=everyone.pk).update(is_active=False)
    newcomer = member.registered(company, position=cashier)
    assert [t.title for t in onboarding.assign_onboarding(newcomer)] == ["Learn the till"]


def test_daily_generation_skips_onboarding_templates(company, member, cashier, templates):
    from apps.tasks.generation import generate_daily_tasks

    member.registered(company, position=cashier)
    generate_daily_tasks(company, timezone.localdate() + timezone.timedelta(days=1))
    assert set(Task.objects.values_list("title", flat=True)) == {"Daily opening"}
