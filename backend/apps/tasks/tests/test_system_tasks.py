"""`create_system_task` (docs/PLAN-OWNER.md §14.5): work the system gives someone, with nobody's
name on it, at their branch, under the company's reminders and with the usual message."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.members.models import Membership
from apps.tasks import services
from apps.tasks.models import Activity, Task

pytestmark = pytest.mark.django_db


def test_an_assigned_task_without_a_giver(
    company, member, django_capture_on_commit_callbacks, sent_messages
):
    branch = company.branches.create(name="Yunusobod")
    head = member.registered(company, "Manager", home_branch=branch)
    owner = member.registered(company, "Owner")
    due = timezone.now() + timedelta(days=2)

    with django_capture_on_commit_callbacks(execute=True):
        task = services.create_system_task(
            company,
            assignee=head,
            title="  Expiry shelf check  ",
            due_at=due,
            description="Batches expiring within 90 days",
            checklist=["Amoksitsillin 500 mg · 230415", " ", "Paratsetamol 500 mg · 77"],
            escalate_to=owner,
        )

    task.refresh_from_db()
    assert task.kind == Task.Kind.ASSIGNED and task.created_by is None
    assert task.title == "Expiry shelf check" and task.due_at == due
    assert task.branch_id == branch.pk and task.escalate_to == owner
    assert not task.needs_confirmation and task.next_reminder_at is not None
    assert [item.text for item in task.checklist.order_by("order")] == [
        "Amoksitsillin 500 mg · 230415",
        "Paratsetamol 500 mg · 77",
    ]
    assert Activity.objects.filter(recipient=head, task=task, actor=None).exists()
    entry = AuditLog.objects.get(action=AuditLog.Action.TASK_ASSIGNED, target_id=task.pk)
    assert entry.actor is None
    [message] = [m for m in sent_messages if m["chat_id"] == head.user.telegram_id]
    assert "Expiry shelf check" in message["text"]


@pytest.mark.parametrize(
    "who",
    [
        {"status": Membership.Status.PENDING},
        {"status": Membership.Status.LEFT},
        {"onboarded_at": None},
    ],
)
def test_only_someone_working_in_the_company(company, member, who):
    person = member(company, **{"onboarded_at": timezone.now(), **who})
    with pytest.raises(DomainError):
        services.create_system_task(
            company, assignee=person, title="Remove series", due_at=timezone.now() + timedelta(1)
        )
    assert not Task.objects.exists()


def test_not_someone_of_another_company(company, other_company, member):
    stranger = member.registered(other_company)
    with pytest.raises(DomainError):
        services.create_system_task(
            company, assignee=stranger, title="Remove series", due_at=timezone.now() + timedelta(1)
        )
