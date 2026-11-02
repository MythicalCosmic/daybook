"""Advances: the cap, request → decide → pay (a receivable in finance) → repay, cancelling,
the owner and employee API."""

from datetime import date
from decimal import Decimal

import pytest

from apps.core.exceptions import DomainError
from apps.finance.models import Debt, Transaction
from apps.inbox.models import Notification
from apps.payroll import queries, services
from apps.payroll.tests.conftest import OCTOBER

pytestmark = pytest.mark.django_db


def url(company, path=""):
    return f"/api/v1/owner/companies/{company.pk}/payroll/{path}"


def my_url(company, path=""):
    return f"/api/v1/companies/{company.pk}/payroll/{path}"


@pytest.fixture
def paid_staff(staff, today):
    for person in (staff.ali, staff.vali, staff.sara):
        services.set_pay(
            person, by=staff.owner, effective_from=date(2026, 1, 1), amount=Decimal("2800000")
        )
    return staff


def test_cap_is_half_a_month_less_what_is_open(shop, paid_staff):
    staff = paid_staff
    cap = queries.advance_cap(staff.ali)
    assert cap["cap"] == Decimal("1400000.00") and cap["available"] == Decimal("1400000.00")
    services.request_advance(staff.ali, by=staff.ali, amount="1000000")
    assert queries.advance_cap(staff.ali)["available"] == Decimal("400000.00")
    with pytest.raises(DomainError, match="at most"):
        services.request_advance(staff.ali, by=staff.ali, amount="500000")
    # Without a pay setup there is nothing to ask for.
    assert queries.advance_cap(staff.owner)["available"] == Decimal("0")
    with pytest.raises(DomainError, match="No advance"):
        services.request_advance(staff.owner, by=staff.owner, amount="1")


def test_request_decide_pay_and_repay(shop, paid_staff, cash, django_capture_on_commit_callbacks):
    staff = paid_staff
    with django_capture_on_commit_callbacks(execute=True):
        row = services.request_advance(staff.ali, by=staff.ali, amount="1000000", installments=2)
    assert row.status == "requested" and row.first_period == OCTOBER
    asked = Notification.objects.filter(kind="payroll.advance", target_id=row.pk)
    assert {n.recipient_id for n in asked} == {staff.owner.pk, staff.accountant.pk}
    with django_capture_on_commit_callbacks(execute=True):
        services.decide_advance(row, by=staff.accountant, approve_it=True)
    row.refresh_from_db()
    assert row.status == "approved"
    assert Notification.objects.filter(kind="payroll.advance_to_pay", target_id=row.pk).exists()
    with django_capture_on_commit_callbacks(execute=True):
        services.pay_advance(row, by=staff.accountant, account=cash, method="cash")
    row.refresh_from_db()
    cash.refresh_from_db()
    assert row.status == "paid" and cash.balance == Decimal("49000000.00")
    debt = row.debt
    assert (debt.direction, debt.kind, debt.amount) == ("receivable", "advance", Decimal("1000000"))
    assert debt.membership_id == staff.ali.pk and debt.source_type == "payroll.advance"
    assert queries.repayment_due(row, OCTOBER) == Decimal("500000.00")
    # Paid back in cash, in two parts: the second closes the advance and the debt.
    services.repay_advance(row, by=staff.accountant, amount="400000", account=cash)
    with pytest.raises(DomainError, match="still owed"):
        services.repay_advance(row, by=staff.accountant, amount="700000", account=cash)
    services.repay_advance(row, by=staff.accountant, amount="600000", account=cash)
    row.refresh_from_db()
    cash.refresh_from_db()
    assert row.status == "repaid" and cash.balance == Decimal("50000000.00")
    assert Debt.objects.get(pk=debt.pk).status == "paid"
    assert Transaction.objects.filter(debt=debt, kind="debt_payment").count() == 2


def test_instalments_split_and_the_last_takes_the_rest(shop, paid_staff, cash):
    staff = paid_staff
    row = services.create_advance(
        staff.ali, by=staff.owner, amount="1000000", installments=3, first_period="2026-10"
    )
    row = services.pay_advance(row, by=staff.owner, account=cash)
    assert queries.repayment_due(row, date(2026, 9, 1)) == 0
    assert queries.repayment_due(row, OCTOBER) == Decimal("333333.33")
    assert queries.repayment_due(row, date(2026, 12, 1)) == Decimal("1000000.00")


def test_cancel_rules(shop, paid_staff, cash):
    staff = paid_staff
    own = services.request_advance(staff.ali, by=staff.ali, amount="100")
    services.cancel_advance(own, by=staff.ali)
    own.refresh_from_db()
    assert own.status == "cancelled"
    given = services.create_advance(staff.vali, by=staff.owner, amount="100")
    with pytest.raises(DomainError):
        services.cancel_advance(given, by=staff.vali)  # approved: only a manager cancels it
    services.pay_advance(given, by=staff.owner, account=cash)
    with pytest.raises(DomainError):
        services.cancel_advance(given, by=staff.owner)


class TestApi:
    def test_owner_flow(self, shop, paid_staff, cash, owner_api):
        staff = paid_staff
        client = owner_api(staff.accountant)
        created = client.post(
            url(shop, "advances/"),
            {"membership": staff.vali.pk, "amount": "800000", "installments": 2},
            format="json",
        )
        assert created.status_code == 201, created.data
        assert created.data["status"] == "approved" and created.data["left"] == "800000.00"
        pk = created.data["id"]
        paid = client.post(
            url(shop, f"advances/{pk}/pay/"), {"account": cash.pk, "method": "card"}, format="json"
        )
        assert paid.status_code == 200, paid.data
        assert paid.data["status"] == "paid" and paid.data["payout_method"] == "card"
        repaid = client.post(
            url(shop, f"advances/{pk}/repay/"),
            {"amount": "300000", "account": cash.pk},
            format="json",
        )
        assert repaid.data["left"] == "500000.00" and repaid.data["repaid"] == "300000.00"
        assert repaid.data["repayments"][0]["how"] == "money"
        assert client.get(url(shop, "advances/"), {"status": "paid"}).data["count"] == 1

    def test_permissions(self, shop, paid_staff, cash, owner_api):
        staff = paid_staff
        row = services.request_advance(staff.ali, by=staff.ali, amount="100")
        assert owner_api(staff.manager).get(url(shop, "advances/")).status_code == 403
        decide = url(shop, f"advances/{row.pk}/decide/")
        assert owner_api(staff.manager).post(decide, {"approve": True}).status_code == 403
        assert owner_api(staff.owner).post(decide, {"approve": True}).status_code == 200
        foreign = owner_api(staff.owner).post(
            url(shop, f"advances/{row.pk}/pay/"), {"account": 999999}, format="json"
        )
        assert foreign.status_code == 400

    def test_employee_requests_within_the_cap(self, shop, paid_staff, api_as):
        staff = paid_staff
        client = api_as(staff.ali)
        mine = client.get(my_url(shop, "advances/")).data
        assert mine["cap"]["available"] == "1400000.00" and mine["advances"] == []
        too_much = client.post(my_url(shop, "advances/"), {"amount": "2000000"}, format="json")
        assert too_much.status_code == 400
        asked = client.post(
            my_url(shop, "advances/"), {"amount": "700000", "reason": "Rent"}, format="json"
        )
        assert asked.status_code == 201 and asked.data["status"] == "requested"
        assert client.get(my_url(shop, "advances/")).data["cap"]["available"] == "700000.00"
        cancelled = client.post(my_url(shop, f"advances/{asked.data['id']}/cancel/"))
        assert cancelled.status_code == 200 and cancelled.data["status"] == "cancelled"
        assert (
            api_as(staff.vali).post(my_url(shop, f"advances/{asked.data['id']}/cancel/"))
        ).status_code == 404

    def test_module_off_and_suspended(self, shop, paid_staff, api_as):
        staff = paid_staff
        staff.ali.status = "suspended"
        staff.ali.save(update_fields=["status"])
        client = api_as(staff.ali)
        assert client.get(my_url(shop, "advances/")).status_code == 200
        assert client.post(my_url(shop, "advances/"), {"amount": "1"}).status_code == 403
        shop.features = []
        shop.save(update_fields=["features"])
        assert api_as(staff.vali).get(my_url(shop, "advances/")).status_code == 403
