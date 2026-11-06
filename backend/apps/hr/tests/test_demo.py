"""The demo seeds a believable HR story (v4 scope: profiles for everyone, two medical books
expiring within 30 days and one expired, a fixed-term contract ending in three weeks, a
probation ending in five days), built on the members demo's people."""

from datetime import time, timedelta

import pytest
from django.utils import timezone

from apps.companies.models import Feature
from apps.core import demo_plan as plan
from apps.core.management.commands.ensure_company_defaults import ensure_company_defaults
from apps.core.management.commands.seed_demo import Command
from apps.hr import conf, coverage, demo, queries, services
from apps.hr.models import Contract, EmployeeDocument, EmployeeProfile
from apps.hr.tests.conftest import DAY, local
from apps.members import demo as members_demo
from apps.members.models import Membership

pytestmark = pytest.mark.django_db


@pytest.fixture
def pharmacy(freeze):
    freeze(local(DAY, 10, 0))
    now = timezone.now()
    company, people = Command()._build_pharmacy(now)
    company.features = list(Feature.values)
    company.save()
    ensure_company_defaults(company)
    members_demo.seed(company, people, now)
    demo.seed(company, people, now)
    demo.finish(company, people, now)
    return company, people


def test_everyone_has_a_profile_and_the_story_holds(pharmacy):
    company, people = pharmacy
    employed = Membership.objects.filter(company=company).exclude(
        status__in=(Membership.Status.PENDING, Membership.Status.REJECTED)
    )
    assert EmployeeProfile.objects.filter(company=company).count() == employed.count()
    alisher = EmployeeProfile.objects.get(membership=people["worker"])
    assert len(alisher.pinfl) == 14 and alisher.passport.startswith("AD")
    assert alisher.payout_method == "card" and alisher.emergency_contacts.count() == 1

    day = queries.today(company)
    expiring = list(queries.expiring_documents(company, branch_ids=None, day=day, within=30))
    assert [doc.expires_on < day for doc in expiring].count(True) == 1
    assert [doc.expires_on >= day for doc in expiring].count(True) == 3
    assert {doc.kind for doc in expiring} == {"medical_book", "pharmacist_certificate"}
    certificate = next(doc for doc in expiring if doc.kind == "pharmacist_certificate")
    assert (certificate.expires_on - day).days == 20

    ending = list(queries.ending_contracts(company, branch_ids=None, day=day, within=30))
    assert [(c.membership, c.ends_on) for c in ending] == [(people["jasur"], day + timedelta(21))]
    probation = list(queries.probation_endings(company, branch_ids=None, day=day, within=7))
    assert [c.probation_until for c in probation] == [day + timedelta(days=5)]
    printed = Contract.objects.filter(company=company).exclude(file="")
    assert printed.count() == 2 and all(c.pdf_generated_at for c in printed)
    assert Contract.objects.filter(company=company, status="terminated").exists()
    totals = queries.compliance(company, branch_ids=None, day=day)["totals"]
    assert totals["missing"] >= 1 and totals["expired"] == 1


def test_hr_heard_about_it_this_morning(pharmacy):
    company, _people = pharmacy
    from apps.inbox.models import Notification

    kinds = set(Notification.objects.filter(company=company).values_list("kind", flat=True))
    assert {"hr.document_expiring", "hr.contract_ending", "hr.probation_ending"} <= kinds
    assert "hr.my_document" in kinds


def test_the_pharmacists_are_chosen_and_qualified(pharmacy):
    company, _people = pharmacy
    settings = conf.get_settings(company)
    names = set(settings.pharmacist_positions.values_list("name", flat=True))
    assert names == {plan.HEAD, plan.SENIOR, plan.PHARMACIST}
    day = queries.today(company)
    staff = queries.qualified_staff(company, branch_ids=None, day=day)
    # Everyone qualified today; the Saturday night pharmacist's renewed certificate waits.
    assert staff and all(row["qualified"] for row in staff)
    unverified = EmployeeDocument.objects.filter(
        company=company, kind="pharmacist_certificate", verified_at__isnull=True
    )
    assert unverified.count() == 1


@pytest.fixture
def rostered(freeze):
    """The pharmacy with its roster (attendance's demo) under HR's story."""
    from apps.attendance import demo as attendance_demo

    freeze(local(DAY, 10, 0))
    now = timezone.now()
    company, people = Command()._build_pharmacy(now)
    company.features = list(Feature.values)
    company.save()
    ensure_company_defaults(company)
    members_demo.seed(company, people, now)
    attendance_demo.seed(company, people, now)
    demo.seed(company, people, now)
    demo.finish(company, people, now)
    return company, people, now


def test_next_saturday_night_at_yunusobod_shows_a_coverage_gap(rostered):
    company, people, now = rostered
    story = plan.Plan(company, people, now)
    saturday, key = demo.saturday_night(story)
    yunusobod = story.branches["Y"]
    night = (story.at(saturday, time(20)), story.at(saturday + timedelta(days=1), time(8)))

    gaps = coverage.planned_gaps(company, saturday, saturday + timedelta(days=1), branch_ids=None)
    assert [(gap.branch_id, gap.start, gap.end) for gap in gaps if gap.start == night[0]] == [
        (yunusobod.pk, *night)
    ]
    chilonzor = story.branches["C"]
    assert not [
        gap
        for gap in coverage.planned_gaps(company, story.today, saturday, branch_ids=[chilonzor.pk])
    ]
    from apps.inbox.models import Notification

    assert Notification.objects.filter(company=company, kind="hr.coverage_gap_planned").exists()

    renewed = EmployeeDocument.objects.get(
        membership=story.member(key), kind="pharmacist_certificate", verified_at__isnull=True
    )
    services.verify_document(renewed, by=people["owner"])
    after = coverage.planned_gaps(company, saturday, saturday + timedelta(days=1), branch_ids=None)
    assert not [gap for gap in after if gap.start == night[0]]
