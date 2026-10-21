"""members/0008: default roles of companies made before Phase 2 gain the Phase 2 permissions
their definition lists, run against today's models (the role fields are the same)."""

import importlib

import pytest
from django.apps import apps as django_apps

from apps.members.models import AccessRole
from apps.members.permissions import DEFAULT_ROLES

pytestmark = pytest.mark.django_db

MIGRATION = importlib.import_module("apps.members.migrations.0008_phase2_default_role_permissions")
# What a company made before Phase 2 had (members/0005 then added a few to Manager).
PHASE_1 = {
    "members.view",
    "members.approve",
    "members.manage",
    "roles.manage",
    "positions.manage",
    "tasks.view_all",
    "tasks.assign",
    "tasks.templates",
    "tasks.confirm",
    "reminders.configure",
    "groups.manage",
    "reports.view",
    "time_off.approve",
    "announcements.send",
}


def grant():
    MIGRATION.grant_phase2_permissions(django_apps, None)


def as_before_phase_2(company):
    for role in AccessRole.objects.filter(company=company, is_owner=False):
        role.permissions = [perm for perm in role.permissions if perm in PHASE_1]
        role.save()


def role(company, name) -> AccessRole:
    return AccessRole.objects.get(company=company, name=name)


def test_default_roles_gain_their_phase_2_permissions(company):
    as_before_phase_2(company)
    before = list(role(company, "Manager").permissions)

    grant()

    manager = role(company, "Manager").permissions
    assert manager[: len(before)] == before  # kept, in order, with the new ones after them
    assert {"sales.manage", "attendance.manage", "projects.manage", "hr.hiring"} <= set(manager)
    assert not {"finance.view", "payroll.view", "hr.sensitive"} & set(manager)
    assert {"finance.manage", "payroll.pay", "audit.view"} <= set(
        role(company, "Accountant").permissions
    )
    assert sorted(role(company, "Cashier").permissions) == ["finance.claim", "sales.operate"]
    assert role(company, "Employee").permissions == ["finance.claim"]


def test_custom_renamed_and_owner_roles_are_left_alone(company):
    as_before_phase_2(company)
    custom = AccessRole.objects.create(
        company=company, name="Supervisor", permissions=["tasks.assign"]
    )
    renamed = role(company, "Manager")
    renamed.name = "Rahbar"
    renamed.save()
    owner = AccessRole.objects.get(company=company, is_owner=True)
    owner_permissions = list(owner.permissions)

    grant()

    custom.refresh_from_db()
    renamed.refresh_from_db()
    owner.refresh_from_db()
    assert custom.permissions == ["tasks.assign"]
    assert set(renamed.permissions) <= PHASE_1
    assert owner.permissions == owner_permissions


def test_nothing_is_removed_and_a_second_run_changes_nothing(company, other_company):
    as_before_phase_2(company)
    manager = role(other_company, "Manager")
    manager.permissions = ["members.manage", "hr.sensitive"]  # the owner's own choices stay
    manager.save()

    grant()
    after = {r.pk: list(r.permissions) for r in AccessRole.objects.order_by("pk")}
    grant()

    manager.refresh_from_db()
    assert manager.permissions[:2] == ["members.manage", "hr.sensitive"]
    assert {r.pk: list(r.permissions) for r in AccessRole.objects.order_by("pk")} == after


def test_the_frozen_lists_cover_todays_default_roles():
    """A Phase 2 permission added to a default role later needs its own migration for the roles
    of existing companies; this fails until there is one (then extend the expected set here)."""
    created_later = {"Pharmacist"}  # members/0009 makes it with its own frozen list
    today = {
        definition["name"]: [str(perm) for perm in definition.get("permissions", ())]
        for definition in DEFAULT_ROLES
        if not definition.get("is_owner") and definition["name"] not in created_later
    }

    for name, permissions in today.items():
        phase_2 = [perm for perm in permissions if perm not in PHASE_1]
        assert phase_2 == MIGRATION.PHASE2_PERMISSIONS[name], name
