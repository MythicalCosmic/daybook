"""members/0016 (docs/PLAN-OWNER.md §14.5): every role that runs a till gains `stock.operate`,
and a Pharmacist role is made where the name is free; run against today's models."""

import importlib

import pytest
from django.apps import apps as django_apps

from apps.members.models import AccessRole

pytestmark = pytest.mark.django_db

MIGRATION = importlib.import_module("apps.members.migrations.0016_stock_operate")


def run():
    MIGRATION.give_stock_operate(django_apps, None)


def test_till_roles_gain_stock_operate_once(company):
    cashier = AccessRole.objects.get(company=company, name="Cashier")
    cashier.permissions = ["sales.operate", "finance.claim"]  # as before W2.a
    cashier.save()
    own = AccessRole.objects.create(
        company=company, name="Night till", permissions=["sales.operate"]
    )
    office = AccessRole.objects.create(company=company, name="Office", permissions=["tasks.assign"])

    run()
    run()  # a second run adds nothing

    cashier.refresh_from_db()
    own.refresh_from_db()
    office.refresh_from_db()
    assert cashier.permissions == ["sales.operate", "finance.claim", "stock.operate"]
    assert own.permissions == ["sales.operate", "stock.operate"]
    assert office.permissions == ["tasks.assign"]


def test_a_company_without_a_pharmacist_gets_one(company, other_company):
    AccessRole.objects.filter(company=company, name="Pharmacist").delete()
    own = AccessRole.objects.get(company=other_company, name="Pharmacist")
    own.permissions = ["tasks.assign"]  # an owner's own role of that name stays theirs
    own.save()

    run()

    [made] = AccessRole.objects.filter(company=company, name="Pharmacist")
    assert sorted(made.permissions) == ["finance.claim", "sales.operate", "stock.operate"]
    own.refresh_from_db()
    assert own.permissions == ["tasks.assign"]
    assert AccessRole.objects.filter(company=other_company, name="Pharmacist").count() == 1
