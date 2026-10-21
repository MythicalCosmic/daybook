"""The finance demo (`demo.seed`) builds a believable, consistent ledger."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core import demo_plan
from apps.finance import conf, demo, maintenance, queries, services
from apps.finance.models import Debt, MoneyAccount, Receipt, Transaction


@pytest.fixture
def seeded(company, demo_people):
    people = demo_people(company)
    now = timezone.now()
    demo.seed(company, people, now)
    demo.finish(company, people, now)  # as seed_demo does, after every app's demo
    return company


def test_the_demo_ledger_is_rich_and_consistent(seeded):
    company = seeded
    rows = Transaction.objects.filter(company=company)
    assert rows.count() > 250
    assert maintenance.verify_company(company, fix=False) == {"accounts": [], "debts": []}
    for account in MoneyAccount.objects.filter(company=company):
        assert account.balance >= 0 or account.allow_negative, account.name
    assert not MoneyAccount.objects.get(company=company, name="Asosiy bank hisobi").allow_negative
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
    # Distributors are the biggest expense: about 70 % of sales go on medicines.
    last_month = (today - timedelta(days=31), today - timedelta(days=1))
    month = queries.totals(company, *last_month, branch_ids=None)
    goods = -sum(
        rows.filter(
            occurred_on__range=last_month,
            category__parent__system_code="goods",
            kind__in=("expense", "debt_open"),
        ).values_list("amount", flat=True),
        Decimal(0),
    )
    assert Decimal("0.5") < goods / month["income"] < Decimal("0.9")


def test_no_account_ever_goes_below_zero_on_a_day(seeded):
    company = seeded
    today = queries.local_today(company)
    for account in MoneyAccount.objects.filter(company=company, allow_negative=False):
        day = today - timedelta(days=demo.DAYS)
        while day <= today:
            assert queries.balance(account, day) >= 0, (account.name, day)
            day += timedelta(days=3)


def test_night_pharmacists_are_paid_at_least_half_again_for_night_hours():
    """A 20:00 to 08:00 shift has 8 night hours of 11 worked: paid 1.5 times, a night
    pharmacist earns at least (3 + 8 x 1.5) / 11 of a day pharmacist's pay."""
    best_day_pay = max(
        demo.PAY[person.key]
        for person in demo_plan.PEOPLE
        if person.position == demo_plan.PHARMACIST and person.key not in demo.NIGHT
    )
    for key in demo.NIGHT:
        assert demo.PAY[key] >= best_day_pay * (3 + 8 * 1.5) / 11, key


def test_the_tills_weeks_are_left_to_the_sales_demo(company, demo_people):
    """With the sales module on, its demo books the last weeks' shifts: the ledger books its
    daily sales only for the days before, so no day is counted twice."""
    company.features = ["finance", "sales"]
    company.save(update_fields=["features"])
    people = demo_people(company)
    demo.seed(company, people, timezone.now())

    today = queries.local_today(company)
    first_till_day = today - timedelta(days=demo_plan.SALES_DAYS)
    days = set(
        Transaction.objects.filter(
            company=company, source_type=demo.DEMO_SOURCE, kind="income"
        ).values_list("occurred_on", flat=True)
    )
    assert days
    assert max(days) < first_till_day
    assert min(days) == today - timedelta(days=demo.DAYS - 1)


def test_the_books_close_only_when_every_demo_is_done(company, demo_people):
    people = demo_people(company)
    now = timezone.now()
    demo.seed(company, people, now)
    assert conf.get_settings(company).locked_until is None  # later demos still book older rows

    demo.finish(company, people, now)
    assert conf.get_settings(company).locked_until is not None


def test_the_demo_uses_the_safe_a_branch_already_has(company, demo_people):
    """Sales' defaults give each branch its safe before any demo runs."""
    people = demo_people(company)
    branch = company.branches.order_by("order", "pk").first()
    safe = services.account_for_branch(branch)

    demo.seed(company, people, timezone.now())

    safe.refresh_from_db()
    assert safe.name == f"Seyf: {branch.name}"
    assert safe.balance > 0
    assert MoneyAccount.objects.filter(company=company, kind="safe", branch=branch).count() == 1
    # Only invented names: the old demo's bank, drinks maker and internet provider are gone.
    names = " ".join(MoneyAccount.objects.filter(company=company).values_list("name", flat=True))
    assert "Kapitalbank" not in names


def test_the_distributors_books(company, demo_people):
    people = demo_people(company)
    small = {
        "owner": people["owner"],
        "manager": people["manager"],
        "worker": people["worker"],
        "cashier": people["madina"],
    }
    demo.seed_small(company, small, timezone.now())

    debts = Debt.objects.filter(company=company)
    assert debts.filter(direction="receivable").count() > 10
    assert debts.filter(direction="payable").exists()
    assert Transaction.objects.filter(company=company, category__system_code="salaries").exists()
    assert maintenance.verify_company(company, fix=False) == {"accounts": [], "debts": []}
