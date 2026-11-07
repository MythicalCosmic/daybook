"""members/0017 (docs/PLAN-LEARNING.md §8): every role that manages routines gains
`learning.view` and `learning.manage`; run against today's models."""

import importlib

import pytest
from django.apps import apps as django_apps

from apps.members.models import AccessRole

pytestmark = pytest.mark.django_db

MIGRATION = importlib.import_module("apps.members.migrations.0017_learning_permissions")


def run():
    MIGRATION.give_learning(django_apps, None)


def test_routine_managers_gain_learning_once(company):
    manager = AccessRole.objects.get(company=company, name="Manager")
    manager.permissions = [p for p in manager.permissions if not p.startswith("learning.")]
    manager.save()
    head = AccessRole.objects.create(
        company=company, name="Head", permissions=["tasks.templates", "learning.view"]
    )
    office = AccessRole.objects.create(company=company, name="Office", permissions=["tasks.assign"])

    run()
    run()  # a second run adds nothing

    manager.refresh_from_db()
    head.refresh_from_db()
    office.refresh_from_db()
    assert manager.permissions[-2:] == ["learning.view", "learning.manage"]
    assert manager.permissions.count("learning.manage") == 1
    assert head.permissions == ["tasks.templates", "learning.view", "learning.manage"]
    assert office.permissions == ["tasks.assign"]
