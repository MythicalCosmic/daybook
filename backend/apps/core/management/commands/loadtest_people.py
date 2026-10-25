"""People for the load test (scripts/loadtest/, docs/DEPLOY.md "Load test").

    manage.py loadtest_people --people 300 --managers 20     # make them, with fresh tasks
    manage.py loadtest_people --delete                        # remove them again

Everything lives in a company of its own ("Load test", slug `loadtest`), so nobody real sees
it. The people's Telegram ids start at --first-id (990 000 000 001 by default, far above any id
Telegram hands out), workers first, then managers; each worker gets --tasks open tasks given by
a manager, due tonight, plus one finished task waiting for a manager's check. Running it again
gives everyone fresh tasks.

Nothing is sent to anyone: rows are written directly (no services, so no notifications), the
tasks have no reminder scheduled, and the people are marked as having blocked both bots, so the
digests and reminders that honour that skip them. Their chats don't exist either, so the few
messages a finished task or a comment still sends are refused by Telegram and dropped.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.companies.models import Company
from apps.companies.services import create_company
from apps.members.models import AccessRole, Membership
from apps.tasks.models import Task

SLUG = "loadtest"
FIRST_ID = 990_000_000_001


class Command(BaseCommand):
    help = "Create (or remove) the load test's company, people and tasks."

    def add_arguments(self, parser):
        parser.add_argument("--people", type=int, default=300, help="Workers (default 300).")
        parser.add_argument("--managers", type=int, default=20, help="Managers (default 20).")
        parser.add_argument("--tasks", type=int, default=3, help="Open tasks per worker.")
        parser.add_argument("--first-id", type=int, default=FIRST_ID)
        parser.add_argument(
            "--delete", action="store_true", help="Remove the people and their tasks."
        )

    def handle(self, *args, people, managers, tasks, first_id, delete, **options):
        if delete:
            self._delete(first_id)
            return
        if people < 1 or managers < 1 or tasks < 1:
            raise CommandError("--people, --managers and --tasks must be at least 1.")
        with transaction.atomic():
            company = self._company()
            workers, bosses = self._people(company, first_id, people, managers)
            made = self._tasks(company, workers, bosses, tasks)
        last = first_id + people + managers - 1
        self.stdout.write(
            f"Load test company {company.pk}: {people} workers (Telegram ids {first_id}–"
            f"{first_id + people - 1}), {managers} managers (to {last}), {made} tasks."
        )

    def _company(self) -> Company:
        company = Company.objects.filter(slug=SLUG).first()
        if company is None:
            company = create_company(name="Load test", slug=SLUG, timezone="Asia/Tashkent")
        elif not company.is_active:
            company.is_active = True
            company.save(update_fields=["is_active"])
        return company

    def _people(self, company, first_id, people, managers):
        branch = company.branches.order_by("pk").first()
        roles = AccessRole.objects.for_company(company)
        worker_role = roles.filter(is_default=True).first() or roles.get(name="Employee")
        manager_role = roles.get(name="Manager")
        now = timezone.now()
        ids = list(range(first_id, first_id + people + managers))
        User.objects.bulk_create(
            [
                User(
                    username=f"tg{tg_id}",
                    telegram_id=tg_id,
                    first_name=f"Test {index + 1}",
                    last_name="Yuklama",
                    password="!",  # unusable: they only ever sign in with Telegram
                    employee_bot_blocked_at=now,
                    owner_bot_blocked_at=now,
                )
                for index, tg_id in enumerate(ids)
            ],
            ignore_conflicts=True,
        )
        users = {user.telegram_id: user for user in User.objects.filter(telegram_id__in=ids)}
        User.objects.filter(telegram_id__in=ids).update(
            employee_bot_blocked_at=now, owner_bot_blocked_at=now, bot_company=company
        )
        Membership.objects.bulk_create(
            [
                Membership(
                    company=company,
                    user=users[tg_id],
                    status=Membership.Status.APPROVED,
                    first_name=users[tg_id].first_name,
                    last_name=users[tg_id].last_name,
                    role=manager_role if index >= people else worker_role,
                    decided_at=now,
                    onboarded_at=now,
                    home_branch=branch,
                )
                for index, tg_id in enumerate(ids)
            ],
            ignore_conflicts=True,
        )
        members = list(
            Membership.objects.filter(company=company, user__telegram_id__in=ids).select_related(
                "user"
            )
        )
        Membership.branches.through.objects.bulk_create(
            [
                Membership.branches.through(membership_id=member.pk, branch_id=branch.pk)
                for member in members
            ],
            ignore_conflicts=True,
        )
        by_id = {member.user.telegram_id: member for member in members}
        workers = [by_id[tg_id] for tg_id in ids[:people]]
        bosses = [by_id[tg_id] for tg_id in ids[people:]]
        return workers, bosses

    def _tasks(self, company, workers, bosses, per_worker) -> int:
        Task.objects.filter(company=company).delete()
        tz = ZoneInfo(company.timezone)
        today = timezone.localtime(timezone.now(), tz).date()
        tonight = datetime.combine(today, time(23, 0), tzinfo=tz)
        now = timezone.now()
        branch = company.branches.order_by("pk").first()
        rows = []
        for index, worker in enumerate(workers):
            boss = bosses[index % len(bosses)]
            common = {
                "company": company,
                "kind": Task.Kind.ASSIGNED,
                "assignee": worker,
                "created_by": boss,
                "branch": branch,
            }
            rows.extend(
                Task(title=f"Javonni tekshirish {number + 1}", due_at=tonight, **common)
                for number in range(per_worker)
            )
            rows.append(
                Task(
                    title="Kassa hisobotini topshirish",
                    due_at=tonight,
                    status=Task.Status.REVIEW,
                    needs_confirmation=True,
                    completed_at=now - timedelta(hours=1),
                    **common,
                )
            )
        Task.objects.bulk_create(rows, batch_size=1000)
        return len(rows)

    def _delete(self, first_id):
        company = Company.objects.filter(slug=SLUG).first()
        users = User.objects.filter(telegram_id__gte=first_id, telegram_id__lt=first_id + 100_000)
        with transaction.atomic():
            if company is not None:
                Task.objects.filter(company=company).delete()
                Membership.objects.filter(company=company).delete()
                company.is_active = False
                company.save(update_fields=["is_active"])
            count = users.count()
            users.delete()
        self.stdout.write(f"Removed {count} load test people; the company is switched off.")
