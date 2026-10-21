"""The demo seeds believable sales without breaking any rule of the ledger."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Sum
from django.utils import timezone

from apps.companies.models import Branch
from apps.finance.models import LIVE_STATUSES, MoneyAccount, Transaction
from apps.members.permissions import Perm
from apps.sales import demo
from apps.sales.models import CashMovement, CashShift, DailySales, SalesTarget


def test_demo_seeds_shifts_and_keeps_the_ledger_in_step(company, demo_people):
    company.features = ["finance", "sales"]
    company.save(update_fields=["features"])
    Branch.objects.create(company=company, name="Yunusobod", code="YNS", order=1)
    people = demo_people(company)
    # In shop hours, so today's tills are open too.
    day = timezone.localdate(timezone=ZoneInfo(company.timezone))
    demo.seed(
        company,
        people,
        datetime(day.year, day.month, day.day, 14, 0, tzinfo=ZoneInfo(company.timezone)),
    )

    shifts = CashShift.objects.filter(company=company)
    assert shifts.filter(status=CashShift.Status.OPEN).count() >= 1
    # Whoever runs a till in the story can open Kassa in the mini app.
    for key in ("madina", "jasur", "nigora"):
        people[key].refresh_from_db()
        assert people[key].has_perm(Perm.SALES_OPERATE), key
    assert shifts.filter(status=CashShift.Status.VERIFIED).count() > 20
    assert shifts.filter(status=CashShift.Status.CLOSED).exists()  # waiting in Needs you
    assert shifts.filter(ai_mismatch=True).count() == 1
    assert DailySales.objects.filter(company=company).count() > 20
    assert SalesTarget.objects.filter(company=company).exists()
    assert CashMovement.objects.filter(
        company=company, kind="handover", confirmed_at__isnull=True
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
