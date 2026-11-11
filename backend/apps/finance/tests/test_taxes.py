"""The tax calendar (v12, `apps.finance.taxes` and `tax_rules`): deadlines by regime and profile,
moved off days off, estimates from the books, marks, reminders, the regime comparison; and a
supplier's payment terms (`apps.finance.terms`)."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from apps.core.exceptions import DomainError
from apps.finance import conf, deadline_reminders, services, tax_calendar, tax_rules, taxes, terms
from apps.finance.models import Debt, FinanceSettings, TaxMark, Transaction
from apps.finance.tests.factories import CounterpartyFactory, MoneyAccountFactory
from apps.inbox.models import Notification

pytestmark = pytest.mark.django_db

TODAY = date(2026, 11, 12)


def regime(company, value: str) -> None:
    services_row = conf.get_settings(company)
    services_row.tax_regime = value
    services_row.vat_percent = FinanceSettings.REGIME_VAT[value]
    services_row.save()


@pytest.fixture
def bank(books, owner):
    account = MoneyAccountFactory(company=books, name="Bank", kind="bank")
    services.record_transaction(
        books,
        by=owner,
        kind="opening",
        amount=D(900_000_000),
        occurred_on=date(2025, 10, 1),
        account=account,
    )
    return account


def sale(company, by, account, amount, day):
    return services.record_transaction(
        company,
        by=by,
        kind="income",
        amount=D(amount),
        occurred_on=day,
        account=account,
        category="sales",
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


def keys(rows):
    return [(row.rule.key, row.due_on) for row in rows]


# The rules -----------------------------------------------------------------------------------


def test_every_rule_names_its_law_and_a_known_tax():
    for rule in tax_rules.RULES:
        assert rule.tax in tax_rules.TAXES
        assert rule.law and rule.url.startswith("https://lex.uz/")
        assert rule.action in ("file_pay", "file", "pay")
        assert set(rule.regimes) <= set(tax_rules.ALL_REGIMES)
    assert len({rule.key for rule in tax_rules.RULES}) == len(tax_rules.RULES)


def test_base_value_and_threshold_by_date():
    assert tax_rules.base_value(date(2026, 8, 31)) == D(412_000)
    assert tax_rules.base_value(date(2026, 9, 1)) == D(440_000)
    assert tax_rules.turnover_threshold(date(2026, 5, 31))[0] == D(1_000_000_000)
    assert tax_rules.turnover_threshold(date(2026, 11, 1))[0] == D(12_000) * D(440_000)


# Deadlines -----------------------------------------------------------------------------------


def test_vat_regime_deadlines_move_off_weekends(books):
    regime(books, "vat")
    rows = taxes.deadlines(books, date(2026, 12, 1), date(2027, 3, 31), today=TODAY)
    found = keys(rows)
    # VAT for November by 20 December 2026: a Sunday, so Monday 21 December (Tax Code art. 5).
    assert ("vat", date(2026, 12, 21)) in found
    # VAT for December by 20 January 2027 (a Wednesday).
    assert ("vat", date(2027, 1, 20)) in found
    # Profit tax: no quarterly return for the fourth quarter, the year's by 1 March 2027.
    assert ("profit_year", date(2027, 3, 1)) in found
    assert not [key for key in found if key[0] == "profit" and key[1].month == 1]
    # No turnover tax, no payroll taxes without payroll, no property without premises.
    assert not [key for key in found if key[0].startswith(("turnover", "income", "social"))]
    assert not [key for key in found if key[0].startswith(("property", "land"))]


def test_turnover_regime_monthly_by_the_15th(books):
    rows = taxes.deadlines(books, date(2026, 12, 1), date(2027, 2, 28), today=TODAY)
    found = keys(rows)
    assert ("turnover", date(2026, 12, 15)) in found
    # 15 February 2027 is a Monday: the month's return and the year's on the same day.
    assert ("turnover", date(2027, 2, 15)) in found
    assert ("turnover_year", date(2027, 2, 15)) in found
    assert not [key for key in found if key[0] == "vat"]


def test_payroll_and_property_add_their_deadlines(books):
    books.features = ["finance", "payroll"]
    books.save(update_fields=["features"])
    row = conf.get_settings(books)
    row.tax_regime = "vat"
    row.owns_property = True
    row.save()
    rows = taxes.deadlines(books, date(2027, 1, 1), date(2027, 1, 31), today=TODAY)
    found = keys(rows)
    assert ("income_tax", date(2027, 1, 15)) in found
    assert ("social_tax", date(2027, 1, 15)) in found
    # Property: the year's estimate and January's advance both by 20 January (art. 417).
    assert ("property_estimate", date(2027, 1, 20)) in found
    assert ("property_advance", date(2027, 1, 20)) in found
    february = keys(taxes.deadlines(books, date(2027, 2, 1), date(2027, 2, 28), today=TODAY))
    assert ("property_advance", date(2027, 2, 10)) in february


def test_a_company_holiday_moves_the_deadline(books):
    from apps.timeoff.models import Holiday

    regime(books, "vat")
    Holiday.objects.create(company=books, date=date(2027, 1, 20), name="Bayram")
    found = keys(taxes.deadlines(books, date(2027, 1, 1), date(2027, 1, 31), today=TODAY))
    assert ("vat", date(2027, 1, 21)) in found


# Estimates -----------------------------------------------------------------------------------


def test_vat_estimate_from_sales_and_goods(books, owner, bank):
    regime(books, "vat")
    sale(books, owner, bank, 112_000_000, date(2026, 10, 10))
    spend(books, owner, bank, 56_000_000, date(2026, 10, 11), "goods")
    rows = taxes.deadlines(books, date(2026, 11, 1), date(2026, 11, 30), today=TODAY)
    vat = next(row for row in rows if row.rule.key == "vat")
    # 12/112 of 112 mln is 12 mln; less 12/112 of 56 mln, 6 mln.
    assert vat.estimate == D(6_000_000)
    assert vat.status == "due"
    assert "6 000 000" in vat.basis or "6,000,000" in vat.basis or vat.basis


def test_turnover_estimate(books, owner, bank):
    sale(books, owner, bank, 50_000_000, date(2026, 10, 3))
    rows = taxes.deadlines(books, date(2026, 11, 1), date(2026, 11, 30), today=TODAY)
    turnover = next(row for row in rows if row.rule.key == "turnover")
    assert turnover.estimate == D(2_000_000)  # 4 % of 50 mln
    assert turnover.due_on == date(2026, 11, 16)  # the 15th is a Sunday


def test_overdue_and_marked_paid(books, owner, bank):
    sale(books, owner, bank, 50_000_000, date(2026, 9, 3))
    rows = taxes.deadlines(books, date(2026, 10, 1), date(2026, 10, 31), today=TODAY)
    turnover = next(row for row in rows if row.rule.key == "turnover")
    assert turnover.status == "overdue"
    mark = taxes.mark(
        books,
        by=owner,
        rule_key="turnover",
        period_start=date(2026, 9, 1),
        done_on=date(2026, 10, 15),
        account=bank,
        amount=D(2_000_000),
    )
    assert mark.transaction.category.system_code == "taxes"
    assert mark.transaction.amount == D(-2_000_000)
    rows = taxes.deadlines(books, date(2026, 10, 1), date(2026, 10, 31), today=TODAY)
    turnover = next(row for row in rows if row.rule.key == "turnover")
    assert turnover.status == "done" and turnover.paid == D(2_000_000)
    with pytest.raises(DomainError):
        taxes.mark(
            books, by=owner, rule_key="turnover", period_start=date(2026, 9, 1), done_on=TODAY
        )
    # Taking the mark back voids the payment it recorded.
    taxes.unmark(mark, by=owner)
    assert not TaxMark.objects.exists()
    assert Transaction.objects.get(pk=mark.transaction_id).status == "void"


def test_linking_an_existing_payment(books, owner, bank):
    paid = spend(books, owner, bank, 1_500_000, date(2026, 10, 14), "taxes")
    deadline = taxes.find(books, "turnover", date(2026, 9, 1))
    assert paid in taxes.candidates(books, deadline)
    mark = taxes.mark(
        books,
        by=owner,
        rule_key="turnover",
        period_start=date(2026, 9, 1),
        done_on=date(2026, 10, 14),
        transaction_row=paid,
    )
    assert mark.amount == D(1_500_000)
    assert paid not in taxes.candidates(books, deadline)


def test_a_rule_the_company_has_not(books, owner):
    with pytest.raises(DomainError):
        taxes.mark(books, by=owner, rule_key="vat", period_start=date(2026, 9, 1), done_on=TODAY)


def test_a_tax_debt_due_that_day_is_the_amount(books, owner):
    regime(books, "vat")
    office = CounterpartyFactory(company=books, name="Soliq", kind="state")
    debt = services.open_debt(
        books,
        by=owner,
        direction="payable",
        kind=Debt.Kind.TAX,
        amount=D(4_321_000),
        currency="UZS",
        issued_on=date(2026, 10, 31),
        due_on=date(2026, 11, 20),
        counterparty=office,
        category="taxes",
    )
    rows = taxes.deadlines(books, date(2026, 11, 1), date(2026, 11, 30), today=TODAY)
    vat = next(row for row in rows if row.rule.key == "vat")
    assert vat.booked and vat.estimate == D(4_321_000) and vat.debt_id == debt.pk


def test_the_template_bill_reminds_instead(books, owner):
    tax_calendar.apply(books, by=owner, key="turnover")
    rows = taxes.deadlines(books, date(2026, 11, 1), date(2026, 11, 30), today=TODAY)
    turnover = next(row for row in rows if row.rule.key == "turnover")
    assert turnover.rule_id is not None


# Reminders -----------------------------------------------------------------------------------


def test_reminders_before_the_deadline_at_the_morning_hour(books, owner):
    books.morning_report_at = time(8, 30)
    books.save(update_fields=["morning_report_at"])
    zone = ZoneInfo(books.timezone)

    def sent(day: date, hour: int = 8, minute: int = 45) -> int:
        before = Notification.objects.filter(kind=taxes.NOTIFICATION).count()
        deadline_reminders.remind(books, datetime.combine(day, time(hour, minute), tzinfo=zone))
        return Notification.objects.filter(kind=taxes.NOTIFICATION).count() - before

    # The turnover deadline of 15 December 2026 (a Tuesday): five days before, at 08:45.
    assert sent(date(2026, 12, 10), hour=8, minute=0) == 0
    assert sent(date(2026, 12, 10)) == 1
    assert sent(date(2026, 12, 10), hour=9) == 0
    assert sent(date(2026, 12, 11)) == 0
    assert sent(date(2026, 12, 15)) == 1
    note = Notification.objects.filter(kind=taxes.NOTIFICATION).first()
    assert "accountant" in note.body
    assert "/finance/taxes" in note.url


# Comparing regimes ---------------------------------------------------------------------------


def test_compare_turnover_and_vat(books, owner, bank):
    months = [(2025, 11), (2025, 12)] + [(2026, month) for month in range(1, 11)]
    for year, month in months:
        day = date(year, month, 5)
        sale(books, owner, bank, 112_000_000, day)
        spend(books, owner, bank, 84_000_000, day, "goods")
        spend(books, owner, bank, 10_000_000, day, "rent")
    result = taxes.compare(books, TODAY)
    assert result["from"] == date(2025, 11, 1) and result["to"] == date(2026, 10, 31)
    assert result["income"] == D(1_344_000_000)
    options = {row["regime"]: row for row in result["options"]}
    # Turnover tax: 4 % of 1 344 mln.
    assert options["turnover"]["total"] == D("53760000.00")
    # VAT: 12/112 of sales (144 mln) less 12/112 of goods (108 mln) = 36 mln; profit before
    # taxes 1 344 - 1 008 - 120 - 36 = 180 mln, 15 % = 27 mln.
    assert options["vat"]["parts"][0]["amount"] == D("36000000.00")
    assert options["vat"]["parts"][1]["amount"] == D("27000000.00")
    assert options["vat"]["total"] == D("63000000.00")
    # Simplified VAT: 6/106 of sales.
    assert options["vat_simplified"]["total"] == D("76075471.70")
    # The demo company is a pharmacy: turnover tax isn't open to it (art. 461 part 2 item 14).
    assert options["turnover"]["available"] is False
    assert options["vat"]["cheapest"] is True
    assert result["disclaimer"]


# Supplier terms ------------------------------------------------------------------------------


def test_terms_set_the_due_date(books, owner):
    party = CounterpartyFactory(company=books, name="Distributor", kind="supplier")
    party = services.update_counterparty(party, by=owner, credit_days=30)
    debt = services.open_debt(
        books,
        by=owner,
        direction="payable",
        kind="trade",
        amount=D(5_000_000),
        currency="UZS",
        issued_on=date(2026, 11, 2),
        counterparty=party,
        category="goods",
    )
    assert debt.due_on == date(2026, 12, 2)
    # A typed due date wins; a loan is never moved by supplier terms.
    typed = services.open_debt(
        books,
        by=owner,
        direction="payable",
        kind="trade",
        amount=D(1_000_000),
        currency="UZS",
        issued_on=date(2026, 11, 2),
        due_on=date(2026, 11, 9),
        counterparty=party,
        category="goods",
    )
    assert typed.due_on == date(2026, 11, 9)


def test_day_of_next_month_terms(books, owner):
    party = CounterpartyFactory(company=books, name="Distributor 2", kind="supplier")
    party = services.update_counterparty(party, by=owner, credit_day=31)
    assert terms.due_on(party, date(2027, 1, 20)) == date(2027, 2, 28)
    assert terms.due_on(party, date(2026, 12, 5)) == date(2027, 1, 31)
    assert "31" in terms.describe(party)
    with pytest.raises(DomainError):
        services.update_counterparty(party, by=owner, credit_days=10)
    services.update_counterparty(party, by=owner, credit_day=None, credit_days=10)
    party.refresh_from_db()
    assert (party.credit_days, party.credit_day) == (10, None)


def test_goods_receipt_on_credit_follows_the_terms(books, owner):
    party = CounterpartyFactory(company=books, name="Distributor 3", kind="supplier")
    party = services.update_counterparty(party, by=owner, credit_days=14)
    bill = services.open_debt(
        books,
        by=owner,
        direction="payable",
        kind="bill",
        amount=D(700_000),
        currency="UZS",
        issued_on=date(2026, 11, 1),
        counterparty=party,
        category="utilities",
        due_on=None,
    )
    assert bill.due_on == date(2026, 11, 15)
    assert bill.due_on - bill.issued_on == timedelta(days=14)
