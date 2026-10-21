"""members/0009: every existing company gets the Pharmacist role of `DEFAULT_ROLES`
(docs/PLAN-OWNER.md §14.3) where no role has that name yet, run against today's models."""

import importlib

import pytest
from django.apps import apps as django_apps

from apps.members.models import AccessRole
from apps.members.permissions import DEFAULT_ROLES

pytestmark = pytest.mark.django_db

MIGRATION = importlib.import_module("apps.members.migrations.0009_pharmacist_role")


def create():
    MIGRATION.create_pharmacist_role(django_apps, None)


def pharmacists(company):
    return AccessRole.objects.filter(company=company, name="Pharmacist")


def test_companies_made_before_get_the_role_once(company, other_company):
    pharmacists(company).delete()  # as a company made before the role existed
    pharmacists(other_company).delete()

    create()
    create()  # a second run adds nothing

    for each in (company, other_company):
        [role] = pharmacists(each)
        assert sorted(role.permissions) == ["finance.claim", "sales.operate"]
        assert not role.is_owner and not role.is_default


def test_an_owners_own_pharmacist_role_and_the_other_roles_stay(company):
    own = pharmacists(company).get()
    own.permissions = ["tasks.assign"]
    own.save()
    before = {role.pk: list(role.permissions) for role in AccessRole.objects.order_by("pk")}

    create()

    after = {role.pk: list(role.permissions) for role in AccessRole.objects.order_by("pk")}
    assert after == before
    assert pharmacists(company).count() == 1


def test_the_frozen_role_is_todays_default_role():
    [today] = [role for role in DEFAULT_ROLES if role["name"] == MIGRATION.NAME]
    assert [str(perm) for perm in today["permissions"]] == MIGRATION.PERMISSIONS
