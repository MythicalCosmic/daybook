"""Customers and nasiya (PLAN-OWNER §11.4, §3.8): phone normalization and uniqueness, each
credit sale one receivable, payments oldest first into the till, the shift's Nasiya total
against the recorded credit sales at close, aging, the daily reminders and the endpoints."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from apps.core.exceptions import DomainError
from apps.finance.models import LIVE_STATUSES, Debt, Transaction
from apps.inbox.models import Notification
from apps.members.permissions import Perm
from apps.sales import cash, queries, reminders, services
from apps.sales.models import CreditEntry, SalesSettings
from apps.sales.services import PaymentLine
from apps.sales.tests.factories import jpeg, make_member, scoped_role

TASHKENT = ZoneInfo("Asia/Tashkent")


@pytest.fixture
def till(shop):
    """Madina's shift is open at Chilonzor with a float of 100 000."""
    shop.shift = services.open_shift(
        by=shop.cashier, register=shop.register, opening_float="100000"
    )
    shop.regular = services.create_customer(
        shop.company, by=shop.owner, name="Saida opa", phone="90 123 45 67"
    )
    return shop


def sale(shop, amount, customer=None):
    return services.record_credit(
        by=shop.cashier, kind="sale", customer=customer or shop.regular, amount=amount
    )


def test_customer_phones_are_normalized_and_unique(shop):
    party = services.create_customer(
        shop.company, by=shop.owner, name="Shifo klinikasi", phone="(90) 123-45-67", kind="clinic"
    )
    assert party.phone == "+998901234567" and party.kind == "customer"
    assert services.customer_kind(party) == "clinic"
    with pytest.raises(DomainError):
        services.create_customer(
            shop.company, by=shop.owner, name="Twin", phone="+998 90 123 45 67"
        )
    with pytest.raises(DomainError):
        services.create_customer(shop.company, by=shop.owner, name="Odd", phone="12345")
    services.update_customer(party, by=shop.owner, kind="pharmacy")
    party.refresh_from_db()
    assert services.customer_kind(party) == "pharmacy"


def test_a_credit_sale_opens_one_receivable_booking_the_income(till):
    entry = sale(till, "150000")
    debt = entry.debt
    assert debt.direction == "receivable" and debt.kind == "trade" and debt.amount == 150000
    assert debt.counterparty_id == till.regular.pk and debt.branch_id == till.branch.pk
    days = SalesSettings.objects.get(company=till.company).credit_days
    assert debt.due_on == till.shift.business_day + timedelta(days=days)
    # Nobody manages Chilonzor in the fixture: the cashier who sold it chases it.
    assert debt.responsible_id == till.cashier.pk
    [income] = Transaction.objects.filter(debt=debt, status__in=LIVE_STATUSES)
    assert income.kind == "income" and income.amount == Decimal("150000.00")
    assert income.account_id is None  # an accrual: no money moved
    assert services.owed(till.regular, currency="UZS") == Decimal("150000.00")
    assert Debt.objects.filter(counterparty=till.regular).count() == 1


def test_limits_and_blocked_customers_are_refused(till):
    services.update_customer(till.regular, by=till.owner, credit_limit="200000")
    sale(till, "150000")
    with pytest.raises(DomainError):
        sale(till, "60000")
    services.update_customer(till.regular, by=till.owner, credit_blocked=True)
    with pytest.raises(DomainError):
        sale(till, "10000")


def test_a_payment_settles_the_oldest_first_and_its_cash_is_in_the_till(till):
    first = sale(till, "100000")
    second = sale(till, "80000")
    with pytest.raises(DomainError):
        services.record_credit(
            by=till.cashier, kind="payment", customer=till.regular, amount="200000"
        )
    paid = services.record_credit(
        by=till.cashier, kind="payment", customer=till.regular, amount="130000"
    )
    first.debt.refresh_from_db()
    second.debt.refresh_from_db()
    assert first.debt.status == "paid" and second.debt.paid == Decimal("30000.00")
    assert paid.method.kind == "cash"
    # The till expects the float plus the cash paid back.
    shift = till.shift
    assert cash.expected_cash(shift) == Decimal("230000.00")
    assert cash.tills_now([till.register], {till.register.pk: shift})[till.register.pk] == 230000
    nasiya = till.method("credit")
    closed = services.close_shift(
        shift,
        by=till.cashier,
        payments=[PaymentLine(nasiya, Decimal("180000"))],
        counted_cash="230000",
        z_photo=jpeg(),
    )
    assert closed.difference == 0 and closed.expected_cash == Decimal("230000.00")


def test_the_nasiya_total_at_close_must_be_the_recorded_credit_sales(till):
    sale(till, "120000")
    nasiya = till.method("credit")
    with pytest.raises(DomainError) as refused:
        services.close_shift(
            till.shift,
            by=till.cashier,
            payments=[PaymentLine(nasiya, Decimal("150000"))],
            counted_cash="100000",
            z_photo=jpeg(),
        )
    # The cashier sees the gap.
    assert "30" in str(refused.value) and "000" in str(refused.value)
    closed = services.close_shift(
        till.shift,
        by=till.cashier,
        payments=[PaymentLine(nasiya, Decimal("120000"))],
        counted_cash="100000",
        z_photo=jpeg(),
    )
    assert closed.status == "closed"


def test_a_company_that_never_records_nasiya_closes_as_before(shop):
    shift = services.open_shift(by=shop.cashier, register=shop.register, opening_float="0")
    closed = services.close_shift(
        shift,
        by=shop.cashier,
        payments=[PaymentLine(shop.method("credit"), Decimal("50000"))],
        counted_cash="0",
        z_photo=jpeg(),
    )
    assert closed.status == "closed"


def test_receipts_mode_counts_the_credit_sales_on_the_nasiya_method(till):
    SalesSettings.objects.filter(company=till.company).update(mode="receipts")
    sale(till, "40000")
    [line] = services.receipt_lines(till.shift)
    assert line.method.kind == "credit" and line.sales == Decimal("40000")


def test_cancelling_nasiya_typed_by_mistake(till):
    entry = sale(till, "50000")
    services.void_credit(entry, by=till.cashier, reason="Wrong customer")
    entry.debt.refresh_from_db()
    assert entry.debt.status == "cancelled"
    assert services.owed(till.regular, currency="UZS") == 0
    kept = sale(till, "70000")
    payment = services.record_credit(
        by=till.cashier, kind="payment", customer=till.regular, amount="20000"
    )
    with pytest.raises(DomainError):
        services.void_credit(kept, by=till.cashier, reason="Paid already")
    services.void_credit(payment, by=till.cashier, reason="Typo")
    assert services.owed(till.regular, currency="UZS") == Decimal("70000.00")
    assert cash.expected_cash(till.shift) == Decimal("100000.00")


def test_aging_puts_each_debt_in_its_bucket(till):
    today = till.shift.business_day
    for amount, days_ago in (("10000", 5), ("20000", 45), ("30000", 90)):
        entry = sale(till, amount)
        Debt.objects.filter(pk=entry.debt_id).update(
            issued_on=today - timedelta(days=days_ago + 30),
            due_on=today - timedelta(days=days_ago),
        )
    fresh = sale(till, "40000")
    assert fresh.debt.due_on > today
    found = queries.aging(till.company, today, branch_ids=None)
    assert found["totals"] == {
        "not_due": "40000.00",
        "d0_30": "10000.00",
        "d31_60": "20000.00",
        "d60_plus": "30000.00",
    }
    [row] = found["customers"]
    assert row["name"] == "Saida opa" and row["total"] == "100000.00"
    # Another branch's people see none of it.
    assert queries.aging(till.company, today, branch_ids=[till.other_branch.pk])["total"] == "0.00"


def test_overdue_nasiya_reminds_the_responsible_once_a_day(till):
    entry = sale(till, "65000")
    today = till.shift.business_day + timedelta(days=40)
    Debt.objects.filter(pk=entry.debt_id).update(due_on=today - timedelta(days=3))
    morning = datetime(today.year, today.month, today.day, 9, 30, tzinfo=TASHKENT)
    assert reminders.remind(morning - timedelta(hours=3)) == 0  # before the morning window
    assert reminders.remind(morning) == 1
    assert reminders.remind(morning + timedelta(minutes=15)) == 0
    [told] = Notification.objects.filter(kind="sales.customer_debt_due")
    assert told.recipient_id == till.cashier.pk and "Saida opa" in told.title
    assert Debt.objects.get(pk=entry.debt_id).last_reminded_on == today
    # The next morning again (finance's weekly reminder would wait a week).
    assert reminders.remind(morning + timedelta(days=1)) == 1


def test_kassa_finds_customers_by_phone_and_records_nasiya(till, api_as):
    client = api_as(till.cashier)
    base = f"/api/v1/companies/{till.company.pk}/sales"
    found = client.get(f"{base}/customers/lookup/", {"phone": "4567"}).json()["results"]
    assert [row["name"] for row in found] == ["Saida opa"] and found[0]["owed"] == "0.00"
    made = client.post(
        f"{base}/credit/",
        {
            "kind": "sale",
            "new_customer": {"name": "Rustam aka", "phone": "93 555 66 77"},
            "amount": "45000",
        },
        format="json",
    )
    assert made.status_code == 201, made.content
    assert made.json()["owed"] == "45000.00" and made.json()["customer"]["name"] == "Rustam aka"
    paid = client.post(
        f"{base}/credit/",
        {"kind": "payment", "customer_id": made.json()["customer"]["id"], "amount": "5000"},
        format="json",
    )
    assert paid.status_code == 201 and paid.json()["owed"] == "40000.00"
    current = client.get(f"{base}/shifts/current/").json()
    assert current["settings"]["credit"] is True
    assert current["shift"]["credit"]["sales"] == "45000.00"
    assert current["shift"]["credit"]["payments"] == "5000.00"
    voided = client.post(
        f"{base}/credit/{paid.json()['id']}/void/", {"reason": "Typo"}, format="json"
    )
    assert voided.status_code == 200
    # Someone else's entry is out of reach.
    other = api_as(till.colleague)
    assert other.post(
        f"{base}/credit/{made.json()['id']}/void/", {"reason": "x"}, format="json"
    ).status_code in (403, 404)


def test_owner_customer_pages_need_sales_view_and_hide_other_companies(
    till, owner_api, other_company, member
):
    sale(till, "30000")
    url = f"/api/v1/owner/companies/{till.company.pk}/sales"
    client = owner_api(till.owner)
    rows = client.get(f"{url}/customers/").json()
    assert rows["count"] == 1 and rows["results"][0]["owed"] == "30000.00"
    detail = client.get(f"{url}/customers/{till.regular.pk}/").json()
    assert detail["debts"][0]["left"] == "30000.00" and detail["credit"][0]["kind"] == "sale"
    assert client.get(f"{url}/receivables/aging/").json()["total"] == "30000.00"
    made = client.post(
        f"{url}/customers/",
        {"name": "Dori-Darmon MCHJ", "kind": "company", "phone": "71 200 30 40"},
        format="json",
    )
    assert made.status_code == 201 and made.json()["kind"] == "company"
    nobody = scoped_role(till.company, Perm.BRANCHES_ALL)
    person = make_member(till.company, "Owner")
    person.role = nobody
    person.save(update_fields=["role"])
    assert owner_api(person).get(f"{url}/customers/").status_code == 403
    seller = scoped_role(till.company, Perm.SALES_VIEW, Perm.BRANCHES_ALL)
    viewer = make_member(till.company, "Owner")
    viewer.role = seller
    viewer.save(update_fields=["role"])
    assert (
        owner_api(viewer).post(f"{url}/customers/", {"name": "X"}, format="json").status_code == 403
    )
    stranger = member(other_company, "Owner")
    assert owner_api(stranger).get(f"{url}/customers/{till.regular.pk}/").status_code == 404
    assert CreditEntry.objects.count() == 1


def test_credit_days_is_a_setting(till):
    SalesSettings.objects.filter(company=till.company).update(credit_days=10)
    entry = sale(till, "1000")
    assert entry.debt.due_on == till.shift.business_day + timedelta(days=10)
    assert date.today()  # the shift's business day drives the due date, not the clock
