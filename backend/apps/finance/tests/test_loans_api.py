"""The loans and tax calendar owner endpoints (v12): rule 21 (company scope, permissions, branch
scope, audit, money as strings) and the shapes the dashboard reads."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from apps.audit.models import AuditLog
from apps.companies.models import Branch
from apps.finance import loans, queries, services
from apps.finance.models import Debt, Loan, MoneyAccount, TaxMark
from apps.finance.tests.factories import CounterpartyFactory, MoneyAccountFactory
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db


def url(company, path: str) -> str:
    return f"/api/v1/owner/companies/{company.pk}/finance/{path}"


@pytest.fixture
def today(fin):
    return queries.local_today(fin)


@pytest.fixture
def boss(fin, member):
    return member(fin, "Owner", first_name="Dilnoza")


@pytest.fixture
def client(owner_api, boss):
    return owner_api(boss)


@pytest.fixture
def bank(fin, boss, today):
    account = MoneyAccountFactory(company=fin, name="Bank", kind=MoneyAccount.Kind.BANK)
    services.record_transaction(
        fin,
        by=boss,
        kind="opening",
        amount=D(100_000_000),
        occurred_on=today - timedelta(days=120),
        account=account,
    )
    return account


@pytest.fixture
def lender(fin):
    return CounterpartyFactory(company=fin, name="Hamkorbank", kind="other")


def terms(today, lender, bank, **extra) -> dict:
    return {
        "direction": "payable",
        "counterparty": lender.pk,
        "account": bank.pk,
        "amount": "24000000",
        "currency": "UZS",
        "issued_on": (today - timedelta(days=40)).isoformat(),
        "annual_rate": "24",
        "method": "annuity",
        "term_months": 12,
        "first_due_on": (today - timedelta(days=10)).isoformat(),
        **extra,
    }


@pytest.fixture
def loan(client, fin, today, lender, bank):
    response = client.post(url(fin, "loans/"), terms(today, lender, bank), format="json")
    assert response.status_code == 201, response.json()
    return Loan.objects.get(pk=response.json()["id"])


def test_preview_shows_the_schedule_without_saving(client, fin, today, lender, bank):
    body = terms(today, lender, bank, method="equal_principal", fee="240000")
    response = client.post(url(fin, "loans/preview/"), body, format="json")
    assert response.status_code == 200
    data = response.json()
    assert len(data["rows"]) == 12
    assert data["rows"][0]["principal"] == "2000000.00"
    assert data["rows"][0]["interest"] == "480000.00"
    assert data["rows"][-1]["balance"] == "0.00"
    assert data["totals"]["interest"] == "3120000.00"
    assert data["totals"]["cost"] == "3360000.00"
    assert not Loan.objects.exists()


def test_record_and_read_a_loan(client, fin, today, loan):
    listing = client.get(url(fin, "loans/")).json()
    assert listing["currency"] == "UZS"
    row = listing["loans"][0]
    assert row["id"] == loan.pk and row["counterparty"]["name"] == "Hamkorbank"
    assert row["owed"] == "24000000.00" and row["annual_rate"] == "24.000"
    # The first payment was due ten days ago: it is overdue.
    assert row["overdue_count"] == 1
    assert D(listing["overdue"]) == D(row["overdue_amount"])
    detail = client.get(url(fin, f"loans/{loan.pk}/")).json()
    assert len(detail["schedule"]) == 12
    assert detail["schedule"][0]["status"] == "overdue"
    assert detail["can_pay"] and detail["can_edit_schedule"]
    assert [row["kind"] for row in detail["payments"]] == ["debt_open"]
    assert AuditLog.objects.filter(action="finance.loan_created").exists()


def test_pay_then_undo(client, fin, today, loan, bank):
    first = loan.debt.installments.order_by("due_on").first()
    response = client.post(
        url(fin, f"loans/{loan.pk}/pay/"),
        {"installment": first.pk, "account": bank.pk, "paid_on": today.isoformat()},
        format="json",
    )
    assert response.status_code == 200, response.json()
    detail = response.json()
    assert detail["schedule"][0]["status"] == "paid"
    assert not detail["can_edit_schedule"]
    kinds = sorted(row["kind"] for row in detail["payments"])
    assert kinds == ["debt_open", "debt_payment", "expense"]
    paid = next(row for row in detail["payments"] if row["kind"] == "debt_payment")
    undone = client.post(
        url(fin, f"loans/{loan.pk}/undo/"),
        {"transaction": paid["id"], "reason": "Typed twice"},
        format="json",
    )
    assert undone.status_code == 200
    assert undone.json()["schedule"][0]["status"] == "overdue"


def test_early_repayment_endpoint(client, fin, today, loan, bank):
    first = loan.debt.installments.order_by("due_on").first()
    client.post(
        url(fin, f"loans/{loan.pk}/pay/"),
        {"installment": first.pk, "account": bank.pk, "paid_on": today.isoformat()},
        format="json",
    )
    response = client.post(
        url(fin, f"loans/{loan.pk}/repay-early/"),
        {"account": bank.pk, "paid_on": today.isoformat(), "amount": "10000000", "mode": "term"},
        format="json",
    )
    assert response.status_code == 200, response.json()
    data = response.json()
    assert any(row["early"] for row in data["schedule"])
    assert data["loan"]["payments_left"] < 11
    assert data["schedule"][-1]["balance"] == "0.00"


def test_the_schedule_is_editable_before_the_first_payment(client, fin, loan):
    response = client.put(
        url(fin, f"loans/{loan.pk}/schedule/"),
        {"method": "equal_principal", "term_months": 6},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert len(response.json()["schedule"]) == 6


def test_another_companys_loan_is_404(client, fin, other_company, member, owner_api):
    from apps.finance import defaults

    defaults.ensure(other_company)
    other_company.features = ["finance"]
    other_company.save(update_fields=["features"])
    stranger = member(other_company, "Owner")
    party = CounterpartyFactory(company=other_company, name="Bank X")
    theirs = loans.create(
        other_company,
        by=stranger,
        direction="payable",
        counterparty=party,
        amount=D(1_000_000),
        currency="UZS",
        issued_on=date(2026, 1, 1),
        annual_rate=D(10),
        method="annuity",
        term_months=2,
        first_due_on=date(2026, 2, 1),
    )
    assert client.get(url(fin, f"loans/{theirs.pk}/")).status_code == 404
    assert client.post(url(fin, f"loans/{theirs.pk}/pay/"), {}, format="json").status_code == 404
    assert client.get(url(other_company, "loans/")).status_code in (403, 404)


def test_permissions(fin, role, person, owner_api, loan, today, lender, bank):
    viewer = person(fin, role(fin, "Viewer", [Perm.FINANCE_VIEW, Perm.BRANCHES_ALL]))
    client = owner_api(viewer)
    assert client.get(url(fin, "loans/")).status_code == 200
    assert client.get(url(fin, f"loans/{loan.pk}/")).status_code == 200
    assert (
        client.post(url(fin, "loans/"), terms(today, lender, bank), format="json").status_code
        == 403
    )
    first = loan.debt.installments.first()
    paying = client.post(
        url(fin, f"loans/{loan.pk}/pay/"),
        {"installment": first.pk, "account": bank.pk, "paid_on": today.isoformat()},
        format="json",
    )
    assert paying.status_code == 403
    nobody = person(fin, role(fin, "Nobody", []))
    assert owner_api(nobody).get(url(fin, "loans/")).status_code == 403
    # A recorder without finance.manage can't enter a loan from before the books.
    recorder = person(
        fin, role(fin, "Recorder", [Perm.FINANCE_VIEW, Perm.FINANCE_RECORD, Perm.BRANCHES_ALL])
    )
    old = terms(today, lender, bank, account=None)
    assert owner_api(recorder).post(url(fin, "loans/"), old, format="json").status_code == 403


def test_branch_scope(fin, role, person, owner_api, boss, lender, bank):
    north = Branch.objects.create(company=fin, name="North")
    south = Branch.objects.create(company=fin, name="South")
    for branch in (north, south):
        loans.create(
            fin,
            by=boss,
            direction="payable",
            counterparty=lender,
            amount=D(1_000_000),
            currency="UZS",
            issued_on=date(2026, 1, 1),
            annual_rate=D(10),
            method="annuity",
            term_months=2,
            first_due_on=date(2026, 2, 1),
            branch=branch,
        )
    local = person(fin, role(fin, "North finance", [Perm.FINANCE_VIEW]), branches=[north])
    seen = owner_api(local).get(url(fin, "loans/")).json()["loans"]
    assert [row["branch"]["name"] for row in seen] == ["North"]
    south_loan = Loan.objects.get(debt__branch=south)
    assert owner_api(local).get(url(fin, f"loans/{south_loan.pk}/")).status_code == 404
    # Taxes are the whole company's.
    assert owner_api(local).get(url(fin, "taxes/")).status_code == 403
    assert owner_api(local).get(url(fin, "taxes/compare/")).status_code == 403


def test_module_off_is_404(client, fin):
    fin.features = []
    fin.save(update_fields=["features"])
    assert client.get(url(fin, "loans/")).status_code == 404
    assert client.get(url(fin, "taxes/")).status_code == 404


def test_tax_calendar_endpoints(client, fin, today, bank, boss):
    data = client.get(url(fin, "taxes/")).json()
    assert data["regime"] == "turnover"
    assert data["disclaimer"]
    assert data["warnings"]  # a pharmacy on turnover tax is told it can't be
    assert data["deadlines"] and data["sources"]
    first = data["deadlines"][0]
    assert {"law", "url", "estimate", "basis", "status", "period_label"} <= set(first)
    target = next(row for row in data["deadlines"] if row["action"] != "file")
    response = client.post(
        url(fin, "taxes/marks/"),
        {
            "rule": target["rule"],
            "period_start": target["period_start"],
            "done_on": today.isoformat(),
            "account": bank.pk,
            "amount": "1500000",
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    mark = TaxMark.objects.get()
    assert mark.transaction is not None
    data = client.get(url(fin, "taxes/")).json()
    done = next(row for row in data["deadlines"] if row["key"] == target["key"])
    assert done["status"] == "done" and done["paid"] == "1500000.00"
    candidates = client.get(url(fin, "taxes/candidates/"), {"deadline": target["key"]})
    assert candidates.status_code == 200
    assert client.delete(url(fin, f"taxes/marks/{mark.pk}/")).status_code == 204
    assert AuditLog.objects.filter(action="finance.tax_unmarked").exists()
    compare = client.get(url(fin, "taxes/compare/")).json()
    assert [row["regime"] for row in compare["options"]] == ["turnover", "vat", "vat_simplified"]


def test_settings_and_supplier_terms(client, fin):
    response = client.patch(
        url(fin, "settings/"),
        {"loan_remind_days": 2, "tax_remind_days": 7, "owns_property": True},
        format="json",
    )
    assert response.status_code == 200
    data = response.json()
    assert (data["loan_remind_days"], data["tax_remind_days"], data["owns_property"]) == (
        2,
        7,
        True,
    )
    assert data["base_value"] == "440000.00"
    made = client.post(
        url(fin, "counterparties/"),
        {"name": "Grand Pharm", "kind": "supplier", "credit_days": 30},
        format="json",
    )
    assert made.status_code == 201
    assert made.json()["credit_days"] == 30
    assert made.json()["payment_terms"]
    party = made.json()["id"]
    both = client.patch(url(fin, f"counterparties/{party}/"), {"credit_day": 10}, format="json")
    assert both.status_code == 400
    moved = client.patch(
        url(fin, f"counterparties/{party}/"),
        {"credit_day": 10, "credit_days": None},
        format="json",
    )
    assert moved.status_code == 200 and moved.json()["credit_day"] == 10
    debt = client.post(
        url(fin, "debts/"),
        {
            "direction": "payable",
            "kind": "trade",
            "mode": "opening",
            "amount": "1000000",
            "currency": "UZS",
            "issued_on": "2026-10-05",
            "counterparty": party,
        },
        format="json",
    )
    assert debt.status_code == 201, debt.json()
    assert Debt.objects.get(pk=debt.json()["id"]).due_on == date(2026, 11, 10)
