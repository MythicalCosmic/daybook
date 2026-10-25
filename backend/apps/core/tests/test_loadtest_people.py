"""manage.py loadtest_people: the load test's company, people and tasks (docs/DEPLOY.md)."""

import pytest
from django.core.management import call_command

from apps.accounts.models import User
from apps.companies.models import Company
from apps.members.models import Membership
from apps.signin.services import can_sign_in
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db

FIRST = 990_000_000_001


def make(**options):
    call_command("loadtest_people", people=5, managers=2, tasks=3, **options)
    return Company.objects.get(slug="loadtest")


def test_people_and_tasks_in_a_company_of_their_own():
    company = make()

    workers = Membership.objects.filter(company=company, role__name="Employee")
    managers = Membership.objects.filter(company=company, role__name="Manager")
    assert workers.count() == 5
    assert managers.count() == 2
    assert set(workers.values_list("user__telegram_id", flat=True)) == set(range(FIRST, FIRST + 5))
    assert all(m.status == Membership.Status.APPROVED and m.onboarded_at for m in workers)
    # Each worker: three open tasks from a manager, one waiting for a check; none reminded.
    tasks = Task.objects.filter(company=company)
    assert tasks.filter(status=Task.Status.TODO).count() == 15
    assert tasks.filter(status=Task.Status.REVIEW).count() == 5
    assert not tasks.filter(next_reminder_at__isnull=False).exists()
    assert set(tasks.values_list("created_by__role__name", flat=True)) == {"Manager"}
    # Managers may open the dashboard; nobody gets bot messages.
    assert all(can_sign_in(m.user) for m in managers)
    people = User.objects.filter(telegram_id__gte=FIRST)
    assert not people.filter(employee_bot_blocked_at__isnull=True).exists()


def test_running_it_again_gives_fresh_tasks_without_new_people():
    company = make()
    Task.objects.filter(company=company).update(status=Task.Status.DONE)

    make()

    assert Membership.objects.filter(company=company).count() == 7
    assert Task.objects.filter(company=company, status=Task.Status.DONE).count() == 0
    assert Task.objects.filter(company=company, status=Task.Status.TODO).count() == 15


def test_delete_removes_them():
    company = make()

    call_command("loadtest_people", delete=True)

    company.refresh_from_db()
    assert not company.is_active
    assert not User.objects.filter(telegram_id__gte=FIRST).exists()
    assert not Task.objects.filter(company=company).exists()
