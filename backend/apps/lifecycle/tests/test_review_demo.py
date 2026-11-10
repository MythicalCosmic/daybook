"""The demo's reviews: Chilonzor's round for the last quarter is closed (everyone published, two
raises approved and in force from the 1st, a bonus approved, Otabek's improvement plan), and
Yunusobod's is still collecting the people's answers, three of them late.

The clock stands at 10:00 on Wednesday 11 November 2026 (Asia/Tashkent): both rounds review the
third quarter.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.companies.models import Feature
from apps.core.management.commands.ensure_company_defaults import ensure_company_defaults
from apps.core.management.commands.seed_demo import Command
from apps.hr.tests.conftest import local
from apps.inbox.models import Notification
from apps.lifecycle import demo, review_notify, review_queries, reviews
from apps.lifecycle.models import Review, ReviewCycle
from apps.members import demo as members_demo
from apps.members.models import Membership

pytestmark = pytest.mark.django_db

TODAY = date(2026, 11, 11)


def test_a_closed_round_and_one_still_answering(freeze, django_capture_on_commit_callbacks):
    from apps.payroll import queries as payroll_queries
    from apps.payroll import services as payroll
    from apps.payroll.models import Adjustment

    freeze(local(TODAY, 10, 0))
    now = timezone.now()
    company, people = Command()._build_pharmacy(now)
    company.features = list(Feature.values)
    company.save()
    ensure_company_defaults(company)
    members_demo.seed(company, people, now)
    staff = {m.first_name: m for m in Membership.objects.filter(company=company)}
    for name, amount in (("Sardor", "5600000"), ("Madina", "5800000")):
        payroll.set_pay(staff[name], by=None, effective_from=date(2025, 1, 1), amount=amount)
    with django_capture_on_commit_callbacks(execute=True):
        demo.finish(company, people, now)

    closed = ReviewCycle.objects.get(company=company, name="Chilonzor: 3-chorak, 2026")
    assert closed.status == "closed"
    assert (closed.period_start, closed.period_end) == (date(2026, 7, 1), date(2026, 9, 30))
    rows = list(closed.reviews.select_related("membership", "reviewer", "job_change"))
    assert rows and all(row.published_at and row.self_sent_at for row in rows)
    by_name = {row.membership.first_name: row for row in rows}
    assert by_name["Alisher"].reviewer.first_name == "Bekzod"
    assert by_name["Bekzod"].reviewer_id == people["owner"].pk
    assert by_name["Jasur"].acknowledged_at is None and by_name["Sardor"].acknowledged_at

    # The raises: approved by Dilnoza, in force from the 1st (5 600 000 + 10 % = 6 160 000).
    sardor = by_name["Sardor"]
    assert sardor.outcome == "raise" and sardor.job_change.status == "applied"
    pay = payroll_queries.compensation(staff["Sardor"], on=date(2026, 11, 1))
    assert pay.amount == Decimal("6160000")
    assert by_name["Madina"].job_change.status == "applied"
    bonus = Adjustment.objects.get(pk=by_name["Gulnora"].bonus_id)
    assert (bonus.kind, bonus.status, bonus.amount) == ("bonus", "approved", Decimal("500000"))
    plan = by_name["Otabek"]
    assert plan.outcome == "improvement_plan"
    assert [goal.status for goal in plan.goals.order_by("order")] == ["done", "open", "open"]
    assert all(row.kpis.get("taken_at") for row in rows)

    # Yunusobod: two sent, a draft, and the late ones; the reminder went out the day before.
    open_ = ReviewCycle.objects.get(company=company, status="self")
    assert open_.self_due_on == date(2026, 11, 9) and open_.self_reminded_on
    states = {
        row.membership.first_name: (row.self_sent_at is not None, row.self_saved_at is not None)
        for row in open_.reviews.select_related("membership")
    }
    assert states["Malika"] == (True, True) and states["Nigora"] == (True, True)
    assert states["Shahzoda"] == (False, True)
    assert "Kamola" not in states  # she joined after the quarter
    late = reviews.late(open_, open_.reviews.all(), today=TODAY)
    assert len(late) == 3
    dilshod = Notification.objects.filter(
        kind=review_notify.REVIEW, recipient__first_name="Dilshod"
    )
    assert dilshod.count() == 2  # the round opened, then the reminder
    results = review_queries.results(closed, rows, member=people["owner"])
    assert results["outcomes"]["raise"] == 2 and results["published"] == len(rows)
    assert Review.objects.filter(cycle=open_, published_at__isnull=False).count() == 0
