"""The tasks demo (docs/PLAN-OWNER.md §2.3 rule 22), through the root `demo_people` fixture."""

import pytest
from django.utils import timezone

from apps.reminders.models import ReminderLog, ReminderPolicy
from apps.tasks import demo
from apps.tasks.models import Task, TaskTemplate

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
