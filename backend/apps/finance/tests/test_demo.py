"""The finance demo (`demo.seed`) builds a believable, consistent ledger."""

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.finance import conf, demo, maintenance, queries
from apps.finance.models import Debt, MoneyAccount, Receipt, Transaction


@pytest.fixture
def seeded(company, demo_people):
    people = demo_people(company)
    demo.seed(company, people, timezone.now())
    return company


def test_the_demo_ledger_is_rich_and_consistent(seeded):
    company = seeded
    rows = Transaction.objects.filter(company=company)
    assert rows.count() > 250
    assert maintenance.verify_company(company, fix=False) == {"accounts": [], "debts": []}
    for account in MoneyAccount.objects.filter(company=company):
        assert account.balance >= 0 or account.allow_negative, account.name
    today = queries.local_today(company)
    totals = queries.totals(company, today - timezone.timedelta(days=30), today, branch_ids=None)
    assert totals["income"] > 0
    assert totals["expense"] > 0
    assert Debt.objects.filter(company=company, status=Debt.Status.OPEN).count() >= 8
    assert Debt.objects.filter(company=company, kind=Debt.Kind.ADVANCE).exists()
    assert queries.overdue_count(company, branch_ids=None, today=today) >= 3
    assert rows.filter(currency="USD").exists()
    assert rows.filter(kind=Transaction.Kind.FX).exists()
    assert rows.filter(status=Transaction.Status.PENDING).count() == 1
    assert rows.filter(status=Transaction.Status.VOID).exists()
    assert Receipt.objects.filter(company=company).count() >= 4
    assert conf.get_settings(company).locked_until is not None
    cash = queries.cash_position(company, None, branch_ids=None, today=today)
    assert cash["total"] > Decimal("100000000")
