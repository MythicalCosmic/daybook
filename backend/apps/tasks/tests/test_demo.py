"""The tasks demo (docs/PLAN-OWNER.md §2.3 rule 22), through the root `demo_people` fixture."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.reminders.models import ReminderLog, ReminderPolicy
from apps.tasks import demo
from apps.tasks.models import Proof, Task, TaskTemplate

pytestmark = pytest.mark.django_db


def test_the_demo_fills_every_page(company, demo_people):
    people = demo_people(company)
    demo.seed(company, people, timezone.now())

    assert (
        TaskTemplate.objects.filter(company=company, onboarding=False, personal=False).count() >= 8
    )
    assert TaskTemplate.objects.filter(company=company, onboarding=True).count() == 4
    assert ReminderPolicy.objects.filter(company=company).count() == 3
    tasks = Task.objects.filter(company=company)
    assert tasks.filter(status=Task.Status.REVIEW).exclude(proof_photo="").exists()
    assert tasks.filter(status=Task.Status.RETURNED).exists()
    assert tasks.filter(reward__isnull=False).exists()
    assert tasks.exclude(proof_thumb="").count() >= 3
    assert tasks.filter(kind=Task.Kind.DAILY).count() > 150
    assert ReminderLog.objects.filter(
        task__company=company, kind=ReminderLog.Kind.ESCALATION
    ).exists()
    people["nigora"].user.refresh_from_db()
    assert people["nigora"].user.employee_bot_blocked_at is not None


def test_the_demo_enriches_the_core_demos_routines_instead_of_copying_them(company, demo_people):
    people = demo_people(company)
    core = TaskTemplate.objects.create(
        company=company, title="Opening checklist", due_time="08:30", created_by=people["owner"]
    )
    core.assignees.add(people["worker"])
    demo.seed(company, people, timezone.now())

    core.refresh_from_db()
    assert core.proof == Proof.PHOTO and core.checklist and core.branch_id is not None
    assert not TaskTemplate.objects.filter(
        company=company, title="Do‘konni ochish: tekshiruv ro‘yxati"
    ).exists()
    # Two months of history, so the reports' comparison has a month before to compare with.
    assert Task.objects.filter(template=core, assignee=people["worker"]).count() > 50
    # Nothing was "created just now": given work was given earlier, routines at midnight.
    recent = timezone.now() - timedelta(minutes=5)
    assert not Task.objects.filter(company=company, created_at__gt=recent).exists()
