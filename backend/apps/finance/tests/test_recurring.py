"""Recurring payments and the tax calendar (Package I): the schedule, holiday moves, paying
and posting idempotent per due date, reminders, and the owner endpoints."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.companies.models import Branch
from apps.core.exceptions import DomainError
from apps.finance import queries, recurring, reminders, tax_calendar
from apps.finance.models import (
    Category,
    Counterparty,
    Debt,
    MoneyAccount,
    RecurringRule,
    Transaction,
)
from apps.finance.tests.factories import CounterpartyFactory
from apps.inbox.models import Notification
from apps.members.permissions import Perm
from apps.timeoff.models import Holiday

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


# The schedule -----------------------------------------------------------------------------------


def schedule(**fields) -> RecurringRule:
    values = {
        "frequency": "monthly",
        "interval": 1,
        "day": 31,
        "starts_on": date(2026, 1, 1),
        "ends_on": None,
    }
    values.update(fields)
    return RecurringRule(**values)


def test_monthly_on_the_31st_takes_the_last_day_of_short_months():
    plan = schedule()
    days = []
    after = None
    for _ in range(4):
        after = recurring.scheduled_after(plan, after)
        days.append(after)

    assert days == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]


def test_quarterly_yearly_and_every_two_weeks():
    quarterly = schedule(frequency="quarterly", day=25, starts_on=date(2026, 1, 1))
    assert recurring.scheduled_after(quarterly, date(2026, 1, 25)) == date(2026, 4, 25)
    yearly = schedule(frequency="yearly", day=15, starts_on=date(2026, 3, 1))
    assert recurring.scheduled_after(yearly, date(2026, 3, 15)) == date(2027, 3, 15)
    fortnight = schedule(frequency="weekly", interval=2, day=1, starts_on=date(2026, 11, 4))
    first = recurring.scheduled_after(fortnight, None)
    assert first == date(2026, 11, 9)  # the first Monday on or after the start
    assert recurring.scheduled_after(fortnight, first) == date(2026, 11, 23)


def test_a_day_before_the_start_moves_to_the_next_period_and_it_ends():
    plan = schedule(day=5, starts_on=date(2026, 11, 10), ends_on=date(2027, 1, 31))

    assert recurring.scheduled_after(plan, None) == date(2026, 12, 5)
    assert recurring.scheduled_after(plan, date(2027, 1, 5)) is None


def test_holidays_move_the_due_day_before_or_after():
    days_off = {date(2026, 3, 20), date(2026, 3, 21), date(2026, 3, 22)}

    assert recurring.shift(date(2026, 3, 21), "before", days_off) == date(2026, 3, 19)
    assert recurring.shift(date(2026, 3, 21), "after", days_off) == date(2026, 3, 23)
    assert recurring.shift(date(2026, 3, 21), "keep", days_off) == date(2026, 3, 21)
    assert recurring.shift(date(2026, 3, 24), "before", days_off) == date(2026, 3, 24)


# Rules ------------------------------------------------------------------------------------------


def test_a_new_rule_starts_from_today(fin, boss, today):
    made = rule(fin, boss, starts_on=today - timedelta(days=90), day=today.day)

    assert made.next_due_on == today
    assert made.currency == "UZS"
    assert AuditLog.objects.filter(action="finance.recurring_created").count() == 1


def test_an_automatic_rule_needs_an_account_and_a_fixed_amount(fin, boss, kassa):
    with pytest.raises(DomainError):
        rule(fin, boss, mode="auto")
    with pytest.raises(DomainError):
        rule(fin, boss, mode="auto", account=kassa, amount_varies=True)


def test_a_bill_category_must_match_its_kind(fin, boss):
    with pytest.raises(DomainError):
        rule(fin, boss, kind="income")  # rent is an expense category


def test_paying_a_bill_books_once_per_due_date_and_moves_on(fin, boss, kassa, today):
    bill = rule(fin, boss, day=today.day, starts_on=today)
    due = bill.next_due_on

    payment = recurring.pay_occurrence(bill, by=boss, account=kassa)

    row = payment.transaction
    assert (row.kind, row.amount, row.source_type) == (
        "expense",
        Decimal("-12000000.00"),
        "finance.recurring",
    )
    assert row.source_key == due.isoformat()
    bill.refresh_from_db()
    assert bill.last_done_on == due
    assert bill.next_due_on > due
    # A second pay of the same occurrence (two people pressing at once) books nothing more:
    # the source is the due date.
    again = recurring.services.record_transaction(
        fin,
        by=boss,
        kind="expense",
        amount=Decimal("12000000"),
        occurred_on=today,
        account=kassa,
        category=bill.category,
        source=recurring.Source(recurring.SOURCE, bill.pk, due.isoformat()),
    )
    assert again.pk == row.pk
    assert Transaction.objects.filter(source_type="finance.recurring").count() == 1


def test_a_varying_bill_takes_the_paid_amount_as_its_next_estimate(fin, boss, kassa, today):
    bill = rule(fin, boss, name="Electricity", amount=0, amount_varies=True, day=today.day)

    with pytest.raises(DomainError):
        recurring.pay_occurrence(bill, by=boss, account=kassa)  # no amount, no estimate
    recurring.pay_occurrence(bill, by=boss, account=kassa, amount="830000")

    bill.refresh_from_db()
    assert bill.amount == Decimal("830000.00")


def test_skipping_and_stopping(fin, boss, today):
    bill = rule(fin, boss, day=today.day, starts_on=today)
    first = bill.next_due_on

    recurring.skip_occurrence(bill, by=boss)
    bill.refresh_from_db()
    assert bill.next_due_on > first
    assert not Transaction.objects.filter(source_type="finance.recurring").exists()

    recurring.stop_rule(bill, by=boss)
    with pytest.raises(DomainError):
        recurring.skip_occurrence(bill, by=boss)


def test_automatic_rules_post_on_their_due_day_once(fin, boss, kassa, today):
    auto = rule(
        fin,
        boss,
        name="Internet",
        mode="auto",
        account=kassa,
        amount="350000",
        day=today.day,
        starts_on=today,
    )
    now = timezone.now()

    assert recurring.run_due(now) == 1
    assert recurring.run_due(now) == 0  # the next occurrence isn't due yet

    row = Transaction.objects.get(source_type="finance.recurring")
    assert (row.amount, row.occurred_on, row.account) == (Decimal("-350000.00"), today, kassa)
    auto.refresh_from_db()
    assert auto.last_done_on == today


def test_an_automatic_rule_catches_up_missed_occurrences(fin, boss, kassa, today):
    auto = rule(
        fin,
        boss,
        mode="auto",
        account=kassa,
        amount="100000",
        frequency="weekly",
        day=today.isoweekday(),
        starts_on=today - timedelta(days=21),
    )
    RecurringRule.objects.filter(pk=auto.pk).update(next_due_on=today - timedelta(days=14))

    assert recurring.run_due(timezone.now()) == 3
    keys = sorted(
        Transaction.objects.filter(source_type="finance.recurring").values_list(
            "source_key", flat=True
        )
    )
    assert keys == [
        (today - timedelta(days=14)).isoformat(),
        (today - timedelta(days=7)).isoformat(),
        today.isoformat(),
    ]


def test_an_automatic_rule_without_money_waits(fin, boss, today):
    till = MoneyAccount.objects.create(company=fin, name="Empty till", kind="cash", currency="UZS")
    rule(fin, boss, mode="auto", account=till, amount="100000", day=today.day, starts_on=today)

    assert recurring.run_due(timezone.now()) == 0
    assert not Transaction.objects.filter(source_type="finance.recurring").exists()


def test_a_holiday_moves_an_automatic_post(fin, boss, kassa, today):
    tomorrow = today + timedelta(days=1)
    auto = rule(
        fin,
        boss,
        mode="auto",
        account=kassa,
        amount="100000",
        day=tomorrow.day,
        starts_on=tomorrow,
        on_holiday="before",
    )
    Holiday.objects.create(company=fin, date=tomorrow, name="Mustaqillik kuni")

    assert recurring.due_on(auto) == today
    assert recurring.run_due(timezone.now()) == 1
    row = Transaction.objects.get(source_type="finance.recurring")
    assert row.occurred_on == today
    assert row.source_key == tomorrow.isoformat()  # the occurrence keeps its scheduled day


def test_rules_of_a_company_with_finance_off_never_post(fin, boss, kassa, today):
    rule(fin, boss, mode="auto", account=kassa, amount="100000", day=today.day, starts_on=today)
    fin.features = []
    fin.save(update_fields=["features"])

    assert recurring.run_due(timezone.now()) == 0


# The tax calendar -------------------------------------------------------------------------------


def test_templates_follow_the_regime_and_apply_once(fin, boss):
    sets = tax_calendar.templates(fin)
    assert [entry["key"] for entry in sets] == ["turnover", "vat", "vat_simplified"]
    assert sets[0]["current"] is True
    assert "confirm" in sets[0]["note"]

    made = tax_calendar.apply(fin, by=boss, key="turnover")
    assert {r.template_key for r in made} == {
        "tax.turnover",
        "tax.income_tax",
        "tax.inps",
        "tax.social_tax",
    }
    assert all(r.mode == "bill" and r.amount_varies and r.amount == 0 for r in made)
    office = Counterparty.objects.get(company=fin, kind="state")
    assert all(r.counterparty_id == office.pk for r in made)
    turnover = next(r for r in made if r.template_key == "tax.turnover")
    assert (turnover.frequency, turnover.day, turnover.on_holiday) == ("quarterly", 25, "after")

    # Switching to VAT adds only what is new; the payroll taxes stay single.
    again = tax_calendar.apply(fin, by=boss, key="vat")
    assert {r.template_key for r in again} == {"tax.vat", "tax.profit"}
    assert tax_calendar.apply(fin, by=boss, key="vat") == []
    assert RecurringRule.objects.filter(company=fin, template_key="tax.income_tax").count() == 1


def test_template_rules_stay_editable(fin, boss):
    [vat, *_rest] = tax_calendar.apply(fin, by=boss, key="vat")

    recurring.update_rule(vat, by=boss, day=28)

    vat.refresh_from_db()
    assert vat.day == 28 and vat.template_key == "tax.vat"


def test_paying_a_payroll_tax_settles_the_tax_office_debts_first(fin, boss, kassa, today):
    [income_tax] = [
        r
        for r in tax_calendar.apply(fin, by=boss, key="turnover")
        if r.template_key == "tax.income_tax"
    ]
    RecurringRule.objects.filter(pk=income_tax.pk).update(next_due_on=today)
    income_tax.refresh_from_db()
    office = income_tax.counterparty
    owed = recurring.services.open_debt(
        fin,
        by=boss,
        direction="payable",
        kind="tax",
        amount="700000",
        currency="UZS",
        issued_on=today - timedelta(days=5),
        counterparty=office,
        category="payroll_taxes",
    )

    payment = recurring.pay_occurrence(income_tax, by=boss, account=kassa, amount="1000000")

    owed.refresh_from_db()
    assert owed.status == Debt.Status.PAID
    kinds = sorted(row.kind for row in payment.rows)
    assert kinds == ["debt_payment", "expense"]
    expense = next(row for row in payment.rows if row.kind == "expense")
    assert expense.amount == Decimal("-300000.00")  # only the rest is a new expense


# Reminders --------------------------------------------------------------------------------------


def at_morning(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 9, 30, tzinfo=TASHKENT)


def test_a_bill_is_reminded_in_the_morning_once_a_day(fin, boss, kassa, today):
    bill = rule(fin, boss, account=kassa, day=today.day, starts_on=today, remind_days_before=2)

    assert reminders.remind(at_morning(today) - timedelta(hours=3)) == 0  # 06:30: too early
    assert reminders.remind(at_morning(today)) == 1
    assert reminders.remind(at_morning(today) + timedelta(minutes=15)) == 0

    note = Notification.objects.get(kind="finance.bill_due")
    assert "Rent" in note.title and "due today" in note.title
    assert [a["key"] for a in note.actions] == ["paid", "later"]
    assert note.data["occurrence"] == bill.next_due_on.isoformat()


def test_the_paid_button_pays_the_reminded_occurrence_only(fin, boss, kassa, today):
    bill = rule(fin, boss, account=kassa, day=today.day, starts_on=today)
    reminders.remind(at_morning(today))
    note = Notification.objects.get(kind="finance.bill_due")

    assert "Paid from" in reminders.paid_action(note, boss, "")
    assert reminders.paid_action(note, boss, "") == "Already paid."
    assert Transaction.objects.filter(source_type="finance.recurring").count() == 1
    bill.refresh_from_db()
    assert bill.last_done_on == today


def test_the_payer_gets_one_task_per_bill_that_closes_when_it_is_paid(
    fin, boss, member, kassa, today
):
    """`create_task`: when a bill's reminders start, its payer gets a task due on the bill's day
    (once per occurrence, with nobody's name on it); paying the bill closes the task, and the
    next occurrence brings the next task."""
    from apps.tasks.models import Task

    payer = member.registered(fin, "Accountant", first_name="Sevara")
    due = today + timedelta(days=2)
    bill = rule(
        fin,
        boss,
        account=kassa,
        day=due.day,
        starts_on=today,
        remind_days_before=3,
        payer=payer,
        create_task=True,
    )
    assert bill.next_due_on == due

    reminders.remind(at_morning(today))
    reminders.remind(at_morning(today) + timedelta(minutes=30))  # the same occurrence: no second

    [task] = Task.objects.filter(assignee=payer)
    assert task.kind == Task.Kind.ASSIGNED and task.created_by is None and task.is_open
    assert task.title == "Pay: Rent"
    assert timezone.localtime(task.due_at, TASHKENT) == datetime(
        due.year, due.month, due.day, 18, 0, tzinfo=TASHKENT
    )
    assert "12 000 000" in task.description.replace("\xa0", " ")
    bill.refresh_from_db()
    assert (bill.task, bill.task_for) == (task, due)

    recurring.pay_occurrence(bill, by=boss, account=kassa, occurrence=due)

    task.refresh_from_db()
    bill.refresh_from_db()
    assert task.status == Task.Status.DONE and task.proof_text
    assert bill.task is None and bill.task_for == due
    later = bill.next_due_on
    reminders.remind(at_morning(later - timedelta(days=3)))
    assert Task.objects.filter(assignee=payer).count() == 2


def test_a_task_needs_a_payer_and_an_automatic_payment_gets_none(fin, boss, kassa, today):
    with pytest.raises(DomainError, match="who pays it"):
        rule(fin, boss, create_task=True)
    automatic = rule(
        fin, boss, mode="auto", account=kassa, day=today.day, starts_on=today, create_task=True
    )
    assert automatic.create_task is False


def test_without_the_switch_the_payer_gets_no_task(fin, boss, member, kassa, today):
    from apps.tasks.models import Task

    payer = member.registered(fin, "Accountant")
    rule(fin, boss, account=kassa, day=today.day, starts_on=today, payer=payer)
    reminders.remind(at_morning(today))
    assert not Task.objects.filter(assignee=payer).exists()
    assert Notification.objects.filter(kind="finance.bill_due", recipient=payer).exists()


def test_an_overdue_debt_reminds_its_responsible_person_weekly(fin, boss, member, today):
    jasur = member(fin, "Employee", first_name="Jasur")
    clinic = CounterpartyFactory(company=fin, name="Shifo klinikasi")
    debt = recurring.services.open_debt(
        fin,
        by=boss,
        direction="receivable",
        kind="trade",
        amount="2000000",
        currency="UZS",
        issued_on=today - timedelta(days=30),
        due_on=today - timedelta(days=5),
        counterparty=clinic,
        category="sales",
        responsible=jasur,
    )

    assert reminders.remind_debts(fin, today) == 1
    assert reminders.remind_debts(fin, today + timedelta(days=3)) == 0
    assert reminders.remind_debts(fin, today + timedelta(days=7)) == 1
    note = Notification.objects.filter(kind="finance.debt_due").order_by("pk").first()
    assert note.recipient_id == jasur.pk
    assert "Shifo klinikasi" in note.title and "5 days overdue" in note.title
    debt.refresh_from_db()
    assert debt.last_reminded_on == today + timedelta(days=7)


def test_several_overdue_debts_make_one_digest(fin, boss, member, today):
    jasur = member(fin, "Employee", first_name="Jasur")
    for name in ("Shifo klinikasi", "Barakat", "Nur dorixonasi"):
        recurring.services.open_debt(
            fin,
            by=boss,
            direction="receivable",
            kind="trade",
            amount="1000000",
            currency="UZS",
            issued_on=today - timedelta(days=30),
            due_on=today - timedelta(days=2),
            counterparty=CounterpartyFactory(company=fin, name=name),
            category="sales",
            responsible=jasur,
        )

    assert reminders.remind_debts(fin, today) == 1

    [note] = Notification.objects.filter(kind="finance.debt_due")
    assert note.title == "3 debts you look after are due or overdue"
    assert note.body.count("\n") == 2 and "Barakat" in note.body
    assert reminders.remind_debts(fin, today + timedelta(days=1)) == 0


# The API ------------------------------------------------------------------------------------------


def test_the_owner_crud(fin, boss, owner_api, kassa, today):
    client = owner_api(boss)
    rent = Category.objects.get(company=fin, system_code="rent")

    response = client.post(
        url(fin, "recurring/"),
        {
            "name": "Ijara",
            "frequency": "monthly",
            "day": 1,
            "category": rent.pk,
            "amount": "12000000",
            "starts_on": today.isoformat(),
            "account": kassa.pk,
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["amount"] == "12000000.00"
    assert body["mode"] == "bill"
    assert len(body["upcoming"]) == 3
    assert body["category"]["id"] == rent.pk

    pk = body["id"]
    assert client.get(url(fin, "recurring/")).json()[0]["id"] == pk
    patched = client.patch(url(fin, f"recurring/{pk}/"), {"amount": "13000000"}, format="json")
    assert patched.json()["amount"] == "13000000.00"

    paid = client.post(url(fin, f"recurring/{pk}/pay/"), {"account": kassa.pk}, format="json")
    assert paid.status_code == 200, paid.content
    assert paid.json()["transaction_id"]
    assert client.post(url(fin, f"recurring/{pk}/skip/")).status_code == 200
    assert client.post(url(fin, f"recurring/{pk}/run-now/")).status_code == 400  # a bill
    assert client.delete(url(fin, f"recurring/{pk}/")).status_code == 204
    assert client.get(url(fin, "recurring/")).json() == []
    assert len(client.get(url(fin, "recurring/?active=all")).json()) == 1


def test_templates_endpoints(fin, boss, owner_api):
    client = owner_api(boss)

    sets = client.get(url(fin, "recurring/templates/")).json()
    assert sets[0]["key"] == "turnover" and sets[0]["items"][0]["applied"] is False

    made = client.post(url(fin, "recurring/templates/turnover/apply/"))
    assert made.status_code == 201, made.content
    assert len(made.json()) == 4
    assert client.post(url(fin, "recurring/templates/nope/apply/")).status_code == 404
    assert client.get(url(fin, "recurring/templates/")).json()[0]["items"][0]["applied"] is True


def test_permissions_tenancy_and_branch_scope(
    fin, boss, owner_api, role, person, other_company, today
):
    viewer = person(fin, role(fin, "Viewer", [Perm.FINANCE_VIEW]))
    client = owner_api(viewer)
    rent = Category.objects.get(company=fin, system_code="rent")

    assert client.get(url(fin, "recurring/")).status_code == 200
    created = client.post(
        url(fin, "recurring/"),
        {
            "name": "X",
            "frequency": "monthly",
            "day": 1,
            "category": rent.pk,
            "amount": "1",
            "starts_on": today.isoformat(),
        },
        format="json",
    )
    assert created.status_code == 403
    assert client.post(url(fin, "recurring/templates/turnover/apply/")).status_code == 403
    assert owner_api(boss).get(url(other_company, "recurring/")).status_code == 404

    chilonzor = Branch.objects.create(company=fin, name="Chilonzor", code="CHL")
    yunusobod = Branch.objects.create(company=fin, name="Yunusobod", code="YNS")
    theirs = rule(fin, boss, name="Yunusobod rent", branch=yunusobod)
    head = person(
        fin, role(fin, "Head", [Perm.FINANCE_VIEW, Perm.FINANCE_MANAGE]), branches=[chilonzor]
    )
    scoped = owner_api(head)
    assert scoped.get(url(fin, "recurring/")).json() == []
    assert scoped.get(url(fin, f"recurring/{theirs.pk}/")).status_code == 404
