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
    from apps.payroll.models import Adjustment

    fine = Adjustment.objects.get(pk=fridge.fine_id)  # the storage breach's fine, in payroll
    assert (fine.kind, fine.source, fine.membership_id) == (
        "fine",
        "discipline",
        people["worker"].pk,
    )
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


def test_leaving_and_job_changes(freeze, django_capture_on_commit_callbacks):
    from datetime import date

    from apps.lifecycle.models import JobChange, Termination
    from apps.members.models import Membership, Position

    company, people = build(freeze)
    with django_capture_on_commit_callbacks(execute=True):
        demo.finish(company, people, timezone.now())

    # Nodira left last month: asked, agreed, everything handed over, her answers.
    nodira = Membership.objects.get(company=company, first_name="Nodira")
    left = Termination.objects.get(membership=nodira)
    assert left.status == "completed" and left.left_on == date(2026, 10, 2)
    assert left.exit_interview["reason"] == "moving" and left.rehire == "yes"
    assert all(item.done for item in left.handover.all())
    assert [event["kind"] for event in left.events] == ["requested", "agreed", "completed"]

    # Jasur leaves on Friday next week; the keys are back, the rest is still open.
    leaving = Termination.objects.get(membership=people["jasur"])
    assert leaving.status == "agreed" and leaving.last_day == date(2026, 10, 30)
    assert leaving.agreed_by_id == people["owner"].pk and leaving.exit_interview
    items = {item.kind: item for item in leaving.handover.all()}
    assert items["keys"].done and not items["documents"].done
    assert leaving.handover.filter(title=demo.JASUR_ITEM).exists()
    assert Notification.objects.filter(recipient=people["jasur"], kind="lifecycle.leaving").exists()

    # Gulnora's promotion took effect on the 1st; her pay follows on the 1st of next month;
    # Shahzoda's move waits for approval.
    gulnora = Membership.objects.get(company=company, first_name="Gulnora")
    senior = Position.objects.get(company=company, name="Senior pharmacist")
    assert gulnora.position_id == senior.pk
    changes = {change.status: change for change in JobChange.objects.filter(company=company)}
    assert changes["applied"].membership_id == gulnora.pk
    assert changes["applied"].effective_on == date(2026, 10, 1)
    assert changes["approved"].parts == ["pay"]
    assert changes["approved"].effective_on == date(2026, 11, 1)
    assert changes["proposed"].membership.first_name == "Shahzoda"
    assert changes["proposed"].parts == ["branch"]
