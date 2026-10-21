"""The demo seeds believable sales without breaking any rule of the ledger."""

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.db.models import Sum
from django.utils import timezone

from apps.companies.models import Feature
from apps.core import demo_plan
from apps.core.management.commands.ensure_company_defaults import ensure_company_defaults
from apps.core.management.commands.seed_demo import Command
from apps.finance.models import LIVE_STATUSES, MoneyAccount, Transaction
from apps.members.permissions import Perm
from apps.sales import demo, queries
from apps.sales.models import CashMovement, CashShift, DailySales, SalesTarget, ShiftPayment

pytestmark = pytest.mark.django_db


@pytest.fixture
def pharmacy():
    """Demo Dorixona's people as seed_demo makes them, then this demo at 14:00."""
    zone = ZoneInfo("Asia/Tashkent")
    day = timezone.localdate(timezone=zone)
    now = datetime(day.year, day.month, day.day, 14, 0, tzinfo=zone)
    company, people = Command()._build_pharmacy(now)
    company.features = [Feature.FINANCE, Feature.SALES]
    company.save(update_fields=["features"])
    ensure_company_defaults(company)
    demo.seed(company, people, now)
    return company, people, now


def test_demo_seeds_shifts_and_keeps_the_ledger_in_step(pharmacy):
    company, people, now = pharmacy
    shifts = CashShift.objects.filter(company=company)
    assert shifts.filter(status=CashShift.Status.OPEN).count() >= 1  # Chilonzor and Yunusobod
    # Whoever runs a till in the story can open Kassa in the mini app; the courier doesn't.
    for key in ("worker", "madina", "nigora"):
        people[key].refresh_from_db()
        assert people[key].has_perm(Perm.SALES_OPERATE), key
    assert not people["jasur"].has_perm(Perm.SALES_OPERATE)
    assert shifts.filter(status=CashShift.Status.VERIFIED).count() > 40
    assert shifts.filter(status=CashShift.Status.CLOSED).exists()  # waiting in Needs you
    assert shifts.filter(ai_mismatch=True).count() == 1
    assert DailySales.objects.filter(company=company).count() > 30
    assert SalesTarget.objects.filter(company=company).exists()
    assert CashMovement.objects.filter(
        company=company, kind="handover", confirmed_at__isnull=True, voided_at__isnull=True
    ).exists()

    # Every till's cached balance equals the sum of its posted rows.
    for account in MoneyAccount.objects.filter(company=company):
        posted = Transaction.objects.filter(account=account, status="posted").aggregate(
            t=Sum("amount")
        )["t"]
        assert account.balance == (posted or Decimal(0)), account.name
    # Every closed shift booked its sales on its business day.
    for shift in shifts.exclude(status=CashShift.Status.OPEN)[:10]:
        rows = Transaction.objects.filter(
            source_type="sales.cashshift", source_id=shift.pk, status__in=LIVE_STATUSES
        )
        assert rows.exists()
        assert set(rows.values_list("occurred_on", flat=True)) == {shift.business_day}

    # The tills follow the roster, and the numbers are a pharmacy's (one seeding: it's slow).
    story = demo_plan.Plan(company, people, now)
    shifts = shifts.select_related("cashier", "branch")
    for shift in shifts:
        key = story.key_of(shift.cashier)
        assert story.shift(key, shift.business_day) is not None, (key, shift.business_day)
    # Yunusobod's till has a night session; Chilonzor closes at 22:00.
    hours = {
        (shift.branch.code, story.local(shift.opened_at).hour)
        for shift in shifts.exclude(status=CashShift.Status.OPEN)
    }
    assert ("YNS", 20) in hours and ("YNS", 8) in hours
    assert not [hour for code, hour in hours if code == "CHL" and hour >= 20]
    # Medicines sold aren't taken back: no refunds.
    payments = ShiftPayment.objects.filter(shift__company=company)
    assert not payments.exclude(refunds=0).exists()
    # About 40 % cash, receipts of about 55 000 so‘m.
    total = payments.aggregate(t=Sum("sales"))["t"]
    cash = payments.filter(method__system_code="cash").aggregate(t=Sum("sales"))["t"]
    assert Decimal("0.32") < cash / total < Decimal("0.48")
    closed = shifts.exclude(status=CashShift.Status.OPEN)
    receipts = closed.aggregate(r=Sum("receipts"))["r"]
    assert 45_000 < total / receipts < 66_000

    # Every widget of the cash and cashier pages has something: Monday evenings the bank's
    # collector takes the takings, Chilonzor (open from 08:00) once opened late, and the
    # personal target belongs to someone who runs a till.
    assert CashMovement.objects.filter(company=company, kind="to_bank").exists()
    since = story.today - timedelta(days=demo.DAYS)
    cashiers = queries.cashier_scorecard(company, since, story.today, branch_ids=None)
    assert any(row["late_opens"] for row in cashiers)
    target = SalesTarget.objects.get(company=company, membership__isnull=False)
    assert CashShift.objects.filter(company=company, cashier=target.membership).exists()
