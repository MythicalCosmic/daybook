"""The tasks demo (docs/PLAN-OWNER.md §2.3 rule 22), through the root `demo_people` fixture."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core import demo_plan
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
    assert tasks.exclude(proof_thumb="").count() >= 2
    assert tasks.filter(kind=Task.Kind.DAILY).count() > 150
    assert ReminderLog.objects.filter(
        task__company=company, kind=ReminderLog.Kind.ESCALATION
    ).exists()
    people["nigora"].user.refresh_from_db()
    assert people["nigora"].user.employee_bot_blocked_at is not None
    # Tonight's task features have something to show: a "can't do it" waiting for the owner, a
    # request for more time and "seen" receipts, all dated in order.
    blocked = tasks.get(blocked_at__isnull=False)
    assert blocked.blocker == Task.Blocker.BROKEN and blocked.next_reminder_at is None
    assert blocked.created_at < blocked.seen_at < blocked.blocked_at < timezone.now()
    asked = tasks.get(extension_until__isnull=False)
    assert asked.created_at < asked.seen_at < asked.extension_asked_at < timezone.now()
    assert asked.extension_until > asked.due_at
    assert tasks.filter(kind=Task.Kind.ASSIGNED, seen_at__isnull=False).count() >= 3
    # Fridge readings are written down inside the cold chain's range.
    readings = tasks.filter(template__title=demo_plan.FRIDGE_EVENING).exclude(proof_text="")
    assert readings.exists()
    assert all(2 <= int(task.proof_text.strip("+ °C")) <= 8 for task in readings)


def test_routines_follow_the_rota_and_leave(company, demo_people):
    """Routine work lands only on the days its person works, never on approved leave."""
    people = demo_people(company)
    now = timezone.now()
    demo.seed(company, people, now)
    story = demo_plan.Plan(company, people, now)

    for key in ("worker", "madina", "nigora", "jasur"):
        days = set(
            Task.objects.filter(
                company=company, kind=Task.Kind.DAILY, assignee=people[key]
            ).values_list("for_date", flat=True)
        )
        assert days
        assert all(story.works(key, day) for day in days), key
    # Madina is on leave today and tomorrow: nothing of hers is due then.
    madina_days = {story.today, story.today + timedelta(days=1)}
    assert not Task.objects.filter(assignee=people["madina"], for_date__in=madina_days).exists()
    # Nigora works nights: her routines are due in the evening.
    evening = Task.objects.filter(assignee=people["nigora"], kind=Task.Kind.DAILY)
    assert all(timezone.localtime(task.due_at, story.zone).hour >= 20 for task in evening)


def test_the_demo_enriches_the_core_demos_routines_instead_of_copying_them(company, demo_people):
    people = demo_people(company)
    core = TaskTemplate.objects.create(
        company=company, title=demo_plan.HANDOVER, due_time="08:15", created_by=people["owner"]
    )
    core.assignees.add(people["worker"])
    demo.seed(company, people, timezone.now())

    core.refresh_from_db()
    assert core.checklist and core.needs_confirmation and core.reminder_policy_id
    assert core.proof == Proof.NONE
    assert TaskTemplate.objects.filter(company=company, title=demo_plan.HANDOVER).count() == 1
    # Two months of history on his working days (two on, two off).
    assert Task.objects.filter(template=core, assignee=people["worker"]).count() > 25
    # Nothing was "created just now": given work was given earlier, routines at midnight.
    recent = timezone.now() - timedelta(minutes=5)
    assert not Task.objects.filter(company=company, created_at__gt=recent).exists()
