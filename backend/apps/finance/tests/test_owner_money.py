"""The owner's money (v11): the safe amount to take out (each obligation, the buffer, never
below zero), draws and contributions, planned purchases, the monthly suggestion, and the
endpoints' scope and permissions."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.companies.models import Branch
from apps.console import registry
from apps.console.registry import CompanyFactsProvider
from apps.core.exceptions import DomainError
from apps.finance import owner_draw, queries, recurring, services
from apps.finance.models import Category, MoneyAccount, PlannedPurchase, Transaction
from apps.finance.tests.factories import CounterpartyFactory, MoneyAccountFactory
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db
D = Decimal


def url(company, path: str) -> str:
    return f"/api/v1/owner/companies/{company.pk}/finance/{path}"


@pytest.fixture
def boss(fin, member):
    return member(fin, "Owner", first_name="Dilnoza")


@pytest.fixture
def today(fin):
    return queries.local_today(fin)


@pytest.fixture
def bank(fin):
    return MoneyAccountFactory(company=fin, name="Bank", kind=MoneyAccount.Kind.BANK)


def opening(company, by, account, amount, day):
    return services.record_transaction(
        company, by=by, kind="opening", amount=D(amount), occurred_on=day, account=account
    )


def spend(company, by, account, amount, day, category):
    return services.record_transaction(
        company,
        by=by,
        kind="expense",
        amount=D(amount),
        occurred_on=day,
        account=account,
        category=category,
    )


def payable(company, by, party, amount, issued_on, due_on, **fields):
    fields.setdefault("category", "goods")
    return services.open_debt(
        company,
        by=by,
        direction="payable",
        kind=fields.pop("kind", "trade"),
        amount=amount,
        currency="UZS",
        issued_on=issued_on,
        due_on=due_on,
        counterparty=party,
        **fields,
    )


@pytest.fixture
def ledger(fin, boss, bank, today):
    """200 mln opened 100 days ago; rent 3 times 9 mln (fixed), medicines 30 mln and a tax 6 mln
    (not fixed). Cash 137 mln; one month of fixed costs 9 mln."""
    opening(fin, boss, bank, "200000000", today - timedelta(days=100))
    for back in (80, 50, 20):
        spend(fin, boss, bank, "9000000", today - timedelta(days=back), "rent")
    spend(fin, boss, bank, "30000000", today - timedelta(days=10), "goods")
    vat = services.create_category(
        fin,
        by=boss,
        name="QQS",
        kind="expense",
        parent=Category.objects.get(company=fin, system_code="taxes"),
    )
    spend(fin, boss, bank, "6000000", today - timedelta(days=5), vat)
    return fin


# The breakdown ----------------------------------------------------------------------------------


def test_safe_is_cash_less_one_month_of_fixed_costs_without_anything_due(ledger, today):
    data = owner_draw.safe_amount(ledger, today)

    assert data["cash"] == D("137000000.00")
    # Rent only: medicines follow sales and taxes are in the tax calendar.
    assert data["buffer"] == {
        "amount": D("9000000.00"),
        "auto": True,
        "fixed_costs": D("9000000.00"),
    }
    assert data["due"] == 0
    assert data["reasons"] == []
    assert data["safe"] == D("128000000.00")
    assert data["short"] == 0
    assert data["horizon_days"] == 30
    assert data["until"] == today + timedelta(days=30)


def test_the_owners_own_money_is_not_the_businesses_cash(ledger, boss, today):
    mine = services.account_for_holder(ledger, boss, kind="owner")
    opening(ledger, boss, mine, "50000000", today - timedelta(days=3))

    data = owner_draw.safe_amount(ledger, today)

    assert data["cash"] == D("137000000.00")
    assert data["personal"] == D("50000000.00")
    assert data["safe"] == D("128000000.00")


def test_each_obligation_within_the_horizon_is_kept_back(ledger, boss, today):
    rent = Category.objects.get(company=ledger, system_code="rent")
    recurring.create_rule(
        ledger,
        by=boss,
        name="Ijara: Chilonzor",
        kind="expense",
        mode="bill",
        frequency="monthly",
        day=(today + timedelta(days=3)).day,
        category=rent,
        amount="9000000",
        starts_on=today,
    )
    distributor = CounterpartyFactory(company=ledger, name="Oqtosh Med Ta’minot", kind="supplier")
    payable(ledger, boss, distributor, "20000000", today, today + timedelta(days=10))
    payable(ledger, boss, distributor, "5000000", today - timedelta(days=20), today - timedelta(2))
    later = CounterpartyFactory(company=ledger, name="Tolzor Farm Savdo", kind="supplier")
    payable(ledger, boss, later, "50000000", today, today + timedelta(days=40))  # after 30 days
    clinic = CounterpartyFactory(company=ledger, name="Shifo klinikasi")
    services.open_debt(
        ledger,
        by=boss,
        direction="receivable",
        kind="trade",
        amount="15000000",
        currency="UZS",
        issued_on=today,
        due_on=today + timedelta(days=5),
        counterparty=clinic,
        category="sales",
    )
    services.open_debt(
        ledger,
        by=boss,
        direction="payable",
        kind="salary",
        amount="4500000",
        currency="UZS",
        issued_on=today,
        membership=boss,
        category="salaries",
    )
    lender = CounterpartyFactory(company=ledger, name="Ishonch bank", kind="other")
    loan = services.open_debt(
        ledger,
        by=boss,
        direction="payable",
        kind="loan",
        amount="60000000",
        currency="UZS",
        issued_on=today - timedelta(days=60),
        counterparty=lender,
        is_opening=True,
        description="Aylanma mablag‘ krediti",
    )
    services.set_installments(
        loan,
        by=boss,
        rows=[(today - timedelta(days=5), "10000000")]
        + [(today + timedelta(days=25 + 30 * step), "10000000") for step in range(5)],
    )

    data = owner_draw.safe_amount(ledger, today)
    reasons = {reason["key"].split(":")[0]: reason for reason in data["reasons"]}

    # The bill, the distributor's two payables (one overdue) as one line, the pay owed, and the
    # two instalments due by then; not the later payable, not what the clinic owes.
    assert reasons["rule"]["amount"] == D("9000000.00")
    assert reasons["payable"]["title"] == "Oqtosh Med Ta’minot"
    assert reasons["payable"]["amount"] == D("25000000.00")
    assert reasons["payable"]["count"] == 2
    assert reasons["payable"]["overdue"] is True
    assert reasons["payroll"]["amount"] == D("4500000.00")
    instalments = [r for r in data["reasons"] if r["kind"] == "loan"]
    assert [r["amount"] for r in instalments] == [D("10000000.00"), D("10000000.00")]
    assert instalments[0]["overdue"] is True
    assert data["due"] == D("9000000") + D("25000000") + D("4500000") + D("20000000")
    assert data["safe"] == D("137000000") - data["due"] - D("9000000")
    # Overdue first, then the biggest.
    assert data["reasons"][0]["overdue"] is True


def test_a_paid_instalment_is_no_longer_kept_back(ledger, boss, bank, today):
    lender = CounterpartyFactory(company=ledger, name="Ishonch bank", kind="other")
    loan = services.open_debt(
        ledger,
        by=boss,
        direction="payable",
        kind="loan",
        amount="20000000",
        currency="UZS",
        issued_on=today - timedelta(days=30),
        counterparty=lender,
        is_opening=True,
    )
    services.set_installments(
        loan,
        by=boss,
        rows=[(today + timedelta(days=5), "10000000"), (today + timedelta(days=20), "10000000")],
    )
    assert owner_draw.safe_amount(ledger, today)["due"] == D("20000000.00")

    services.pay_debt(loan, by=boss, amount=D("10000000"), paid_on=today, account=bank)

    data = owner_draw.safe_amount(ledger, today)
    assert data["due"] == D("10000000.00")
    assert data["cash"] == D("127000000.00")


def test_bills_whose_amount_nobody_knows_are_listed_but_not_counted(ledger, boss, today):
    utilities = Category.objects.get(company=ledger, system_code="utilities")
    recurring.create_rule(
        ledger,
        by=boss,
        name="Elektr",
        kind="expense",
        mode="bill",
        frequency="monthly",
        day=(today + timedelta(days=4)).day,
        category=utilities,
        amount="0",
        amount_varies=True,
        starts_on=today,
    )

    data = owner_draw.safe_amount(ledger, today)

    assert data["unknown"] == 1
    assert data["reasons"][-1]["amount"] is None
    assert data["due"] == 0
    assert data["safe"] == D("128000000.00")


def test_an_explicit_buffer_and_a_longer_horizon(ledger, boss, today):
    distributor = CounterpartyFactory(company=ledger, name="Ko‘kterak Farm", kind="supplier")
    payable(ledger, boss, distributor, "50000000", today, today + timedelta(days=40))
    owner_draw.update_settings(ledger, by=boss, cash_buffer="20000000", draw_horizon_days=45)

    data = owner_draw.safe_amount(ledger, today)

    assert data["buffer"]["auto"] is False
    assert data["buffer"]["amount"] == D("20000000.00")
    assert data["buffer"]["fixed_costs"] == D("9000000.00")
    assert data["due"] == D("50000000.00")
    assert data["safe"] == D("67000000.00")
    with pytest.raises(DomainError):
        owner_draw.update_settings(ledger, by=boss, draw_horizon_days=200)
    owner_draw.update_settings(ledger, by=boss, cash_buffer=None)
    assert owner_draw.safe_amount(ledger, today)["buffer"]["auto"] is True


def test_the_safe_amount_never_goes_below_zero(ledger, boss, today):
    distributor = CounterpartyFactory(company=ledger, name="Ko‘kterak Farm", kind="supplier")
    payable(ledger, boss, distributor, "150000000", today, today + timedelta(days=7))

    data = owner_draw.safe_amount(ledger, today)

    assert data["safe"] == 0
    assert data["short"] == D("150000000") + D("9000000") - D("137000000")


def test_planned_purchases_within_the_horizon_are_kept_back(ledger, boss, today):
    owner_draw.plan_purchase(
        ledger, by=boss, title="Farmatsevtik muzlatgich", amount="14000000", due_on=today
    )
    owner_draw.plan_purchase(ledger, by=boss, title="Peshlavha", amount="5000000")  # no date
    owner_draw.plan_purchase(
        ledger, by=boss, title="Yangi kassa", amount="8000000", due_on=today + timedelta(days=60)
    )
    done = owner_draw.plan_purchase(ledger, by=boss, title="Javon", amount="3000000")
    owner_draw.update_purchase(done, by=boss, done=True)

    data = owner_draw.safe_amount(ledger, today)

    assert data["planned"] == D("19000000.00")
    assert [row.title for row in data["purchases"]["kept"]] == [
        "Farmatsevtik muzlatgich",
        "Peshlavha",
    ]
    assert [row.title for row in data["purchases"]["later"]] == ["Yangi kassa"]
    assert data["safe"] == D("128000000") - D("19000000")
    with pytest.raises(DomainError):
        owner_draw.plan_purchase(ledger, by=boss, title=" ", amount="1000")


def test_payroll_counts_payrolls_own_figure_for_the_next_pay_day(
    ledger, boss, today, isolated_registries
):
    ledger.features = ["finance", "payroll"]
    ledger.save(update_fields=["features"])
    pay_day = today + timedelta(days=12)
    registry.COMPANY_FACTS._entries.pop("payroll", None)
    registry.COMPANY_FACTS.add(
        CompanyFactsProvider(
            "payroll",
            None,
            None,
            None,
            lambda company, range_, member: {
                "next_run_on": pay_day.isoformat(),
                "next_run_amount": "84000000.00",
            },
        )
    )

    data = owner_draw.safe_amount(ledger, today)

    payroll = [reason for reason in data["reasons"] if reason["kind"] == "payroll"]
    assert payroll[0]["date"] == pay_day
    assert payroll[0]["amount"] == D("84000000.00")
    assert payroll[0]["estimate"] is True
    # The pay booked for the same run isn't counted twice: the bigger of the two stands.
    services.open_debt(
        ledger,
        by=boss,
        direction="payable",
        kind="salary",
        amount="84000000",
        currency="UZS",
        issued_on=today,
        membership=boss,
        category="salaries",
    )
    again = owner_draw.safe_amount(ledger, today)
    assert [r["amount"] for r in again["reasons"] if r["kind"] == "payroll"] == [D("84000000.00")]


# Draws and contributions -------------------------------------------------------------------------


def test_this_months_draws_and_contributions(ledger, boss, bank, today):
    owner_draw.take(
        ledger,
        by=boss,
        account=bank,
        amount="12000000",
        occurred_on=today.replace(day=1),
        confirmed=True,
    )
    owner_draw.put(ledger, by=boss, account=bank, amount="3000000", occurred_on=today)
    mine = services.account_for_holder(ledger, boss, kind="owner")
    opening(ledger, boss, mine, "1000000", today)
    services.record_transaction(
        ledger, by=boss, kind="owner", amount=D("-500000"), occurred_on=today, account=mine
    )  # the personal side: not the business's

    month = owner_draw.safe_amount(ledger, today)["month"]

    assert month["drawn"] == D("12000000.00")
    assert month["put_in"] == D("3000000.00")
    assert month["net"] == D("-9000000.00")
    assert month["count"] == 2
    assert [row["direction"] for row in month["rows"]] == ["in", "out"]
    assert month["rows"][1]["description"] == "Taken by the owner"
    rows = Transaction.objects.filter(company=ledger, kind="owner", account=bank)
    # Owner money never reaches the profit.
    assert queries.totals(ledger, today.replace(day=1), today, branch_ids=None)["income"] == 0
    assert {row.amount for row in rows} == {D("-12000000.00"), D("3000000.00")}


def test_taking_more_than_is_safe_needs_a_confirmation(ledger, boss, bank, today):
    with pytest.raises(owner_draw.OverSafe) as error:
        owner_draw.take(ledger, by=boss, account=bank, amount="130000000", occurred_on=today)
    assert error.value.safe == D("128000000.00")
    assert not Transaction.objects.filter(company=ledger, kind="owner").exists()

    row = owner_draw.take(
        ledger, by=boss, account=bank, amount="130000000", occurred_on=today, confirmed=True
    )
    assert row.amount == D("-130000000.00")
    assert owner_draw.safe_amount(ledger, today)["safe"] == 0


def test_money_is_taken_only_from_business_accounts(ledger, boss, today):
    terminal = MoneyAccount.objects.get(company=ledger, kind=MoneyAccount.Kind.CLEARING)
    mine = services.account_for_holder(ledger, boss, kind="owner")
    for account in (terminal, mine):
        with pytest.raises(DomainError):
            owner_draw.take(ledger, by=boss, account=account, amount="1000", occurred_on=today)
        with pytest.raises(DomainError):
            owner_draw.put(ledger, by=boss, account=account, amount="1000", occurred_on=today)


def test_history_puts_draws_beside_the_months_profit(ledger, boss, bank, today):
    owner_draw.take(
        ledger, by=boss, account=bank, amount="2000000", occurred_on=today, confirmed=True
    )

    rows = owner_draw.history(ledger, 3, today)

    assert [row["month"] for row in rows][-1] == today.replace(day=1)
    assert len(rows) == 3
    assert rows[-1]["drawn"] == D("2000000.00")
    month_profit = queries.totals(ledger, today.replace(day=1), today, branch_ids=None)["profit"]
    assert rows[-1]["profit"] == month_profit


# The monthly suggestion ------------------------------------------------------------------------


def test_the_suggestion_keeps_90_days_above_the_buffer(fin, boss, bank, today):
    opening(fin, boss, bank, "100000000", today - timedelta(days=1))
    owner_draw.update_settings(fin, by=boss, cash_buffer="10000000")

    data = owner_draw.suggested_monthly(fin, today)

    # No usual takings or spending yet: three draws of 30 mln leave exactly the 10 mln buffer.
    assert len(data["dates"]) == 3
    assert data["dates"][0] == owner_draw._add_months(today.replace(day=1), 1)
    assert data["monthly"] == D("30000000.00")
    assert data["low"]["balance"] == D("10000000.00")
    assert data["below_buffer_on"] is None


def test_the_suggestion_counts_the_payroll_the_forecast_cant_see(
    fin, boss, bank, today, isolated_registries
):
    fin.features = ["finance", "payroll"]
    fin.save(update_fields=["features"])
    opening(fin, boss, bank, "100000000", today - timedelta(days=1))
    owner_draw.update_settings(fin, by=boss, cash_buffer="10000000")
    registry.COMPANY_FACTS._entries.pop("payroll", None)
    registry.COMPANY_FACTS.add(
        CompanyFactsProvider(
            "payroll",
            None,
            None,
            None,
            lambda company, range_, member: {
                "next_run_on": (today + timedelta(days=12)).isoformat(),
                "next_run_amount": "20000000.00",
            },
        )
    )

    data = owner_draw.suggested_monthly(fin, today)

    # Three pay days of 20 mln within the 90 days: 100 - 60 - 3 draws >= 10.
    assert data["monthly"] == D("10000000.00")
    assert data["profit_average"] == 0
    assert data["above_profit"] is True


def test_no_suggestion_when_the_forecast_is_already_below_the_buffer(fin, boss, bank, today):
    opening(fin, boss, bank, "5000000", today - timedelta(days=1))
    owner_draw.update_settings(fin, by=boss, cash_buffer="10000000")

    data = owner_draw.suggested_monthly(fin, today)

    assert data["monthly"] == 0
    assert data["below_buffer_on"] == today


def test_round_down():
    assert owner_draw.round_down(D("38456789"), "UZS") == D("38400000.00")
    assert owner_draw.round_down(D("456789"), "UZS") == D("450000.00")
    assert owner_draw.round_down(D("1234.5"), "USD") == D("1230.00")
    assert owner_draw.round_down(D("-5"), "UZS") == 0


def test_add_months_keeps_the_day_or_the_months_last():
    assert owner_draw._add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert owner_draw._add_months(date(2026, 11, 5), 2) == date(2027, 1, 5)
    assert owner_draw._add_months(date(2026, 12, 1), -1) == date(2026, 11, 1)


# The endpoints ---------------------------------------------------------------------------------


def test_the_page_in_one_call(ledger, boss, owner_api, today):
    response = owner_api(boss).get(url(ledger, "owner-money/"))

    assert response.status_code == 200
    data = response.json()
    assert data["safe"] == "128000000.00"
    assert data["cash"] == "137000000.00"
    assert data["buffer"] == {"amount": "9000000.00", "auto": True, "fixed_costs": "9000000.00"}
    assert data["settings"] == {"cash_buffer": None, "draw_horizon_days": 30}
    assert data["suggestion"]["monthly"]
    assert len(data["history"]) == 6
    assert {account["name"] for account in data["accounts"]} >= {"Bank"}
    assert all(account["kind"] != "clearing" for account in data["accounts"])
    assert data["is_owner"] is True
    assert data["partners"] == 0


def test_take_and_put_through_the_api(ledger, boss, bank, owner_api, today):
    client = owner_api(boss)

    over = client.post(
        url(ledger, "owner-money/take/"), {"account": bank.pk, "amount": "130000000"}, format="json"
    )
    assert over.status_code == 400
    assert over.json()["code"] == "over_safe"
    assert over.json()["safe"] == "128000000.00"

    taken = client.post(
        url(ledger, "owner-money/take/"),
        {"account": bank.pk, "amount": "8000000", "description": "Uy uchun"},
        format="json",
    )
    assert taken.status_code == 201
    assert taken.json()["safe"] == "120000000.00"
    put = client.post(
        url(ledger, "owner-money/put/"), {"account": bank.pk, "amount": "2000000"}, format="json"
    )
    assert put.status_code == 201
    future = client.post(
        url(ledger, "owner-money/take/"),
        {
            "account": bank.pk,
            "amount": "1000",
            "occurred_on": (today + timedelta(days=1)).isoformat(),
        },
        format="json",
    )
    assert future.status_code == 400
    page = client.get(url(ledger, "owner-money/")).json()
    assert page["month"]["drawn"] == "8000000.00"
    assert page["month"]["put_in"] == "2000000.00"


def test_settings_and_planned_purchases_through_the_api(
    ledger, boss, owner_api, today, django_capture_on_commit_callbacks
):
    client = owner_api(boss)

    response = client.patch(
        url(ledger, "owner-money/settings/"),
        {"cash_buffer": "15000000", "draw_horizon_days": 14},
        format="json",
    )
    assert response.json() == {"cash_buffer": "15000000.00", "draw_horizon_days": 14}
    made = client.post(
        url(ledger, "owner-money/purchases/"),
        {"title": "Muzlatgich", "amount": "14000000", "due_on": today.isoformat()},
        format="json",
    )
    assert made.status_code == 201
    pk = made.json()["id"]
    assert client.get(url(ledger, "owner-money/")).json()["planned"] == "14000000.00"
    # A write bumps the ledger's pulse after commit, which retires the cached page.
    with django_capture_on_commit_callbacks(execute=True):
        done = client.patch(
            url(ledger, f"owner-money/purchases/{pk}/"), {"done": True}, format="json"
        )
    assert done.json()["done"] is True
    assert client.get(url(ledger, "owner-money/")).json()["planned"] == "0.00"
    assert client.delete(url(ledger, f"owner-money/purchases/{pk}/")).status_code == 204
    assert not PlannedPurchase.objects.filter(pk=pk).exists()


def test_another_companys_id_is_not_found(ledger, boss, owner_api, other_company, member):
    stranger = member(other_company, "Owner")
    assert owner_api(stranger).get(url(ledger, "owner-money/")).status_code == 404


def test_it_needs_finance_view_and_manage(ledger, owner_api, role, person):
    viewer = person(ledger, role(ledger, "Viewer", [Perm.FINANCE_VIEW, Perm.BRANCHES_ALL]))
    assert owner_api(viewer).get(url(ledger, "owner-money/")).status_code == 403
    accountant = person(
        ledger,
        role(ledger, "Buxgalter", [Perm.FINANCE_VIEW, Perm.FINANCE_MANAGE, Perm.BRANCHES_ALL]),
    )
    response = owner_api(accountant).get(url(ledger, "owner-money/"))
    assert response.status_code == 200
    assert response.json()["is_owner"] is False


def test_someone_who_sees_only_some_branches_is_refused(ledger, owner_api, role, person):
    branch = Branch.objects.filter(company=ledger).first() or Branch.objects.create(
        company=ledger, name="Chilonzor"
    )
    manager = person(
        ledger, role(ledger, "Branch money", [Perm.FINANCE_VIEW, Perm.FINANCE_MANAGE]), [branch]
    )
    for path in ("owner-money/", "partners/", "dividends/"):
        assert owner_api(manager).get(url(ledger, path)).status_code == 403


def test_the_module_switch(ledger, boss, owner_api):
    ledger.features = []
    ledger.save(update_fields=["features"])
    assert owner_api(boss).get(url(ledger, "owner-money/")).status_code == 404
