"""Money review of package I (v6 review, 2026-11-07): each test here failed on the code that
shipped in 0.4.2 and pins the fix (or is marked xfail with the reason when the fix is the
lead's call)."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from apps.finance import budgets, claims, queries, recurring, reminders, services, tax_calendar
from apps.finance.models import (
    Budget,
    Category,
    Debt,
    MoneyAccount,
    RecurringRule,
    Transaction,
)
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


# F3: merging a category that a bill, a budget or a claim uses -----------------------------------


def test_merging_a_category_moves_its_bills_budgets_and_claims(fin, boss, member, today):
    """The bills, budgets and claims of package I hold their category with PROTECT, and the
    merge only moved ledger rows: merging "Taksi" into "Yetkazib berish" was a 500."""
    jasur = member(fin, "Employee", first_name="Jasur")
    taxi = services.create_category(fin, by=boss, name="Taksi", kind="expense")
    delivery = services.create_category(fin, by=boss, name="Yetkazib berish", kind="expense")
    courier = rule(fin, boss, name="Courier", category=taxi, day=today.day, starts_on=today)
    month = today.replace(day=1)
    later = (month + timedelta(days=40)).replace(day=1)
    budgets.set_budgets(fin, by=boss, month=month, rows=[(taxi, "1000000"), (delivery, "2000000")])
    budgets.set_budgets(fin, by=boss, month=later, rows=[(taxi, "500000")])
    expense = claims.submit_claim(
        fin, by=jasur, amount="45000", category=taxi, spent_on=today, paid_from="own_money"
    )

    services.merge_category(taxi, into=delivery, by=boss)

    courier.refresh_from_db()
    expense.refresh_from_db()
    assert courier.category_id == delivery.pk
    assert expense.category_id == delivery.pk
    # The merged category's budget joins the target's: its actuals now hold both.
    assert sorted(
        Budget.objects.filter(company=fin).values_list("month", "category_id", "amount")
    ) == [(month, delivery.pk, Decimal("3000000.00")), (later, delivery.pk, Decimal("500000.00"))]
    assert not Category.objects.filter(pk=taxi.pk).exists()


# F4: a budget is "over" once it is spent, not at 99.5 % -----------------------------------------


@pytest.mark.parametrize(
    ("spent", "share", "status"),
    [
        ("2385000", "0.79", "ok"),  # 79.5 %: not yet 80 %
        ("2400000", "0.80", "warning"),
        ("2985000", "0.99", "warning"),  # 99.5 %: 15 000 left
        ("3000000", "1.00", "over"),
    ],
)
def test_budget_thresholds_are_reached_not_rounded_to(
    fin, boss, kassa, today, spent, share, status
):
    """The share was rounded half to even before the 80 % / 100 % comparison: 99.5 % of the
    rent budget read "over budget" and sent the 100 % alert with 15 000 so'm still left."""
    rent = Category.objects.get(company=fin, system_code="rent")
    month = today.replace(day=1)
    budgets.set_budgets(fin, by=boss, month=month, rows=[(rent, "3000000")])
    services.record_transaction(
        fin,
        by=boss,
        kind="expense",
        amount=spent,
        occurred_on=today,
        account=kassa,
        category=rent,
    )

    view = budgets.month_view(fin, month, branch_ids=None, today=today)
    [row] = [row for row in view["rows"] if row["category"]["id"] == rent.pk]
    assert (row["share"], row["status"]) == (share, status)
    budgets.check(fin, month)
    budget = Budget.objects.get(company=fin, month=month, category=rent)
    assert (budget.alerted_100_at is not None) == (status == "over")
    assert (budget.alerted_80_at is not None) == (status in ("warning", "over"))


# F5: a held-cash claim is booked on the cash the person holds, in the claim's currency -------


def test_held_cash_is_booked_on_the_account_in_the_base_currency(fin, boss, member, today):
    """`submit_claim` checks the cash held in the base currency but booked the expense on the
    holder's UZS account (the default of `account_for_holder`): in a company keeping its books
    in dollars it opened an empty "cash on hand (UZS)" account and booked the dollars there."""
    fin.base_currency = "USD"
    fin.save(update_fields=["base_currency"])
    jasur = member(fin, "Employee", first_name="Jasur")
    held = services.account_for_holder(fin, jasur, currency="USD")
    services.record_transaction(
        fin, by=boss, kind="opening", amount="500", occurred_on=today, account=held
    )
    transport = Category.objects.get(company=fin, system_code="transport")

    claim = claims.submit_claim(
        fin, by=jasur, amount="45", category=transport, spent_on=today, paid_from="held_cash"
    )

    row = claim.transaction
    assert (row.account_id, row.currency, row.amount) == (held.pk, "USD", Decimal("-45.00"))
    assert not MoneyAccount.objects.filter(company=fin, holder=jasur, currency="UZS").exists()


# F6: the fixed-asset categories are booked by the system, never claimed -------------------------


def test_the_fixed_asset_categories_are_not_offered_or_taken_for_a_claim(fin, boss, member, today):
    """Depreciation and "Fixed assets written off" (0.4.1) are booked by the assets module and
    move no money; the claim's category list (bot, mini app) offered them."""
    from apps.core.exceptions import DomainError
    from apps.finance import defaults

    defaults.ensure_asset_categories(fin)
    jasur = member(fin, "Employee", first_name="Jasur")
    offered = set(claims.expense_categories(fin).values_list("system_code", flat=True))
    assert not offered & {"depreciation", "asset_disposal"}
    depreciation = Category.objects.get(company=fin, system_code="depreciation")
    with pytest.raises(DomainError):
        claims.submit_claim(
            fin,
            by=jasur,
            amount="45000",
            category=depreciation,
            spent_on=today,
            paid_from="own_money",
        )


# F7: a claim's waiting entry is decided with its claim, never voided on its own ---------------


def test_a_waiting_claim_entry_is_not_voided_from_the_ledger(
    fin, boss, member, kassa, today, owner_api
):
    """A held-cash claim waits as a pending expense on the holder's account. The ledger refused
    to approve or reject it ("decide it there") but voided it: the claim then could be neither
    rejected nor cancelled (its entry was no longer pending), and approving it booked nothing."""
    jasur = member(fin, "Employee", first_name="Jasur")
    services.record_transaction(
        fin,
        by=boss,
        kind="income",
        amount="1000000",
        occurred_on=today,
        account=kassa,
        category="sales",
    )
    services.transfer(
        fin,
        by=boss,
        from_account=kassa,
        to_account=services.account_for_holder(fin, jasur),
        amount_out=Decimal("500000"),
        occurred_on=today,
    )
    transport = Category.objects.get(company=fin, system_code="transport")
    claim = claims.submit_claim(
        fin, by=jasur, amount="45000", category=transport, spent_on=today, paid_from="held_cash"
    )
    assert claim.transaction.status == Transaction.Status.PENDING
    client = owner_api(boss)
    entry = client.get(url(fin, f"transactions/{claim.transaction_id}/")).json()
    assert entry["can_void"] is False

    one = client.post(
        url(fin, f"transactions/{claim.transaction_id}/void/"), {"reason": "Stray"}, format="json"
    )
    many = client.post(
        url(fin, "transactions/bulk/"),
        {"action": "void", "ids": [claim.transaction_id], "reason": "Stray"},
        format="json",
    )

    assert one.status_code == 400, one.content
    assert many.json()["results"][0]["ok"] is False
    claims.decide_claim(claim, by=boss, approve=False, reason="No receipt")
    claim.refresh_from_db()
    assert claim.status == "rejected"
    assert claim.transaction.status == Transaction.Status.REJECTED
