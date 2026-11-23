"""members/0018 (docs/KOZ.md §2): every role that manages routines gains `vision.view`,
`vision.video` and `vision.manage`; run against today's models."""

import importlib

import pytest
from django.apps import apps as django_apps

from apps.members.models import AccessRole

pytestmark = pytest.mark.django_db

MIGRATION = importlib.import_module("apps.members.migrations.0018_vision_permissions")
VISION = ["vision.view", "vision.video", "vision.manage"]


def run():
    MIGRATION.give_vision(django_apps, None)


def test_routine_managers_gain_vision_once(company):
    manager = AccessRole.objects.get(company=company, name="Manager")
    manager.permissions = [p for p in manager.permissions if not p.startswith("vision.")]
    manager.save()
    head = AccessRole.objects.create(
        company=company, name="Head", permissions=["tasks.templates", "vision.view"]
    )
    office = AccessRole.objects.create(company=company, name="Office", permissions=["tasks.assign"])

    run()
    run()  # a second run adds nothing

    manager.refresh_from_db()
    head.refresh_from_db()
    office.refresh_from_db()
    assert manager.permissions[-3:] == VISION
    assert manager.permissions.count("vision.manage") == 1
    assert head.permissions == ["tasks.templates", "vision.view", "vision.video", "vision.manage"]
    assert office.permissions == ["tasks.assign"]


def test_cashiers_and_employees_get_nothing(company):
    run()

    for name in ("Pharmacist", "Cashier", "Employee", "Accountant"):
        role = AccessRole.objects.get(company=company, name=name)
        assert not [code for code in role.permissions if code.startswith("vision.")], name
