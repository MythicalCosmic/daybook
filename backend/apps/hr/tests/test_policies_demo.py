"""The demo's policies tell one story: three published policies with their versions, a draft,
a realistic mix of signed, waiting and late (every signature after its request and inside the
person's hours), the reminders and late notes those deadlines brought, and the director's order
attached as a PDF."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.companies.models import Feature
from apps.core.management.commands.ensure_company_defaults import ensure_company_defaults
from apps.core.management.commands.seed_demo import Command
from apps.hr import demo
from apps.hr.models import Policy, PolicyAcknowledgement
from apps.hr.policies import notify, queries
from apps.hr.tests.conftest import DAY, local
from apps.inbox.models import Notification
from apps.members import demo as members_demo

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
    return company, people


def tallies(company):
    policies = Policy.objects.filter(company=company).prefetch_related("positions", "branches")
    day = queries.today(company)
    return {p.title: queries.tally(p, branch_ids=None, day=day) for p in policies}


def test_three_policies_with_versions_and_a_mix_of_signatures(pharmacy):
    company, _people = pharmacy
    found = {p.title: p for p in Policy.objects.filter(company=company)}
    assert set(found) == {"Dori berish qoidalari", "Saqlash va harorat rejimi", "Kassa intizomi"}

    dispensing = found["Dori berish qoidalari"]
    assert dispensing.current_version.number == 2 == dispensing.ack_version.number
    assert queries.draft_of(dispensing).number == 3
    assert dispensing.current_version.file.name.endswith(".pdf")
    storage = found["Saqlash va harorat rejimi"]
    assert storage.current_version.number == 2 and storage.ack_version.number == 1
    assert storage.current_version.asks_again is False

    # Everyone of the story; the pharmacists who joined through a team link today are still
    # within their days.
    counts = tallies(company)
    newcomers = queries.audience(dispensing).filter(decided_at__date__gte=DAY).count()
    rules = counts["Dori berish qoidalari"]
    assert (rules.signed, rules.late, rules.waiting) == (9, 2, newcomers)
    assert counts["Saqlash va harorat rejimi"].late == 0
    assert (
        0 < counts["Saqlash va harorat rejimi"].signed < counts["Saqlash va harorat rejimi"].total
    )
    till = counts["Kassa intizomi"]
    assert (till.late, till.waiting) == (0, 2 + newcomers)

    # Every signature came after its request, and the late ones made their manager hear.
    for row in PolicyAcknowledgement.objects.filter(version__company=company).exclude(
        acknowledged_at=None
    ):
        assert row.acknowledged_at > row.asked_at
    assert Notification.objects.filter(company=company, kind=notify.POLICY_LATE).exists()
    assert AuditLog.objects.filter(company=company, action="hr.policy_signed").count() > 20
    # Sardor signed the storage rules after the typo fix: the text he read is version 2.
    sardor = PolicyAcknowledgement.objects.get(
        version=storage.ack_version, membership__first_name="Sardor"
    )
    assert sardor.signed_version.number == 2


def test_alisher_sees_what_to_sign_first(pharmacy):
    company, people = pharmacy
    standing = queries.mine(people["worker"], queries.today(company))
    states = {item.policy.title: item.state for item in standing}
    assert states == {
        "Dori berish qoidalari": queries.SIGNED,
        "Saqlash va harorat rejimi": queries.WAITING,
        "Kassa intizomi": queries.SIGNED,
    }
    waiting = next(item for item in standing if item.state == queries.WAITING)
    assert waiting.due_on == queries.today(company) + timedelta(days=4)
    assert standing[0].state == queries.WAITING  # what to sign comes first
