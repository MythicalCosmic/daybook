"""The Wave 0 data migrations, run against today's models (their fields are the same).

Each existing company keeps working on deploy day: one branch, members in it, tasks bound to
their assignee's branch, roles with the new permissions added (never removed).
"""

import importlib
from datetime import timedelta

import pytest
from django.apps import apps as django_apps
from django.utils import timezone

from apps.announcements.models import Announcement
from apps.companies.models import Branch, Company
from apps.companies.tests.factories import BranchFactory
from apps.members.models import AccessRole, Membership
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db


def run(app, migration, function):
    module = importlib.import_module(f"apps.{app}.migrations.{migration}")
    getattr(module, function)(django_apps, None)


def as_before_wave_0(company):
    """A company the way the previous release left it: three roles and no branch."""
    AccessRole.objects.filter(company=company, name__in=["Accountant", "Cashier"]).delete()
    for role in AccessRole.objects.filter(company=company):
        role.permissions = [
            perm
            for perm in role.permissions
            if perm
            in {
                "members.view",
                "members.approve",
                "tasks.view_all",
                "tasks.assign",
                "tasks.templates",
                "tasks.confirm",
                "groups.manage",
                "reports.view",
                "time_off.approve",
                "announcements.send",
            }
        ]
        role.save()
    Branch.objects.filter(company=company).delete()


class TestPermissions:
    def grant(self):
        run("members", "0005_owner_console_permissions", "grant_owner_console_permissions")

    def test_existing_roles_gain_only_the_listed_permissions(self, company):
        as_before_wave_0(company)
        reporter = AccessRole.objects.create(
            company=company, name="Reporter", permissions=["reports.view"]
        )
        approver = AccessRole.objects.create(
            company=company, name="Door", permissions=["members.approve", "hr.view"]
        )

        self.grant()

        manager = AccessRole.objects.get(company=company, name="Manager")
        assert set(manager.permissions) >= {
            "dashboard.access",
            "attendance.view",
            "branches.all",
            "hr.view",
            "payroll.propose",
            "finance.claim",
        }
        assert not set(manager.permissions) & {"finance.view", "payroll.view", "sales.manage"}
        reporter.refresh_from_db()
        assert sorted(reporter.permissions) == [
            "attendance.view",
            "dashboard.access",
            "reports.view",
        ]
        approver.refresh_from_db()
        assert approver.permissions == [
            "members.approve",
            "hr.view",
            "branches.all",
            "payroll.propose",
            "finance.claim",
        ]
        employee = AccessRole.objects.get(company=company, name="Employee")
        assert employee.permissions == ["finance.claim"]

    def test_cashier_and_accountant_are_added_when_the_names_are_free(self, company, other_company):
        as_before_wave_0(company)
        as_before_wave_0(other_company)
        mine = AccessRole.objects.create(company=other_company, name="Cashier", permissions=[])

        self.grant()

        accountant = AccessRole.objects.get(company=company, name="Accountant")
        assert {"finance.view", "payroll.view", "members.view", "reports.view"} <= set(
            accountant.permissions
        )
        assert not accountant.is_default and not accountant.is_owner
        cashier = AccessRole.objects.get(company=company, name="Cashier")
        assert sorted(cashier.permissions) == ["finance.claim", "sales.operate"]
        mine.refresh_from_db()
        assert mine.permissions == []  # someone's own role is left alone
        assert AccessRole.objects.filter(company=other_company, name="Accountant").exists()

    def test_running_twice_changes_nothing(self, company):
        as_before_wave_0(company)
        self.grant()
        before = {r.pk: list(r.permissions) for r in AccessRole.objects.all()}

        self.grant()

        assert {r.pk: list(r.permissions) for r in AccessRole.objects.all()} == before


class TestBranches:
    def test_every_company_gets_one_branch_named_after_it(self, company, other_company):
        as_before_wave_0(company)
        as_before_wave_0(other_company)
        Company.objects.filter(pk=company.pk).update(name="A" * 150)
        kept = BranchFactory(company=other_company, name="Already there")

        run("companies", "0006_one_branch_per_company", "add_the_first_branch")

        assert list(company.branches.values_list("name", flat=True)) == ["A" * 100]
        assert list(other_company.branches.all()) == [kept]

    def test_approved_members_work_in_the_only_branch(self, company, other_company, member):
        as_before_wave_0(company)
        branch = BranchFactory(company=company)
        approved = member(company)
        pending = member(company, status=Membership.Status.PENDING)
        gone = member(company, status=Membership.Status.LEFT)
        BranchFactory(company=other_company)
        BranchFactory(company=other_company)  # two branches: the owner decides
        elsewhere = member(other_company)

        run("members", "0006_membership_branches", "assign_the_only_branch")

        for person in (approved, pending, gone, elsewhere):
            person.refresh_from_db()
        assert approved.home_branch == branch
        assert list(approved.branches.all()) == [branch]
        for person in (pending, gone, elsewhere):
            assert person.home_branch is None
            assert not person.branches.exists()

    def test_tasks_take_their_assignees_branch(self, company, member):
        branch = BranchFactory(company=company)
        other = BranchFactory(company=company)
        worker = member(company, home_branch=branch)
        homeless = member(company)
        bound = TaskFactory(assignee=worker, branch=other)
        unbound = TaskFactory(assignee=worker)
        orphan = TaskFactory(assignee=homeless)

        run("tasks", "0005_task_branch_backfill", "take_the_assignees_branch")

        assert Task.objects.get(pk=bound.pk).branch == other  # never moved once set
        assert Task.objects.get(pk=unbound.pk).branch == branch
        assert Task.objects.get(pk=orphan.pk).branch is None


def test_announcements_were_sent_when_written(company, member):
    author = member(company, "Manager")
    old = Announcement.objects.create(company=company, author=author, text="Old news")
    draft = Announcement.objects.create(
        company=company, author=author, text="Later", status=Announcement.Status.DRAFT
    )
    sent = timezone.now() - timedelta(days=1)
    already = Announcement.objects.create(company=company, author=author, text="X", sent_at=sent)

    run("announcements", "0003_announcement_sent_at_backfill", "sent_when_created")

    old.refresh_from_db()
    draft.refresh_from_db()
    already.refresh_from_db()
    assert old.sent_at == old.created_at
    assert draft.sent_at is None
    assert already.sent_at == sent
