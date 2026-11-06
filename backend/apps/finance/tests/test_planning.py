"""Upcoming payments, the cash forecast, budgets with their alerts, payables paid several at
once, and credit notes (Package I, §11.4 and §14.8 acceptance)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.core.exceptions import DomainError
from apps.finance import budgets, planning, queries, recurring, services
from apps.finance.models import Budget, Category, Debt, MoneyAccount, Transaction
from apps.finance.sources import Source
from apps.finance.tests.factories import CounterpartyFactory
from apps.inbox.models import Notification
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db


def url(company, path: str) -> str:
    return f"/api/v1/owner/companies/{company.pk}/finance/{path}"


@pytest.fixture
def boss(fin, member):
    return member(fin, "Owner", first_name="Dilnoza")


@pytest.fixture
def kassa(fin):
    return MoneyAccount.objects.get(company=fin, kind=MoneyAccount.Kind.CASH)


@pytest.fixture
def today(fin):
    return queries.local_today(fin)


def deposit(company, by, account, amount, day, **fields):
    return services.record_transaction(
        company,
        by=by,
        kind="income",
        amount=Decimal(amount),
        occurred_on=day,
        account=account,
        category="sales",
        **fields,
    )


def spend(company, by, account, amount, day, category="rent", **fields):
    return services.record_transaction(
        company,
        by=by,
        kind="expense",
        amount=Decimal(amount),
        occurred_on=day,
        account=account,
        category=category,
        **fields,
    )


def payable(company, by, party, amount, issued_on, due_on, category="goods", **fields):
    return services.open_debt(
        company,
        by=by,
        direction="payable",
        kind="trade",
        amount=amount,
        currency="UZS",
        issued_on=issued_on,
        due_on=due_on,
        counterparty=party,
        category=category,
        **fields,
    )


# Upcoming ---------------------------------------------------------------------------------------


def test_upcoming_lists_bills_taxes_payables_receivables_and_pay(fin, boss, kassa, today):
    rent = Category.objects.get(company=fin, system_code="rent")
    recurring.create_rule(
        fin,
        by=boss,
        name="Ijara",
        kind="expense",
        mode="bill",
        frequency="monthly",
        day=(today + timedelta(days=3)).day,
        category=rent,
        amount="12000000",
        starts_on=today,
    )
    distributor = CounterpartyFactory(company=fin, name="Oqtosh Med Ta’minot", kind="supplier")
    late = payable(
        fin, boss, distributor, "5000000", today - timedelta(days=20), today - timedelta(days=2)
    )
    clinic = CounterpartyFactory(company=fin, name="Shifo klinikasi")
    services.open_debt(
        fin,
        by=boss,
        direction="receivable",
        kind="trade",
        amount="3000000",
        currency="UZS",
        issued_on=today,
        due_on=today + timedelta(days=10),
        counterparty=clinic,
        category="sales",
    )
    worker = boss.company.memberships.exclude(pk=boss.pk).first()
    services.open_debt(
        fin,
        by=boss,
        direction="payable",
        kind="salary",
        amount="4500000",
        currency="UZS",
        issued_on=today,
        membership=boss,
        category="salaries",
    )

    data = planning.upcoming(fin, 30, branch_ids=None, today=today)

    kinds = [item["kind"] for item in data["items"]]
    assert kinds[0] == "payable" and data["items"][0]["overdue"] is True  # overdue first
    assert data["items"][0]["debt_id"] == late.pk
    assert {"bill", "payable", "receivable", "payroll"} <= set(kinds)
    pay = next(item for item in data["items"] if item["kind"] == "payroll")
    assert pay["title"] == "Pay and expenses owed to the team"
    assert "Dilnoza" not in pay["subtitle"]  # never per person
    assert data["totals"]["out"] == "21500000.00"
    assert data["totals"]["in"] == "3000000.00"
    assert data["totals"]["overdue_out"] == "5000000.00"
    assert worker is None or worker.pk != boss.pk


def test_upcoming_endpoint_and_its_permission(fin, boss, owner_api, role, person):
    assert owner_api(boss).get(url(fin, "upcoming/?days=60")).json()["days"] == 60
    assert owner_api(boss).get(url(fin, "upcoming/?days=500")).status_code == 400
    recorder = person(fin, role(fin, "Recorder", [Perm.FINANCE_RECORD]))
    assert owner_api(recorder).get(url(fin, "upcoming/")).status_code == 403


# The forecast -----------------------------------------------------------------------------------


def test_the_forecast_finds_the_low_point_and_the_day_below_zero(fin, boss, kassa, today):
    # Eight weeks of history: 1 000 000 in and 400 000 out a day, on average.
    first = today - timedelta(days=56)
    for offset in range(56):
        day = first + timedelta(days=offset)
        deposit(fin, boss, kassa, "1000000", day)
        spend(fin, boss, kassa, "400000", day, category="utilities")
    # Cash now: 56 times 600 000 = 33 600 000. A 50 000 000 distributor bill falls due in 10 days.
    distributor = CounterpartyFactory(company=fin, name="Tolzor Farm Savdo", kind="supplier")
    due = today + timedelta(days=10)
    payable(fin, boss, distributor, "50000000", today, due)

    data = planning.forecast(fin, 30, branch_ids=None, today=today)

    assert data["start"] == "33600000.00"
    assert data["basis"] == {
        "daily_in": "1000000.00",
        "daily_out": "400000.00",
        "days_observed": 56,
    }
    assert len(data["points"]) == 31
    # Day 10: 33.6 M + 10 times 0.6 M - 50 M = -10.4 M; the lowest point, the first below zero.
    assert data["below_zero_on"] == due.isoformat()
    assert data["low"] == {"date": due.isoformat(), "balance": "-10400000.00"}
    assert (
        data["end"]
        == str(Decimal("33600000") + 30 * Decimal("600000") - Decimal("50000000")) + ".00"
    )
    assert data["events"] == [
        {
            "date": due.isoformat(),
            "title": "Tolzor Farm Savdo",
            "amount": "50000000.00",
            "direction": "out",
        }
    ]


def test_the_forecast_never_counts_an_overdue_receivable(fin, boss, kassa, today):
    deposit(fin, boss, kassa, "1000000", today)
    clinic = CounterpartyFactory(company=fin, name="Shifo klinikasi")
    services.open_debt(
        fin,
        by=boss,
        direction="receivable",
        kind="trade",
        amount="9000000",
        currency="UZS",
        issued_on=today - timedelta(days=40),
        due_on=today - timedelta(days=10),
        counterparty=clinic,
        category="sales",
    )

    data = planning.forecast(fin, 30, branch_ids=None, today=today)

    assert data["events"] == []
    assert data["below_zero_on"] is None


def test_forecast_endpoint(fin, boss, owner_api):
    body = owner_api(boss).get(url(fin, "reports/forecast/?days=60")).json()

    assert body["days"] == 60 and len(body["points"]) == 61
    assert body["low"]["balance"] == "0.00"


# Budgets ----------------------------------------------------------------------------------------


def test_budgets_against_the_pnl_actuals_with_children(fin, boss, kassa, today):
    marketing = Category.objects.get(company=fin, system_code="marketing")
    flyers = services.create_category(fin, by=boss, name="Flyers", kind="expense", parent=marketing)
    month = today.replace(day=1)
    deposit(fin, boss, kassa, "10000000", today)
    spend(fin, boss, kassa, "1000000", today, category=marketing)
    spend(fin, boss, kassa, "500000", today, category=flyers)

    budgets.set_budgets(
        fin, by=boss, month=month, rows=[(marketing, "2000000"), (flyers, "400000")]
    )

    view = budgets.month_view(fin, month, branch_ids=None, today=today)
    rows = {row["category"]["id"]: row for row in view["rows"]}
    assert rows[marketing.pk]["actual"] == "1500000.00"  # its own rows and its children's
    assert (rows[marketing.pk]["share"], rows[marketing.pk]["status"]) == ("0.75", "ok")
    assert (rows[flyers.pk]["share"], rows[flyers.pk]["status"]) == ("1.25", "over")
    assert rows[flyers.pk]["category"]["parent_id"] == marketing.pk
    rent = Category.objects.get(company=fin, system_code="rent")
    assert rows[rent.pk]["status"] == "none"
    assert view["totals"] == {"budget": "2000000.00", "actual": "1500000.00"}


def test_budget_alerts_go_once_per_threshold(
    fin, boss, kassa, today, django_capture_on_commit_callbacks
):
    transport = Category.objects.get(company=fin, system_code="transport")
    month = today.replace(day=1)
    deposit(fin, boss, kassa, "10000000", today)
    budgets.set_budgets(fin, by=boss, month=month, rows=[(transport, "1000000")])

    def pay(amount):  # the check runs once the expense commits
        with django_capture_on_commit_callbacks(execute=True):
            spend(fin, boss, kassa, amount, today, category="transport")

    pay("700000")  # 70 %: nothing
    assert not Notification.objects.filter(kind="finance.budget").exists()

    pay("120000")  # 82 %: the 80 % alert
    [alert] = Notification.objects.filter(kind="finance.budget")
    assert alert.title.startswith("Transport: 82% of the")
    assert alert.recipient_id == boss.pk

    pay("10000")  # 83 %: no second alert
    assert budgets.check(fin, month) == 0
    assert Notification.objects.filter(kind="finance.budget").count() == 1

    pay("200000")  # 103 %: the 100 % alert
    assert Notification.objects.filter(kind="finance.budget").count() == 2
    assert budgets.check(fin, month) == 0
    budget = Budget.objects.get(category=transport, month=month)
    assert budget.alerted_80_at and budget.alerted_100_at


def test_a_new_budget_amount_may_alert_again(
    fin, boss, kassa, today, django_capture_on_commit_callbacks
):
    transport = Category.objects.get(company=fin, system_code="transport")
    month = today.replace(day=1)
    deposit(fin, boss, kassa, "10000000", today)
    budgets.set_budgets(fin, by=boss, month=month, rows=[(transport, "1000000")])
    with django_capture_on_commit_callbacks(execute=True):
        spend(fin, boss, kassa, "900000", today, category="transport")
    assert Notification.objects.filter(kind="finance.budget").count() == 1

    with django_capture_on_commit_callbacks(execute=True):
        budgets.set_budgets(fin, by=boss, month=month, rows=[(transport, "1100000")])

    assert Notification.objects.filter(kind="finance.budget").count() == 2  # 82 % of the new one


def test_copy_last_month(fin, boss, today):
    month = today.replace(day=1)
    last = (month - timedelta(days=1)).replace(day=1)
    rent = Category.objects.get(company=fin, system_code="rent")
    utilities = Category.objects.get(company=fin, system_code="utilities")
    budgets.set_budgets(fin, by=boss, month=last, rows=[(rent, "12000000"), (utilities, "900000")])
    budgets.set_budgets(fin, by=boss, month=month, rows=[(rent, "13000000")])

    assert budgets.copy_budgets(fin, by=boss, month=month) == 1

    amounts = dict(
        Budget.objects.filter(month=month).values_list("category__system_code", "amount")
    )
    assert amounts == {"rent": Decimal("13000000.00"), "utilities": Decimal("900000.00")}


def test_budgets_api(fin, boss, owner_api, role, person, today):
    client = owner_api(boss)
    rent = Category.objects.get(company=fin, system_code="rent")
    month = f"{today:%Y-%m}"

    body = client.put(
        url(fin, "budgets/"),
        {"month": month, "rows": [{"category": rent.pk, "amount": "12000000"}]},
        format="json",
    )
    assert body.status_code == 200, body.content
    row = next(r for r in body.json()["rows"] if r["category"]["id"] == rent.pk)
    assert row["budget"] == "12000000.00"
    removed = client.put(
        url(fin, "budgets/"),
        {"month": month, "rows": [{"category": rent.pk, "amount": None}]},
        format="json",
    )
    assert (
        next(r for r in removed.json()["rows"] if r["category"]["id"] == rent.pk)["budget"] is None
    )
    assert (
        client.post(url(fin, "budgets/copy/"), {"month": month}, format="json").status_code == 200
    )
    assert client.get(url(fin, "budgets/?month=2026-13")).status_code == 400

    viewer = owner_api(person(fin, role(fin, "Viewer", [Perm.FINANCE_VIEW])))
    assert viewer.get(url(fin, f"budgets/?month={month}")).status_code == 200
    assert (
        viewer.put(url(fin, "budgets/"), {"month": month, "rows": []}, format="json").status_code
        == 403
    )


# Payables and credit notes ----------------------------------------------------------------------


def test_payables_are_grouped_and_three_are_paid_in_one_action(fin, boss, owner_api, kassa, today):
    deposit(fin, boss, kassa, "50000000", today)
    oqtosh = CounterpartyFactory(company=fin, name="Oqtosh Med Ta’minot", kind="supplier")
    tolzor = CounterpartyFactory(company=fin, name="Tolzor Farm Savdo", kind="supplier")
    one = payable(
        fin, boss, oqtosh, "4000000", today - timedelta(days=40), today - timedelta(days=3)
    )
    two = payable(
        fin, boss, oqtosh, "6000000", today - timedelta(days=10), today + timedelta(days=4)
    )
    three = payable(fin, boss, tolzor, "3000000", today, today + timedelta(days=30))
    client = owner_api(boss)

    body = client.get(url(fin, "payables/")).json()
    assert [group["counterparty"]["name"] for group in body["groups"]] == [
        "Oqtosh Med Ta’minot",
        "Tolzor Farm Savdo",
    ]
    assert [d["bucket"] for d in body["groups"][0]["debts"]] == ["overdue", "week"]
    assert body["totals"] == {
        "overdue": "4000000.00",
        "week": "6000000.00",
        "later": "3000000.00",
        "all": "13000000.00",
    }

    paid = client.post(
        url(fin, "payables/pay/"),
        {
            "account": kassa.pk,
            "paid_on": today.isoformat(),
            "debts": [
                {"id": one.pk, "amount": "4000000"},
                {"id": two.pk, "amount": "2000000"},
                {"id": three.pk, "amount": "3000000"},
            ],
        },
        format="json",
    )

    assert paid.status_code == 201, paid.content
    assert len(paid.json()["paid"]) == 3
    assert paid.json()["warnings"] == []  # bought on credit by hand, not a goods receipt
    rows = Transaction.objects.filter(kind="debt_payment", company=fin)
    assert rows.count() == 3
    from apps.audit.models import AuditLog

    assert AuditLog.objects.filter(action="finance.debt_paid").count() == 3
    one.refresh_from_db()
    two.refresh_from_db()
    assert (one.status, two.paid) == ("paid", Decimal("2000000.00"))
    kassa.refresh_from_db()
    assert kassa.balance == Decimal("41000000.00")


def test_paying_payables_is_all_or_nothing(fin, boss, owner_api, kassa, today):
    deposit(fin, boss, kassa, "50000000", today)
    party = CounterpartyFactory(company=fin, name="Chinorbek Pharma Logistika", kind="supplier")
    one = payable(fin, boss, party, "1000000", today, today)
    two = payable(fin, boss, party, "1000000", today, today)

    response = owner_api(boss).post(
        url(fin, "payables/pay/"),
        {
            "account": kassa.pk,
            "paid_on": today.isoformat(),
            "debts": [{"id": one.pk, "amount": "1000000"}, {"id": two.pk, "amount": "5000000"}],
        },
        format="json",
    )

    assert response.status_code == 400
    one.refresh_from_db()
    assert one.paid == 0
    assert not Transaction.objects.filter(kind="debt_payment").exists()


def test_the_cash_warning_shows_for_a_goods_receipt_payable_and_not_for_rent(
    fin, boss, kassa, today, src
):
    from apps.finance import payables

    party = CounterpartyFactory(company=fin, name="Ko‘kterak Farm Distribyutor", kind="supplier")
    goods = payable(fin, boss, party, "1000000", today, today)
    rent = payable(fin, boss, party, "1000000", today, today, category="rent")
    Debt.objects.filter(pk=goods.pk).update(source_type="inventory.goodsreceipt", source_id=7)
    goods.refresh_from_db()
    bank = MoneyAccount.objects.create(company=fin, name="Bank", kind="bank", currency="UZS")

    assert payables.bank_only(goods) and not payables.bank_only(rent)
    assert len(payables.warnings([goods], kassa)) == 1
    assert payables.warnings([rent], kassa) == []
    assert payables.warnings([goods], bank) == []


def test_payables_respect_permissions_and_tenancy(
    fin, owner_api, role, person, other_company, boss
):
    viewer = owner_api(person(fin, role(fin, "Viewer", [Perm.FINANCE_VIEW])))
    assert viewer.get(url(fin, "payables/")).status_code == 200
    assert viewer.post(url(fin, "payables/pay/"), {}, format="json").status_code == 403
    assert owner_api(boss).get(url(other_company, "payables/")).status_code == 404


def test_credit_debt_books_one_row_and_moves_no_account(fin, boss, kassa, today, src):
    party = CounterpartyFactory(company=fin, name="Oqtosh Med Ta’minot", kind="supplier")
    debt = payable(fin, boss, party, "5000000", today, today + timedelta(days=30))
    goods_before = queries.totals(fin, today, today, branch_ids=None)["expense"]
    kassa_before = kassa.balance

    row = services.credit_debt(
        debt, by=None, amount="1200000", credited_on=today, reason="Returned", source=src(41)
    )

    assert (row.kind, row.is_contra, row.account_id, row.amount) == (
        "expense",
        True,
        None,
        Decimal("1200000.00"),
    )
    debt.refresh_from_db()
    assert debt.paid == Decimal("1200000.00") and debt.status == "open"
    assert queries.totals(fin, today, today, branch_ids=None)["expense"] == goods_before - Decimal(
        "1200000"
    )
    kassa.refresh_from_db()
    assert kassa.balance == kassa_before
    # A retry with the same source books nothing.
    again = services.credit_debt(
        debt, by=None, amount="1200000", credited_on=today, reason="Returned", source=src(41)
    )
    assert again.pk == row.pk
    assert Transaction.objects.filter(debt=debt, is_contra=True).count() == 1


def test_credit_debt_refuses_more_than_owed_and_a_reserved_debt(fin, boss, today, src):
    party = CounterpartyFactory(company=fin, name="Tolzor Farm Savdo", kind="supplier")
    debt = payable(fin, boss, party, "1000000", today, today)

    with pytest.raises(DomainError):
        services.credit_debt(debt, by=boss, amount="1000001", credited_on=today, reason="x")
    services.lock_debt(debt, source=src(9))
    with pytest.raises(DomainError):
        services.credit_debt(debt, by=boss, amount="1", credited_on=today, reason="x")


def test_a_credit_on_a_receivable_lowers_sales_and_survives_the_nightly_check(fin, boss, today):
    from apps.finance import maintenance

    clinic = CounterpartyFactory(company=fin, name="Shifo klinikasi")
    debt = services.open_debt(
        fin,
        by=boss,
        direction="receivable",
        kind="trade",
        amount="2000000",
        currency="UZS",
        issued_on=today,
        counterparty=clinic,
        category="sales",
    )
    services.credit_debt(debt, by=boss, amount="2000000", credited_on=today, reason="Price fix")

    debt.refresh_from_db()
    assert debt.status == "paid"
    assert queries.totals(fin, today, today, branch_ids=None)["income"] == Decimal("0")
    assert maintenance.verify_company(fin) == {"accounts": [], "debts": []}


def test_a_credit_note_can_be_voided(fin, boss, today):
    party = CounterpartyFactory(company=fin, name="Tolzor Farm Savdo", kind="supplier")
    debt = payable(fin, boss, party, "1000000", today, today)
    row = services.credit_debt(debt, by=boss, amount="400000", credited_on=today, reason="Return")

    services.void_transaction(row, by=boss, reason="Wrong return")

    debt.refresh_from_db()
    assert debt.paid == 0


def test_credit_endpoint(fin, boss, owner_api, today):
    party = CounterpartyFactory(company=fin, name="Tolzor Farm Savdo", kind="supplier")
    debt = payable(fin, boss, party, "1000000", today, today)

    response = owner_api(boss).post(
        url(fin, f"debts/{debt.pk}/credit/"),
        {"amount": "300000", "reason": "Return"},
        format="json",
    )

    assert response.status_code == 201, response.content
    assert response.json()["amount"] == "300000.00"


def test_sources_of_planning_rows_are_registered():
    from apps.finance import sources

    assert sources.get("finance.recurring") is not None
    assert sources.get("finance.claim") is not None
    assert Source("finance.claim", 1, "debt").type == "finance.claim"


def test_vat_percent_is_a_contract_of_queries(fin):
    assert queries.vat_percent(fin) == Decimal("0")
    assert date.today()  # the contract never needs a day
