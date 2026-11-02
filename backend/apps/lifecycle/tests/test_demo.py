"""The demo's discipline story: a verbal warning for lateness, confirmed and explained, and a
written warning for a storage breach waiting to be read (its fine goes to payroll when payroll
is there); Bobur's suspension from the members demo is listed with its reason."""

from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.companies.models import Feature
from apps.core.management.commands.ensure_company_defaults import ensure_company_defaults
from apps.core.management.commands.seed_demo import Command
from apps.hr.tests.conftest import DAY, local
from apps.inbox.models import Notification
from apps.lifecycle import demo, queries
from apps.lifecycle.models import DisciplinaryRecord
from apps.members import demo as members_demo

pytestmark = pytest.mark.django_db


def build(freeze):
    freeze(local(DAY, 10, 0))
    now = timezone.now()
    company, people = Command()._build_pharmacy(now)
    company.features = list(Feature.values)
    company.save()
    ensure_company_defaults(company)
    members_demo.seed(company, people, now)
    demo.seed(company, people, now)
    return company, people


def test_two_records_and_a_suspension(freeze):
    company, people = build(freeze)

    lateness = DisciplinaryRecord.objects.get(membership=people["jasur"])
    assert (lateness.kind, lateness.category, lateness.status) == (
        "verbal_warning",
        "lateness",
        "acknowledged",
    )
    assert lateness.employee_response
    fridge = DisciplinaryRecord.objects.get(membership=people["worker"])
    assert (fridge.kind, fridge.category, fridge.read_at) == (
        "written_warning",
        "storage_breach",
        None,
    )
    assert fridge.fine_id is None  # payroll isn't on this branch
    assert Notification.objects.filter(recipient=people["worker"], kind="lifecycle.record").exists()
    assert Notification.objects.filter(
        recipient=people["manager"], kind="lifecycle.explanation"
    ).exists()
    [suspended] = queries.suspended(company, branch_ids=None)
    assert suspended["reason"] and suspended["member"].first_name == "Bobur"


def test_with_payroll_the_written_warning_carries_a_fine(freeze, monkeypatch):
    monkeypatch.setattr(
        "apps.payroll.services.propose_fine",
        lambda membership, **kwargs: SimpleNamespace(pk=4040),
        raising=False,
    )

    _company, people = build(freeze)

    assert DisciplinaryRecord.objects.get(membership=people["worker"]).fine_id == 4040
