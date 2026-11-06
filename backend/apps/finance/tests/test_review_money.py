"""Money review of package I (v6 review, 2026-11-07): each test here failed on the code that
shipped in 0.4.2 and pins the fix (or is marked xfail with the reason when the fix is the
lead's call)."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from apps.finance import queries, recurring, reminders, services, tax_calendar
from apps.finance.models import Category, Debt, MoneyAccount, RecurringRule, Transaction
from apps.inbox.models import Notification

pytestmark = pytest.mark.django_db
TASHKENT = ZoneInfo("Asia/Tashkent")


def url(company, path: str) -> str:
    return f"/api/v1/owner/companies/{company.pk}/finance/{path}"


def rule(company, by, **fields) -> RecurringRule:
    values = {
        "name": "Rent",
        "kind": "expense",
        "mode": "bill",
        "frequency": "monthly",
        "day": 5,
        "category": Category.objects.get(company=company, system_code="rent"),
        "amount": Decimal("12000000"),
        "starts_on": date(2026, 1, 1),
    }
    values.update(fields)
    return recurring.create_rule(company, by=by, **values)


@pytest.fixture
def boss(fin, member):
    return member(fin, "Owner", first_name="Dilnoza")


@pytest.fixture
def kassa(fin):
    account = MoneyAccount.objects.get(company=fin, kind=MoneyAccount.Kind.CASH)
    account.allow_negative = True
    account.save(update_fields=["allow_negative"])
    return account


@pytest.fixture
def today(fin):
    return queries.local_today(fin)


def booked(bill) -> int:
    return Transaction.objects.filter(
        source_type=recurring.SOURCE, source_id=bill.pk, status="posted"
    ).count()


# F1: paying, skipping or running a recurring payment acts on the occurrence the person saw -----


def test_paying_the_same_occurrence_twice_books_it_once(fin, boss, kassa, today, owner_api):
    """Two managers paying the rent from the dialog that shows "due 7 Nov" (or one dialog sent
    twice): the second request used to pay December's rent as well."""
    bill = rule(fin, boss, day=today.day, starts_on=today)
    client = owner_api(boss)
    body = {"account": kassa.pk, "amount": "12000000", "occurrence": today.isoformat()}

    first = client.post(url(fin, f"recurring/{bill.pk}/pay/"), body, format="json")
    second = client.post(url(fin, f"recurring/{bill.pk}/pay/"), body, format="json")

    assert first.status_code == 200, first.content
    assert second.status_code == 400, second.content
    assert second.json()["detail"] == "Already paid."
    assert booked(bill) == 1
    bill.refresh_from_db()
    assert bill.last_done_on == today


def test_skipping_or_running_the_same_occurrence_twice_acts_once(
    fin, boss, kassa, today, owner_api
):
    bill = rule(fin, boss, day=today.day, starts_on=today)
    internet = rule(
        fin, boss, name="Internet", mode="auto", account=kassa, day=today.day, starts_on=today
    )
    client = owner_api(boss)
    once = {"occurrence": today.isoformat()}

    skip = url(fin, f"recurring/{bill.pk}/skip/")
    assert client.post(skip, once, format="json").status_code == 200
    again = client.post(skip, once, format="json")
    assert again.status_code == 400, again.content
    bill.refresh_from_db()
    assert bill.last_done_on == today  # December's rent is still to pay, and reminded

    path = url(fin, f"recurring/{internet.pk}/run-now/")
    assert client.post(path, once, format="json").status_code == 200
    assert client.post(path, once, format="json").status_code == 400
    assert booked(internet) == 1


def test_the_due_day_after_a_holiday_move_names_the_same_occurrence(
    fin, boss, kassa, today, owner_api
):
    """The dashboard shows (and sends back) the due day after the holiday move."""
    from apps.timeoff.models import Holiday

    scheduled = date(today.year + 1, 3, 21)  # Navruz
    Holiday.objects.create(company=fin, date=scheduled, name="Navruz")
    bill = rule(fin, boss, frequency="yearly", day=21, starts_on=date(today.year + 1, 3, 1))
    assert bill.next_due_on == scheduled
    shown = recurring.due_on(bill)
    assert shown != scheduled

    response = owner_api(boss).post(
        url(fin, f"recurring/{bill.pk}/pay/"),
        {"account": kassa.pk, "occurrence": shown.isoformat(), "paid_on": today.isoformat()},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert booked(bill) == 1


def test_the_paid_button_racing_another_payment_books_nothing_more(
    fin, boss, kassa, today, monkeypatch
):
    """[Paid from Kassa] read the rule just before someone paid it in the dashboard: it used to
    pay the next occurrence too (its check ran before the rule was locked)."""
    bill = rule(fin, boss, account=kassa, day=today.day, starts_on=today)
    reminders.remind(datetime(today.year, today.month, today.day, 9, 30, tzinfo=TASHKENT))
    note = Notification.objects.get(kind="finance.bill_due")
    stale = RecurringRule.objects.select_related("company", "account").get(pk=bill.pk)
    recurring.pay_occurrence(bill, by=boss, account=kassa)  # the dashboard, a moment earlier
    monkeypatch.setattr(reminders, "_rule", lambda notification: stale)

    assert reminders.paid_action(note, boss, "") == "Already paid."
    assert booked(bill) == 1


# F2: a sales-tax bill settles only its own tax, never payroll's withheld taxes ----------------


def test_a_vat_bill_leaves_the_payroll_tax_debts_to_their_own_bills(fin, boss, kassa, today):
    """Payroll books the income tax it withholds as a payable to the tax office. Paying VAT used
    to settle that debt first: VAT read 700 000 less in "Taxes", and the income tax, paid on its
    own bill a few days later, was booked as an expense a second time."""
    made = {r.template_key: r for r in tax_calendar.apply(fin, by=boss, key="vat")}
    vat, income_tax = made["tax.vat"], made["tax.income_tax"]
    withheld = services.open_debt(
        fin,
        by=boss,
        direction="payable",
        kind="tax",
        amount="700000",
        currency="UZS",
        issued_on=today - timedelta(days=5),
        counterparty=vat.counterparty,
        category="salaries",
    )

    paid_vat = recurring.pay_occurrence(vat, by=boss, account=kassa, amount="30000000")

    withheld.refresh_from_db()
    assert (withheld.status, withheld.paid) == (Debt.Status.OPEN, Decimal("0.00"))
    [row] = paid_vat.rows
    assert (row.kind, row.amount, row.category.system_code) == (
        "expense",
        Decimal("-30000000.00"),
        "taxes",
    )

    paid_income_tax = recurring.pay_occurrence(income_tax, by=boss, account=kassa, amount="700000")
    withheld.refresh_from_db()
    assert withheld.status == Debt.Status.PAID
    assert [row.kind for row in paid_income_tax.rows] == ["debt_payment"]
