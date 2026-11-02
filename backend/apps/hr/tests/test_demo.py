"""The demo seeds a believable HR story (v4 scope: profiles for everyone, two medical books
expiring within 30 days and one expired, a fixed-term contract ending in three weeks, a
probation ending in five days), built on the members demo's people."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.companies.models import Feature
from apps.core.management.commands.ensure_company_defaults import ensure_company_defaults
from apps.core.management.commands.seed_demo import Command
from apps.hr import demo, queries
from apps.hr.models import Contract, EmployeeProfile
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
    assert [doc.expires_on >= day for doc in expiring].count(True) == 2
    assert {doc.kind for doc in expiring} == {"medical_book"}

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
